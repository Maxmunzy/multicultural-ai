"""v6 → v8: 표 cell을 sentence로 재라벨링한 학습 데이터 생성.

v6 라벨링 일관성 문제 해결:
  - 표 영역이 PDF별/cell별로 들쭉날쭉 (어떤 cell은 O, 어떤 cell은 I, 어떤 cell은 B+I 분리)
  - v8: pdfplumber.find_tables로 표 검출 → 각 cell = 한 sentence (B + I)
  - 본문(표 밖) 라벨은 v6 그대로 유지

표 검출 실패한 PDF는 v6 라벨 그대로 (안전 fallback).

사용:
    docker compose exec -T backend python /app/sentence_extraction/rebuild_v8_table_labels.py \\
        --src /app/sentence_extraction/data/layoutxlm_bio_train_v6.jsonl \\
        --pdf-dir /app/sentence_extraction/data/all_pdfs \\
        --out /app/sentence_extraction/data/layoutxlm_bio_train_v8.jsonl
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

LABEL_O, LABEL_B, LABEL_I = 0, 1, 2


def _bbox_center_in(word_bbox, cell_bbox) -> bool:
    cx = (word_bbox[0] + word_bbox[2]) / 2
    cy = (word_bbox[1] + word_bbox[3]) / 2
    return cell_bbox[0] <= cx <= cell_bbox[2] and cell_bbox[1] <= cy <= cell_bbox[3]


def relabel_record(record: dict, pdf_dir: Path) -> tuple[dict, str]:
    """v6 record → v8 record. Returns (new_record, status).

    status: "ok" | "no_pdf" | "no_page" | "no_tables" | "error:..."
    """
    import pdfplumber

    pdf_name = record["pdf"]
    page_idx = record["page"]
    pdf_path = pdf_dir / pdf_name
    if not pdf_path.exists():
        return record, "no_pdf"

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return record, "no_page"
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return record, "no_page"
            tables = page.find_tables()
            cells_info = []
            for ti, tbl in enumerate(tables):
                for ri, row in enumerate(tbl.rows):
                    for ci, cell in enumerate(row.cells):
                        if cell is None:
                            continue
                        bx = (
                            int(cell[0] / W * 1000),
                            int(cell[1] / H * 1000),
                            int(cell[2] / W * 1000),
                            int(cell[3] / H * 1000),
                        )
                        cells_info.append({"bbox": bx, "t": ti, "r": ri, "c": ci})
    except Exception as e:
        return record, f"error:{type(e).__name__}"

    if not cells_info:
        return record, "no_tables"

    bboxes = record["bboxes"]
    n_words = record["n_words"]
    char_to_word = record["char_to_word"]
    v8_labels = list(record["char_labels"])

    # word → cell 매핑 (한 word는 한 cell만)
    word_to_cell = [-1] * n_words
    for wi, wb in enumerate(bboxes):
        for ci, info in enumerate(cells_info):
            if _bbox_center_in(wb, info["bbox"]):
                word_to_cell[wi] = ci
                break

    cell_words: dict[int, list[int]] = defaultdict(list)
    for wi, ci in enumerate(word_to_cell):
        if ci >= 0:
            cell_words[ci].append(wi)
    if not cell_words:
        return record, "no_tables"

    # cell별 char range — table → row → col 순으로 정렬
    sorted_cells = sorted(
        cell_words.keys(),
        key=lambda c: (cells_info[c]["t"], cells_info[c]["r"], cells_info[c]["c"]),
    )

    for ci in sorted_cells:
        wis = cell_words[ci]
        char_idxs = sorted(i for i, w in enumerate(char_to_word) if w in wis)
        if not char_idxs:
            continue
        first, last = char_idxs[0], char_idxs[-1]
        v8_labels[first] = LABEL_B
        for j in range(first + 1, last + 1):
            v8_labels[j] = LABEL_I

    # 통계 재계산
    new_record = dict(record)
    new_record["char_labels"] = v8_labels
    new_record["n_b_sent"] = v8_labels.count(LABEL_B)
    new_record["n_i_sent"] = v8_labels.count(LABEL_I)
    new_record["n_o"] = v8_labels.count(LABEL_O)
    return new_record, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    stats: dict[str, int] = defaultdict(int)
    n_total = 0
    n_chars_changed = 0
    t0 = time.time()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.src, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            record = json.loads(line)
            n_total += 1
            v6_labels = record["char_labels"]
            new_record, status = relabel_record(record, args.pdf_dir)
            stats[status] += 1
            if status == "ok":
                v8_labels = new_record["char_labels"]
                n_chars_changed += sum(1 for a, b in zip(v6_labels, v8_labels) if a != b)
            fout.write(json.dumps(new_record, ensure_ascii=False) + "\n")
            if n_total % 200 == 0:
                elapsed = time.time() - t0
                eta = elapsed / n_total * (stats.get("_eta_total", n_total) or n_total) - elapsed
                print(
                    f"  [{n_total}] elapsed={elapsed:.0f}s status={dict(stats)}",
                    file=sys.stderr,
                )

    elapsed = time.time() - t0
    print(f"\n=== Done ({elapsed:.0f}s) ===", file=sys.stderr)
    print(f"Total records: {n_total}", file=sys.stderr)
    print(f"Status breakdown:", file=sys.stderr)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        pct = 100 * v / n_total
        print(f"  {k:20s} {v:5d} ({pct:.1f}%)", file=sys.stderr)
    print(f"Total chars relabeled (ok records only): {n_chars_changed}", file=sys.stderr)
    print(f"Output: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
