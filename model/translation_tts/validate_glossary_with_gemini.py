"""
term_glossary.csv의 vi 항목 전체를 Gemini로 검증.
배치 방식으로 요청해 rate limit 문제를 방지한다.
"""

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from gemini_helper import fill_glossary_column

GLOSSARY_PATH = Path(__file__).parent / "term_glossary.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "glossary_validation_vi.csv"


def normalize(text: str) -> str:
    return text.strip().lower()


def is_match(preferred: str, suggestion: str) -> bool:
    p = normalize(preferred)
    s = normalize(suggestion)
    return p == s or p in s or s in p


def main():
    with GLOSSARY_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("korean", "").strip()]

    total = len(rows)
    korean_terms = [r["korean"] for r in rows]
    print(f"총 {total}개 용어 배치 검증 시작 (10개씩 묶음)...\n")

    def on_progress(done, total):
        print(f"  [{done}/{total}] 완료")

    suggestions = fill_glossary_column(korean_terms, "vi", on_progress=on_progress)

    results = []
    match_count = 0
    mismatch_count = 0
    fail_count = 0

    for row in rows:
        korean = row["korean"]
        preferred = row.get("preferred_vi", "").strip()
        suggestion = suggestions.get(korean, "")

        if not suggestion:
            status = "no_response"
            fail_count += 1
        elif is_match(preferred, suggestion):
            status = "match"
            match_count += 1
        else:
            status = "mismatch"
            mismatch_count += 1

        results.append({
            "korean": korean,
            "preferred_vi": preferred,
            "gemini_suggestion": suggestion,
            "status": status,
            "note": row.get("note", ""),
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["korean", "preferred_vi", "gemini_suggestion", "status", "note"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n=== 결과 ===")
    print(f"전체:     {total}개")
    print(f"일치:     {match_count}개 ({match_count/total*100:.1f}%)")
    print(f"불일치:   {mismatch_count}개 ({mismatch_count/total*100:.1f}%)")
    print(f"응답없음: {fail_count}개 ({fail_count/total*100:.1f}%)")
    print(f"\n결과 저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
