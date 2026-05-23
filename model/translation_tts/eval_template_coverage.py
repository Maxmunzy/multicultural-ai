"""언어별 템플릿 hit rate + 용어 보존율 평가 스크립트.

튜터 피드백 대응: "9개 언어 지원인데 언어별 번역 품질 지표가 없다"
→ 이 스크립트를 실행해 언어별 템플릿 커버리지와 용어 보존율을 정량화한다.

실행:
    cd multicultural-ai
    python model/translation_tts/eval_template_coverage.py

출력:
    model/translation_tts/outputs/template_coverage/summary.md
    model/translation_tts/outputs/template_coverage/detail.csv
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import csv as _csv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# translator 모듈은 FastAPI 없이도 함수 단위로 import 가능
from app.services.translator import (  # noqa: E402
    _LANG_TEMPLATES,
    _classify_sentence,
    _extract_template_items,
    _extract_noun_for_template,
    _build_from_template,
    _extract_audience,
    _extract_recipient,
    _build_role_sets,
    _mask_protected_entities,
    _restore_protected_entities,
)

_DOCKER_GLOSSARY = Path("/app/external_model/translation_tts/term_glossary.csv")
_LOCAL_GLOSSARY  = Path(__file__).parent / "term_glossary.csv"


def _load_glossary() -> list:
    """Docker 경로 우선, 없으면 로컬 repo 경로로 fallback."""
    path = _DOCKER_GLOSSARY if _DOCKER_GLOSSARY.exists() else _LOCAL_GLOSSARY
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(_csv.DictReader(f))

# ── 평가용 문장 세트 ──────────────────────────────────────────────────────────
# (한국어 원문, 유형, 예상 포함 용어 목록)
EVAL_SENTENCES: list[tuple[str, str, list[str]]] = [
    # prepare
    ("수채화 물감과 붓을 준비해 주세요.", "prepare", ["수채화 물감", "붓"]),
    ("도화지와 색칠 도구를 준비해 주세요.", "prepare", ["도화지", "색칠 도구"]),
    ("체육복과 실내화를 준비해 주세요.", "prepare", ["체육복", "실내화"]),
    ("풍선과 찰흙을 준비해 주세요.", "prepare", ["풍선", "찰흙"]),
    # bring
    ("물통과 실내화를 챙겨 주세요.", "bring", ["물통", "실내화"]),
    ("체육복을 지참해 주세요.", "bring", ["체육복"]),
    # submit
    ("동의서를 담임선생님께 제출해 주세요.", "submit", ["동의서"]),
    ("받아쓰기 공책을 제출해 주세요.", "submit", ["받아쓰기 공책"]),
    # attend
    ("학부모 총회에 참석해 주세요.", "attend", ["학부모 총회"]),
    # pay
    ("급식비를 납부해 주세요.", "pay", []),           # glossary 미등록 명사 → noun extraction
    ("방과후학교 수강비를 납부해 주세요.", "pay", []),  # 동일
]

LANGS = list(_LANG_TEMPLATES.keys())  # vi, en, ru, ms, mn, zh, th, ja


def _term_preserved(output: str, expected_terms_ko: list[str], glossary: list, lang: str) -> int:
    """용어가 번역 결과에 보존됐는지 확인. 사전 기준 번역어로 판단."""
    if not expected_terms_ko:
        return 0
    lang_key = lang
    count = 0
    for ko in expected_terms_ko:
        for row in glossary:
            if row.get("korean", "").strip() == ko:
                preferred = row.get(f"preferred_{lang_key}", "").strip()
                if preferred and preferred in output:
                    count += 1
                    break
    return count


def run() -> None:
    glossary = _load_glossary()
    _build_role_sets(glossary)

    OUT_DIR = Path(__file__).parent / "outputs" / "template_coverage"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 결과 누적
    rows: list[dict] = []
    lang_stats: dict[str, dict] = {
        lang: {"template_hits": 0, "total": 0, "term_found": 0, "term_total": 0}
        for lang in LANGS
    }

    print("=" * 72)
    print("Template Coverage & Term Preservation Eval")
    print(f"언어: {', '.join(LANGS)}")
    print(f"문장 수: {len(EVAL_SENTENCES)}")
    print("=" * 72)

    for ko_text, expected_type, expected_ko_terms in EVAL_SENTENCES:
        print(f"\n[{expected_type}] {ko_text}")

        stype_detected = _classify_sentence(ko_text)
        masked, placeholders = _mask_protected_entities(ko_text, "vi")  # 슬롯 추출용

        for lang in LANGS:
            lang_stats[lang]["total"] += 1

            items = _extract_template_items(ko_text, glossary, lang)
            noun_fallback = False
            if not items:
                noun = _extract_noun_for_template(masked, stype_detected)
                if noun:
                    noun_fallback = True

            audience = _extract_audience(ko_text, lang)
            recipient = _extract_recipient(ko_text, lang)

            template_out = None
            if items:
                template_out = _build_from_template(
                    stype_detected, items, lang, audience, recipient
                )

            hit = template_out is not None
            if hit:
                lang_stats[lang]["template_hits"] += 1

            # 용어 보존 체크 (glossary 등록 용어만)
            if template_out and expected_ko_terms:
                found = _term_preserved(template_out, expected_ko_terms, glossary, lang)
                lang_stats[lang]["term_found"] += found
                lang_stats[lang]["term_total"] += len(expected_ko_terms)

            rows.append({
                "korean":          ko_text,
                "expected_type":   expected_type,
                "detected_type":   stype_detected,
                "lang":            lang,
                "items_found":     " | ".join(ko for ko, _ in items),
                "noun_fallback":   "Y" if noun_fallback else "N",
                "template_hit":    "Y" if hit else "N",
                "template_output": template_out or "(NLLB fallback)",
            })

            status = "✅ TEMPLATE" if hit else ("⚠️ noun_fallback" if noun_fallback else "❌ NLLB")
            out_preview = (template_out or "")[:60]
            print(f"  [{lang}] {status}  {out_preview}")

    # ── 언어별 요약 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("언어별 요약")
    print("=" * 72)
    print(f"{'언어':<6}  {'템플릿 hit율':>12}  {'용어 보존율':>12}")
    print("-" * 36)

    summary_rows: list[dict] = []
    for lang in LANGS:
        s = lang_stats[lang]
        hit_pct = s["template_hits"] / s["total"] * 100 if s["total"] else 0
        term_pct = (
            s["term_found"] / s["term_total"] * 100 if s["term_total"] else float("nan")
        )
        print(
            f"  {lang:<4}  {s['template_hits']}/{s['total']} ({hit_pct:.0f}%)"
            f"         {s['term_found']}/{s['term_total']} ({term_pct:.0f}%)"
            if s["term_total"]
            else f"  {lang:<4}  {s['template_hits']}/{s['total']} ({hit_pct:.0f}%)         -"
        )
        summary_rows.append({
            "lang":          lang,
            "template_hits": s["template_hits"],
            "total":         s["total"],
            "hit_rate_pct":  f"{hit_pct:.0f}",
            "term_found":    s["term_found"],
            "term_total":    s["term_total"],
            "term_rate_pct": f"{term_pct:.0f}" if s["term_total"] else "-",
        })

    # ── CSV 저장 ──────────────────────────────────────────────────────────────
    csv_path = OUT_DIR / "detail.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # ── Markdown 저장 ─────────────────────────────────────────────────────────
    md_path = OUT_DIR / "summary.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 언어별 템플릿 커버리지 & 용어 보존율\n\n")
        f.write("> 튜터 피드백 대응: 9개 언어 지원 정량 근거\n\n")
        f.write("## 언어별 요약\n\n")
        f.write("| 언어 | 템플릿 hit | hit율 | 용어 보존 | 보존율 |\n")
        f.write("|------|-----------|-------|----------|-------|\n")
        for s in summary_rows:
            f.write(
                f"| {s['lang']} | {s['template_hits']}/{s['total']} | {s['hit_rate_pct']}% "
                f"| {s['term_found']}/{s['term_total']} | {s['term_rate_pct']}% |\n"
            )
        f.write("\n## 평가 문장 목록\n\n")
        f.write("| # | 한국어 | 유형 | 감지 유형 |\n")
        f.write("|---|--------|------|----------|\n")
        seen = set()
        idx = 1
        for r in rows:
            key = r["korean"]
            if key not in seen:
                seen.add(key)
                f.write(f"| {idx} | {r['korean']} | {r['expected_type']} | {r['detected_type']} |\n")
                idx += 1
        f.write("\n## 해석\n\n")
        f.write(
            "- **템플릿 hit**: 해당 문장이 NLLB 없이 구조 템플릿으로 번역됨 → 학교 행동 문장 100% 구조 보장\n"
            "- **용어 보존율**: glossary 등록 용어가 번역 결과에 정확히 나타나는 비율\n"
            "- **NLLB fallback**: glossary 미등록 명사 포함 문장 → 명사만 NLLB 단독 번역 후 템플릿 조립\n"
        )

    print(f"\nCSV: {csv_path}")
    print(f"MD:  {md_path}")


if __name__ == "__main__":
    run()
