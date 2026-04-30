"""
fill_original2.py
==================
notices_original2.jsonl 의 빈 필드(category, keywords, importance)를
notices_labeled_v2.jsonl 과 규칙 기반 추출로 채운다.

실행:
    python model/extraction/fill_original2.py
"""

import json
import re
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ORIGINAL2_PATH = os.path.join(DATA_DIR, "notices_original2.jsonl")
LABELED_PATH = os.path.join(DATA_DIR, "notices_labeled_v2.jsonl")

# ── 카테고리 중요도 기준 ─────────────────────────────────────
CATEGORY_BASE_IMPORTANCE = {
    "제출":      1.0,
    "준비물":    0.85,
    "건강·안전": 0.80,
    "비용":      0.75,
    "일정":      0.70,
    "기타":      0.50,
}

URGENT_KEYWORDS = ["반드시", "꼭", "필수", "엄수", "마감", "당일", "즉시", "응급", "위급", "112"]

MONEY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
DATE_PATTERN  = re.compile(
    r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일)|(?<![\d.])(\d{1,2})[./](\d{1,2})(?!\d)"
)


MONTH_ONLY_PATTERN = re.compile(r"(?<!\d)([1-9]|1[012])월(?!\s*\d+\s*일)")


def rule_category(sentence: str) -> str:
    s = sentence
    if MONEY_PATTERN.search(s):
        return "비용"
    if any(k in s for k in ["제출", "제출해", "제출하", "내주", "보내주"]):
        return "제출"
    if any(k in s for k in ["준비", "가져", "챙겨", "구입", "지참"]):
        return "준비물"
    if any(k in s for k in ["안전", "건강", "마스크", "위험", "유괴", "실종", "신고", "치료", "감염", "질병"]):
        return "건강·안전"
    if DATE_PATTERN.search(s) or MONTH_ONLY_PATTERN.search(s) or any(k in s for k in ["일시", "기간", "까지", "예정", "실시", "평가"]):
        return "일정"
    return "기타"


def rule_importance(sentence: str, category: str) -> float:
    score = CATEGORY_BASE_IMPORTANCE.get(category, 0.5)
    if any(k in sentence for k in URGENT_KEYWORDS):
        score = min(1.0, score + 0.05)
    if DATE_PATTERN.search(sentence):
        score = min(1.0, score + 0.05)
    return round(score, 2)


# ── labeled 데이터 로드 → original_id 기준으로 그룹화 ───────────
def load_labeled_by_original_id(path: str) -> dict:
    groups: dict[int, list] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            oid = obj.get("original_id")
            if oid is not None:
                groups.setdefault(oid, []).append(obj)
    return groups


# ── labeled 그룹 → category/keywords/importance 집계 ───────────
def aggregate_from_labeled(entries: list) -> dict:
    todos = [e for e in entries if e.get("is_todo")]
    if not todos:
        return {"category": "", "keywords": "", "importance": ""}

    cats = []
    keywords = []
    importances = []
    for e in todos:
        cat = e.get("category") or rule_category(e["sentence"])
        cats.append(cat)
        imp = rule_importance(e["sentence"], cat)
        importances.append(imp)
        if imp >= 0.70:
            keywords.append(e["sentence"][:60])

    unique_cats = list(dict.fromkeys(cats))  # 순서 유지 중복 제거
    max_imp = max(importances) if importances else 0.5
    kw_str = " / ".join(keywords[:5])  # 상위 5개까지

    return {
        "category":   ", ".join(unique_cats),
        "keywords":   kw_str,
        "importance": str(max_imp),
    }


# ── 규칙 기반으로 원문에서 직접 추출 ────────────────────────────
def extract_from_text(text: str) -> dict:
    sentences = [s.strip() for s in re.split(r"[.。\n]", text) if len(s.strip()) > 8]

    todo_candidates = []
    for sent in sentences:
        # 안부인사·서명류 제외
        if re.search(r"안녕하십니까|안녕하세요|감사드립니다|교장$|^\d{4}\.", sent):
            continue
        cat = rule_category(sent)
        imp = rule_importance(sent, cat)
        if imp >= 0.65:
            todo_candidates.append({"sentence": sent, "category": cat, "importance": imp})

    if not todo_candidates:
        return {"category": "", "keywords": "", "importance": ""}

    cats = list(dict.fromkeys(c["category"] for c in todo_candidates))
    max_imp = max(c["importance"] for c in todo_candidates)
    keywords = [c["sentence"][:60] for c in todo_candidates if c["importance"] >= 0.70][:5]

    return {
        "category":   ", ".join(cats),
        "keywords":   " / ".join(keywords),
        "importance": str(max_imp),
    }


# ── 메인 처리 ─────────────────────────────────────────────────
def main():
    labeled_groups = load_labeled_by_original_id(LABELED_PATH)

    updated = []
    with open(ORIGINAL2_PATH, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            oid = obj["id"]

            if oid in labeled_groups:
                result = aggregate_from_labeled(labeled_groups[oid])
                # labeled 데이터에 todo 없으면 규칙 기반으로 폴백
                if not result["category"]:
                    result = extract_from_text(obj["original_text"])
                    method = "rule(fallback)"
                else:
                    method = "labeled"
            else:
                result = extract_from_text(obj["original_text"])
                method = "rule"

            obj["category"]   = result["category"]
            obj["keywords"]   = result["keywords"]
            obj["importance"] = result["importance"]
            updated.append(obj)
            print(f"[{method}] ID {oid:2d}: category={obj['category'][:40]!r}  imp={obj['importance']}")

    with open(ORIGINAL2_PATH, "w", encoding="utf-8") as f:
        for obj in updated:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"\n완료: {len(updated)}개 항목 업데이트 → {ORIGINAL2_PATH}")


if __name__ == "__main__":
    main()
