"""
term_glossary.csv의 비어있는 언어 컬럼을 Gemini로 채운다.
언어당 1회 요청 → 총 8회 (무료 한도 20/day 내)
"""

import csv
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from gemini_helper import fill_glossary_column

GLOSSARY_PATH = Path(__file__).parent / "term_glossary.csv"
TARGET_LANGS = ["en", "zh", "th", "ms", "mn", "ru", "ja"]  # vi는 이미 완성
LANG_DELAY = 10.0  # 언어 간 딜레이 (초)


def main():
    with GLOSSARY_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    korean_terms = [r["korean"] for r in rows if r.get("korean", "").strip()]
    print(f"용어 {len(korean_terms)}개 × {len(TARGET_LANGS)}개 언어 시작\n")

    for lang in TARGET_LANGS:
        col = f"preferred_{lang}"
        already_filled = sum(1 for r in rows if r.get(col, "").strip())
        if already_filled == len(rows):
            print(f"[{lang}] 이미 완성됨 — 스킵")
            continue

        print(f"[{lang}] 번역 중...", end=" ", flush=True)
        suggestions = fill_glossary_column(korean_terms, lang)

        filled = 0
        for row in rows:
            korean = row.get("korean", "")
            if not row.get(col, "").strip() and suggestions.get(korean, "").strip():
                row[col] = suggestions[korean]
                filled += 1

        _save(rows, fieldnames)
        print(f"{filled}개 채움 → {GLOSSARY_PATH.name} 저장")

        if lang != TARGET_LANGS[-1]:
            print(f"  {LANG_DELAY:.0f}초 대기 중...", flush=True)
            time.sleep(LANG_DELAY)

    print("\n완료.")


def _save(rows, fieldnames):
    with GLOSSARY_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
