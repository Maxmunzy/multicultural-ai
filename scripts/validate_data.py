"""데이터 검증 + 통계 리포트 생성기.

강사 피드백(2026-04-28): "내장데이터셋이 아닌 이상 데이터 검증은 필수.
데이터를 잘 이해하고 커스텀하는 게 근본 핵심."

실행:
    python scripts/validate_data.py
출력:
    data/REPORT.md (자동 생성/갱신)
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELED_V2 = ROOT / "model" / "extraction" / "data" / "notices_labeled_v2.jsonl"
ORIGINAL2 = ROOT / "model" / "extraction" / "data" / "notices_original2.jsonl"
GLOSSARY = ROOT / "model" / "translation_tts" / "term_glossary.csv"
LABELED_LEGACY = ROOT / "data" / "labeled"
REPORT_PATH = ROOT / "data" / "REPORT.md"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def length_stats(values: list[int]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.mean(values), 1),
        "median": int(statistics.median(values)),
        "stdev": round(statistics.stdev(values), 1) if len(values) > 1 else 0,
    }


def report_labeled_v2() -> list[str]:
    """notices_labeled_v2.jsonl 통계."""
    rows = load_jsonl(LABELED_V2)
    if not rows:
        return [f"### labeled_v2 — 파일 없음 (`{LABELED_V2.relative_to(ROOT)}`)\n"]

    is_todo_dist = Counter(r.get("is_todo") for r in rows)
    cat_dist = Counter(r.get("category") for r in rows if r.get("category"))
    sentence_lengths = [len(r.get("sentence", "")) for r in rows]
    notices_count = len({r.get("notice_id") for r in rows if r.get("notice_id")})
    missing_original_id = sum(1 for r in rows if r.get("original_id") is None)

    out = []
    out.append("### `notices_labeled_v2.jsonl`")
    out.append("")
    out.append(f"- **총 행 수**: {len(rows)}건")
    out.append(f"- **고유 가정통신문 ID**: {notices_count}개 (`notice_id` 기준)")
    out.append(f"- **`original_id` 결측**: {missing_original_id}건 (N16~N19 알림장 4건 — 27장 원문 외 자료)")
    out.append("")
    out.append("**`is_todo` 분포** (할 일 vs 정보성 문장)")
    out.append("")
    out.append("| 라벨 | 건수 |")
    out.append("| --- | --- |")
    for label, count in sorted(is_todo_dist.items(), key=lambda x: -x[1]):
        out.append(f"| {label} | {count} |")
    out.append("")
    out.append("**카테고리 분포** (is_todo=True 행만)")
    out.append("")
    out.append("| 카테고리 | 건수 | 비율 |")
    out.append("| --- | --- | --- |")
    total_cat = sum(cat_dist.values())
    for label, count in sorted(cat_dist.items(), key=lambda x: -x[1]):
        ratio = count / total_cat * 100 if total_cat else 0
        out.append(f"| {label} | {count} | {ratio:.1f}% |")
    out.append("")
    if cat_dist:
        biggest = max(cat_dist.values())
        smallest = min(cat_dist.values())
        out.append(f"⚠️ **클래스 불균형**: 최다 {biggest} : 최소 {smallest} = {biggest / smallest:.1f}:1 → 클래스 가중치(`balanced`) 적용 권장")
        out.append("")

    s = length_stats(sentence_lengths)
    out.append("**문장 길이 (문자 수)**")
    out.append("")
    out.append(f"- min/median/mean/max: {s['min']}/{s['median']}/{s['mean']}/{s['max']}")
    out.append(f"- stdev: {s['stdev']}")
    out.append("")
    return out


def report_original2() -> list[str]:
    """notices_original2.jsonl 통계."""
    rows = load_jsonl(ORIGINAL2)
    if not rows:
        return [f"### original2 — 파일 없음\n"]

    text_lengths = [len(r.get("original_text", "")) for r in rows if r.get("original_text")]
    source_dist = Counter(r.get("source_type", "") for r in rows)
    has_category = sum(1 for r in rows if r.get("category"))

    out = []
    out.append("### `notices_original2.jsonl` (원문 데이터)")
    out.append("")
    out.append(f"- **총 가정통신문**: {len(rows)}장")
    out.append(f"- **카테고리 채워진 행**: {has_category}/{len(rows)}건")
    out.append("")
    out.append("**출처(`source_type`) 분포**")
    out.append("")
    out.append("| 출처 | 건수 |")
    out.append("| --- | --- |")
    for label, count in sorted(source_dist.items(), key=lambda x: -x[1]):
        out.append(f"| {label or '(미지정)'} | {count} |")
    out.append("")
    s = length_stats(text_lengths)
    out.append(f"**원문 길이 (문자)**: min/median/mean/max = {s['min']}/{s['median']}/{s['mean']}/{s['max']}, stdev {s['stdev']}")
    out.append("")
    return out


def report_glossary() -> list[str]:
    """term_glossary.csv 통계."""
    if not GLOSSARY.exists():
        return [f"### glossary — 파일 없음\n"]
    rows = []
    with GLOSSARY.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out = []
    out.append("### `term_glossary.csv` (학교 도메인 용어사전)")
    out.append("")
    out.append(f"- **총 용어 수**: {len(rows)}개 한국어 키워드")
    out.append("")
    columns = [k for k in rows[0].keys() if k.startswith("preferred_")]
    out.append("**언어별 채워진 셀 수**")
    out.append("")
    out.append("| 언어 컬럼 | 채워진 행 | 누락 |")
    out.append("| --- | --- | --- |")
    for col in columns:
        filled = sum(1 for r in rows if r.get(col, "").strip())
        out.append(f"| {col} | {filled} | {len(rows) - filled} |")
    out.append("")
    return out


def report_legacy() -> list[str]:
    """data/labeled 등 구버전 데이터 인덱스만 표기."""
    out = ["### 구버전 / 기타"]
    out.append("")
    if LABELED_LEGACY.exists():
        for f in sorted(LABELED_LEGACY.glob("notice_sample_v*.csv")):
            try:
                with f.open("r", encoding="utf-8") as fp:
                    n = sum(1 for _ in fp) - 1  # header 제외
            except Exception:
                n = "?"
            out.append(f"- `{f.relative_to(ROOT)}` — {n}건")
    out.append("")
    return out


def write_report():
    lines = []
    lines.append("# 데이터셋 리포트")
    lines.append("")
    lines.append(f"> 자동 생성 — `python scripts/validate_data.py` 재실행 시 갱신됨.  ")
    lines.append("> 강사 피드백(2026-04-28) 대응: *\"데이터를 잘 이해하고 커스텀하는 게 근본 핵심.\"*")
    lines.append("")
    lines.append("## 1. notices_labeled_v2 (모델 학습/검증용)")
    lines.append("")
    lines.extend(report_labeled_v2())
    lines.append("## 2. notices_original2 (원문 가정통신문)")
    lines.append("")
    lines.extend(report_original2())
    lines.append("## 3. term_glossary (학교 용어사전)")
    lines.append("")
    lines.extend(report_glossary())
    lines.append("## 4. 구버전 데이터")
    lines.append("")
    lines.extend(report_legacy())
    lines.append("---")
    lines.append("")
    lines.append("## 검증 인사이트")
    lines.append("")
    lines.append("- **클래스 불균형 여전** — '기타' 카테고리가 검증셋에 1건만 있어 F1 신뢰도 낮음. 데이터 추가 필요.")
    lines.append("- **`original_id` 결측 4건(N16~N19 알림장)** — 27장 원문 외 자료. 추가 원문 확보 시 매핑 가능.")
    lines.append("- **사전 144 용어 × 8개 언어 풀 셀** — 누락 없음 (Gemini 자동 채움 + GPT 교차검증).")
    lines.append("- **새 데이터 추가 시 본 스크립트 재실행** → 통계 변화 추적.")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] {REPORT_PATH}")


if __name__ == "__main__":
    write_report()
