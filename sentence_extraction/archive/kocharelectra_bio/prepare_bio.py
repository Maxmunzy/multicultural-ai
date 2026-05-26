"""KoCharELECTRA + BIO Fine-tune 학습 데이터 변환.

기존 jsonl (Claude cleaned_text + sentence_list) → char-level BIO 라벨링.

라벨 스킴:
- B-SENT: sentence 시작 char
- I-SENT: sentence 안 char (시작 X)
- O: sentence 밖 char (공백/줄바꿈 등)

학습:
  Input:  char sequence (Claude cleaned_text)
  Output: 각 char의 BIO 라벨 (3 class)

sentence 매칭은 substring (변형 0 보장 — Claude sentence_list가 cleaned_text 안에 그대로 있음).

사용:
    python sentence_extraction/prepare_bio.py \\
        --in sentence_extraction/data/kd_train_pointerdoc_pymupdf.jsonl \\
        --out sentence_extraction/data/bio_train.jsonl
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


LABEL_O = 0
LABEL_B = 1
LABEL_I = 2

LABEL_NAMES = ["O", "B-SENT", "I-SENT"]


def make_bio_labels(cleaned_text: str, sentences: list[dict[str, Any]]) -> tuple[list[int], int, int]:
    """sentence_list를 cleaned_text 안에서 substring 매칭 → char별 BIO 라벨.

    각 sentence는 cleaned_text 안의 substring (변형 0 원칙). cursor 사용해서
    sentence 순서대로 monotonic하게 매칭 (sentence_list가 cleaned_text 순서임).

    Returns:
        (labels: O/B/I per char, matched_count, total_sentences)
    """
    n = len(cleaned_text)
    labels = [LABEL_O] * n

    cursor = 0
    matched = 0
    for s in sentences:
        s_text = s.get("text", "").strip()
        if not s_text:
            continue

        # cursor 이후로 substring 검색 — sentence_list 순서 가정
        idx = cleaned_text.find(s_text, cursor)
        if idx < 0:
            # fallback: 처음부터 검색
            idx = cleaned_text.find(s_text)
        if idx < 0:
            continue  # 매칭 실패

        labels[idx] = LABEL_B
        end = idx + len(s_text)
        for i in range(idx + 1, end):
            labels[i] = LABEL_I

        cursor = end
        matched += 1

    return labels, matched, len(sentences)


def process_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    cleaned_text = rec.get("cleaned_text", "")
    sentences = rec.get("sentences", [])
    if not cleaned_text or not sentences:
        return None

    labels, matched, total = make_bio_labels(cleaned_text, sentences)
    if matched == 0:
        return None

    return {
        "pdf": rec.get("pdf", ""),
        "text": cleaned_text,
        "labels": labels,
        "n_chars": len(cleaned_text),
        "n_sentences": total,
        "n_matched": matched,
        "match_rate": matched / max(total, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "ok": 0, "skip": 0}
    matched_sum = 0
    total_sents_sum = 0
    char_count = 0

    with open(args.in_path, encoding="utf-8") as f_in, open(args.out, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            stats["total"] += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sample = process_record(rec)
            if sample is None:
                stats["skip"] += 1
                continue
            stats["ok"] += 1
            matched_sum += sample["n_matched"]
            total_sents_sum += sample["n_sentences"]
            char_count += sample["n_chars"]
            f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"Total records:       {stats['total']}")
    print(f"OK:                  {stats['ok']}")
    print(f"Skipped:             {stats['skip']}")
    print(f"Total chars:         {char_count:,}")
    print(f"Sentence matching:")
    print(f"  matched / total:   {matched_sum} / {total_sents_sum} ({100*matched_sum/max(total_sents_sum,1):.1f}%)")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
