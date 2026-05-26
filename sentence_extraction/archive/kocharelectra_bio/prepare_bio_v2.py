"""BIO 학습 데이터 v2 — raw parser input + Claude label norm-matching.

v1 차이:
  v1: input = Claude cleaned_text (정제된 paragraph), label = Claude sentences (substring)
  v2: input = pymupdf raw text (paragraph 깨진 채), label = Claude sentences (norm-matching)

BIO 모델이 line break/공백 노이즈를 학습으로 무시할 수 있도록.
변형 0 원칙: Claude sentence는 norm 비교만, 위치는 raw text 안에서.

사용:
    python sentence_extraction/prepare_bio_v2.py \\
        --kd sentence_extraction/data/kd_train_pointerdoc_pymupdf.jsonl \\
        --pdf-dir sentence_extraction/data/all_pdfs \\
        --out sentence_extraction/data/bio_train_v2.jsonl
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


def build_norm_map(text: str) -> tuple[str, list[int]]:
    """text → (norm_text, norm_pos_to_raw_pos).

    norm_text = 공백/줄바꿈 제거된 text.
    norm_pos_to_raw_pos[i] = norm_text의 i번째 char가 원본 text의 어디인지.
    """
    norm_chars: list[str] = []
    norm_to_raw: list[int] = []
    for i, c in enumerate(text):
        if c.isspace():
            continue
        norm_chars.append(c)
        norm_to_raw.append(i)
    return "".join(norm_chars), norm_to_raw


def find_sentence_span(
    sentence: str,
    raw_text: str,
    norm_text: str,
    norm_to_raw: list[int],
    search_norm_pos: int,
) -> tuple[int, int, int] | None:
    """Claude sentence를 raw_text 안에서 찾기. norm-matching.

    Returns (raw_start, raw_end, next_norm_pos) — raw_text[raw_start:raw_end]가 sentence에 대응.
    next_norm_pos는 다음 cursor.
    """
    s_norm, _ = build_norm_map(sentence)
    if not s_norm:
        return None

    # 1차: cursor 이후
    found = norm_text.find(s_norm, search_norm_pos)
    if found < 0:
        # 2차: 처음부터 (안전망 — Claude sentence가 raw에 순서 안 맞을 수 있음)
        found = norm_text.find(s_norm)
        if found < 0:
            return None

    raw_start = norm_to_raw[found]
    end_norm_pos = found + len(s_norm) - 1
    if end_norm_pos >= len(norm_to_raw):
        return None
    raw_end = norm_to_raw[end_norm_pos] + 1  # exclusive
    return raw_start, raw_end, found + len(s_norm)


def make_bio_labels(raw_text: str, sentences: list[dict[str, Any]]) -> tuple[list[int], int, int]:
    """Claude sentence_list를 raw_text 안에서 norm-matching → char별 BIO 라벨."""
    norm_text, norm_to_raw = build_norm_map(raw_text)
    n = len(raw_text)
    labels = [LABEL_O] * n

    cursor_norm = 0
    matched = 0
    for s in sentences:
        s_text = s.get("text", "").strip() if isinstance(s, dict) else str(s).strip()
        if not s_text:
            continue
        span = find_sentence_span(s_text, raw_text, norm_text, norm_to_raw, cursor_norm)
        if span is None:
            continue
        raw_start, raw_end, next_norm = span
        labels[raw_start] = LABEL_B
        for i in range(raw_start + 1, raw_end):
            labels[i] = LABEL_I
        cursor_norm = next_norm
        matched += 1

    return labels, matched, len(sentences)


def extract_raw_text(pdf_path: Path) -> str:
    """pymupdf block-aware join — paragraph 깨진 raw text 그대로 (BIO가 학습으로 line break 처리)."""
    import fitz
    doc = fitz.open(pdf_path)
    text_blocks: list[str] = []
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            lines: list[str] = []
            for line in b.get("lines", []):
                t = " ".join(s["text"] for s in line.get("spans", [])).strip()
                if t:
                    lines.append(t)
            if lines:
                text_blocks.append(" ".join(lines))
    doc.close()
    return "\n".join(text_blocks)


def process_record(rec: dict[str, Any], pdf_dir: Path) -> dict[str, Any] | None:
    pdf_name = rec.get("pdf", "")
    sentences = rec.get("sentences", [])
    if not pdf_name or not sentences:
        return None

    pdf_path = pdf_dir / pdf_name
    if not pdf_path.exists():
        return None

    try:
        raw_text = extract_raw_text(pdf_path)
    except Exception as e:
        print(f"  parser FAIL {pdf_name}: {e}", file=sys.stderr)
        return None

    if not raw_text.strip():
        return None

    labels, matched, total = make_bio_labels(raw_text, sentences)
    if matched == 0:
        return None

    return {
        "pdf": pdf_name,
        "text": raw_text,
        "labels": labels,
        "n_chars": len(raw_text),
        "n_sentences": total,
        "n_matched": matched,
        "match_rate": matched / max(total, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kd", required=True, type=Path, help="Claude 라벨 jsonl (cleaned_text+sentences)")
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="N개 후 멈춤 (디버그)")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "ok": 0, "skip_no_pdf": 0, "skip_match": 0, "skip_parser": 0}
    matched_sum = 0
    total_sents_sum = 0
    char_count = 0

    with open(args.kd, encoding="utf-8") as f_in, open(args.out, "w", encoding="utf-8") as f_out:
        for line_idx, line in enumerate(f_in):
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
            pdf_name = rec.get("pdf", "")
            if not (args.pdf_dir / pdf_name).exists():
                stats["skip_no_pdf"] += 1
                continue
            sample = process_record(rec, args.pdf_dir)
            if sample is None:
                stats["skip_match"] += 1
                continue
            stats["ok"] += 1
            matched_sum += sample["n_matched"]
            total_sents_sum += sample["n_sentences"]
            char_count += sample["n_chars"]
            f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            if stats["ok"] % 100 == 0:
                print(f"  progress: {stats['ok']} OK / {stats['total']} total", file=sys.stderr)

    print(f"Total records:       {stats['total']}")
    print(f"OK:                  {stats['ok']}")
    print(f"Skipped (no PDF):    {stats['skip_no_pdf']}")
    print(f"Skipped (matching):  {stats['skip_match']}")
    print(f"Total chars:         {char_count:,}")
    print(f"Sentence matching:   {matched_sum} / {total_sents_sum} ({100*matched_sum/max(total_sents_sum,1):.1f}%)")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()
