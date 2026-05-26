"""LayoutXLM BIO 학습 데이터 — char별 BIO + char↔word alignment.

입력: data/layoutxlm_train.jsonl (word + bbox + group_id, page record 단위)
출력: data/layoutxlm_bio_train.jsonl
  - words, bboxes (기존 유지 — LayoutXLM input)
  - char_text: " ".join(words)
  - char_labels: char별 0=O, 1=B-SENT, 2=I-SENT
  - char_to_word: 각 char가 어느 word index에 속하는지 (LayoutXLM word representation을 char에 broadcast 시 사용)

BIO 변환 규칙:
  - word의 group_id가 이전과 다르고 ≥0 → 그 word 첫 char = B-SENT
  - 같은 group 내 char = I-SENT
  - group_id < 0 (unlabeled) → char = O
  - word 사이 공백 → 이전 word 라벨 따라 (간단화)

사용:
    python sentence_extraction/prepare_layoutxlm_bio.py \\
        --in sentence_extraction/data/layoutxlm_train.jsonl \\
        --out sentence_extraction/data/layoutxlm_bio_train.jsonl
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


def words_to_bio(words: list[str], word_labels: list[int]) -> tuple[str, list[int], list[int]]:
    """word + group_id → char_text + char_labels + char_to_word.

    word 사이는 단일 공백으로 join. 공백 char는 이전 word의 라벨 따라.
    """
    char_text_parts: list[str] = []
    char_labels: list[int] = []
    char_to_word: list[int] = []

    prev_group: int | None = None
    char_offset = 0
    for wi, (word, group) in enumerate(zip(words, word_labels)):
        if not word:
            continue

        # word 사이 공백 (첫 word 제외)
        if char_text_parts:
            char_text_parts.append(" ")
            # 공백은 이전 word 라벨 따라
            prev_label = char_labels[-1] if char_labels else LABEL_O
            # B는 한 번만 (다음 char가 I가 되도록), 공백은 I 또는 O 유지
            char_labels.append(LABEL_I if prev_label in (LABEL_B, LABEL_I) else LABEL_O)
            char_to_word.append(wi - 1 if wi > 0 else 0)

        # word 본체
        is_new_sentence = (group >= 0) and (group != prev_group)
        for ci, c in enumerate(word):
            char_text_parts.append(c)
            char_to_word.append(wi)
            if group < 0:
                char_labels.append(LABEL_O)
            elif is_new_sentence and ci == 0:
                char_labels.append(LABEL_B)
                is_new_sentence = False
            else:
                char_labels.append(LABEL_I)

        prev_group = group

    return "".join(char_text_parts), char_labels, char_to_word


def process_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    words = rec.get("words", [])
    bboxes = rec.get("bboxes", [])
    labels = rec.get("labels", [])  # word별 group_id

    if not words or len(words) != len(bboxes) or len(words) != len(labels):
        return None

    char_text, char_labels, char_to_word = words_to_bio(words, labels)
    if not char_text:
        return None

    n_b = sum(1 for l in char_labels if l == LABEL_B)
    n_i = sum(1 for l in char_labels if l == LABEL_I)
    n_o = sum(1 for l in char_labels if l == LABEL_O)

    return {
        "pdf": rec.get("pdf", ""),
        "page": rec.get("page", 0),
        "words": words,
        "bboxes": bboxes,
        "char_text": char_text,
        "char_labels": char_labels,
        "char_to_word": char_to_word,
        "n_words": len(words),
        "n_chars": len(char_text),
        "n_b_sent": n_b,
        "n_i_sent": n_i,
        "n_o": n_o,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "ok": 0, "skip": 0}
    b_sum = 0
    i_sum = 0
    o_sum = 0
    char_sum = 0

    with open(args.in_path, encoding="utf-8") as f_in, open(args.out, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            stats["total"] += 1
            if args.limit and stats["total"] > args.limit:
                break
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sample = process_record(rec)
            if sample is None:
                stats["skip"] += 1
                continue
            stats["ok"] += 1
            b_sum += sample["n_b_sent"]
            i_sum += sample["n_i_sent"]
            o_sum += sample["n_o"]
            char_sum += sample["n_chars"]
            f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            if stats["ok"] % 500 == 0:
                print(f"  progress: {stats['ok']} / {stats['total']}", file=sys.stderr)

    print(f"Total records:    {stats['total']}")
    print(f"OK:               {stats['ok']}")
    print(f"Skipped:          {stats['skip']}")
    print(f"Total chars:      {char_sum:,}")
    print(f"Label distribution:")
    total_labels = b_sum + i_sum + o_sum
    print(f"  B-SENT: {b_sum:>8,} ({100*b_sum/max(total_labels,1):.1f}%)")
    print(f"  I-SENT: {i_sum:>8,} ({100*i_sum/max(total_labels,1):.1f}%)")
    print(f"  O:      {o_sum:>8,} ({100*o_sum/max(total_labels,1):.1f}%)")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
