"""v11: camelot으로 표 word를 EAV(header: value)로 재구성한 학습 데이터.

v6 record의 (pdf, page) → 원본 PDF re-process:
  - pdfplumber: 본문 word + 표 영역 검출
  - 표 영역 word 제거 → camelot으로 표 cell → "header: value" word 생성
  - merge + reading order(y, x) 정렬

라벨 부여 — 본문 word는 원본 char_labels의 sentence span text와 매칭해서 group_id 복원;
표 EAV word는 한 cell = 1 sentence (B + I) 룰.

표 검출 실패 / camelot fail → v6 record 그대로 fallback (안전).

사용:
    docker exec project-backend-1 python /app/sentence_extraction/rebuild_v11_camelot_eav.py \\
        --src /app/sentence_extraction/data/layoutxlm_bio_train_v6.jsonl \\
        --pdf-dir /app/sentence_extraction/data/all_pdfs \\
        --out /app/sentence_extraction/data/layoutxlm_bio_train_v11.jsonl
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


def words_to_bio(words: list[str], group_ids: list[int]) -> tuple[str, list[int], list[int]]:
    """word + group_id → char_text + char_labels + char_to_word (prepare_layoutxlm_bio 동일 룰)."""
    char_text_parts: list[str] = []
    char_labels: list[int] = []
    char_to_word: list[int] = []

    prev_group: int | None = None
    for wi, (word, group) in enumerate(zip(words, group_ids)):
        if not word:
            continue
        if char_text_parts:
            char_text_parts.append(" ")
            prev_label = char_labels[-1] if char_labels else LABEL_O
            char_labels.append(LABEL_I if prev_label in (LABEL_B, LABEL_I) else LABEL_O)
            char_to_word.append(wi - 1 if wi > 0 else 0)
        is_new = (group >= 0) and (group != prev_group)
        for ci, c in enumerate(word):
            char_text_parts.append(c)
            char_to_word.append(wi)
            if group < 0:
                char_labels.append(LABEL_O)
            elif is_new and ci == 0:
                char_labels.append(LABEL_B)
                is_new = False
            else:
                char_labels.append(LABEL_I)
        prev_group = group
    return "".join(char_text_parts), char_labels, char_to_word


def extract_v6_word_groups(record: dict) -> list[int]:
    """v6 record의 char_labels → word별 group_id 복원.

    같은 sentence(B 다음 I 연속) 안의 word는 같은 group_id.
    O word는 group_id = -1.
    """
    char_labels = record["char_labels"]
    char_to_word = record["char_to_word"]
    n_words = record["n_words"]

    word_group = [-1] * n_words
    current_group = -1
    for ci, lab in enumerate(char_labels):
        if ci >= len(char_to_word):
            break
        wi = char_to_word[ci]
        if lab == LABEL_B:
            current_group += 1
            if 0 <= wi < n_words:
                word_group[wi] = current_group
        elif lab == LABEL_I:
            if 0 <= wi < n_words and word_group[wi] == -1:
                word_group[wi] = current_group
    return word_group


def _in_bbox(w: dict, bx: tuple) -> bool:
    cx = (w["x0"] + w["x1"]) / 2
    cy = (w["top"] + w["bottom"]) / 2
    return bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3]


def _camelot_eav_words(pdf_path: Path, page_idx: int,
                       table_bboxes_pp: list[tuple], W: float, H: float) -> tuple[list[dict], list[int]]:
    """camelot 표 cell → EAV word + cell_id (cell마다 다른 id, 같은 cell = 한 sentence)."""
    try:
        import camelot
    except ImportError:
        return [], []

    table_areas = []
    for bbox in table_bboxes_pp:
        x1, top, x2, bottom = bbox
        y1 = H - top
        y2 = H - bottom
        table_areas.append(f"{x1},{y1},{x2},{y2}")

    try:
        tables = camelot.read_pdf(
            str(pdf_path), flavor="lattice",
            pages=str(page_idx + 1), table_areas=table_areas,
        )
    except Exception:
        return [], []

    out_words: list[dict] = []
    out_cell_ids: list[int] = []
    cell_counter = 0

    def _emit(text: str, cell) -> None:
        nonlocal cell_counter
        top = H - cell.y2
        bottom = H - cell.y1
        words_in = text.split()
        n = len(words_in)
        if n == 0:
            return
        x_step = (cell.x2 - cell.x1) / n
        for wi_, wt in enumerate(words_in):
            out_words.append({
                "text": wt,
                "x0": cell.x1 + wi_ * x_step,
                "x1": cell.x1 + (wi_ + 1) * x_step,
                "top": top, "bottom": bottom,
            })
            out_cell_ids.append(cell_counter)
        cell_counter += 1

    for tbl in tables:
        df = tbl.df
        n_rows = len(df)
        n_cols = len(df.columns)
        if n_rows < 2:
            for cidx in range(n_cols):
                cell_text = str(df.iloc[0][cidx]).strip()
                if cell_text:
                    _emit(cell_text, tbl.cells[0][cidx])
        else:
            header_row = df.iloc[0]
            for ridx in range(1, n_rows):
                for cidx in range(n_cols):
                    cell_text = str(df.iloc[ridx][cidx]).strip()
                    header_text = str(header_row[cidx]).strip()
                    if not cell_text or not header_text:
                        continue
                    _emit(f"{header_text}: {cell_text}", tbl.cells[ridx][cidx])
    return out_words, out_cell_ids


def rebuild_record(record: dict, pdf_dir: Path) -> tuple[dict, str]:
    """v6 → v11 record. Returns (new_record, status)."""
    import pdfplumber
    from sentence_extraction.parser_ensemble import dedup_overlapping_words, merge_singleton_words  # type: ignore

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

            raw_words = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            raw_words = dedup_overlapping_words(raw_words)
            raw_words = merge_singleton_words(raw_words)

            try:
                table_bboxes_pp = [tbl.bbox for tbl in page.find_tables()]
            except Exception:
                table_bboxes_pp = []
    except Exception as e:
        return record, f"error:{type(e).__name__}"

    if not table_bboxes_pp:
        return record, "no_tables"

    # v6 본문 word group 복원
    v6_word_groups = extract_v6_word_groups(record)
    v6_words = record["words"]

    # 본문 vs 표 word 분리
    body_indices = [i for i, w in enumerate(raw_words)
                    if not any(_in_bbox(w, bx) for bx in table_bboxes_pp)]
    body_words_raw = [raw_words[i] for i in body_indices]

    # 본문 word group_id 매칭 — pdfplumber 결정성 가정으로 text 일치하면 v6 word 인덱스 매칭
    # v6 words 중 표 영역 밖 word를 순서대로 추출 후 같은 길이라면 1:1 매핑
    v6_body_indices = []
    for vi, vb in enumerate(record["bboxes"]):
        cx_norm = (vb[0] + vb[2]) / 2 / 1000 * W
        cy_norm = (vb[1] + vb[3]) / 2 / 1000 * H
        is_in_table = any(
            bx[0] <= cx_norm <= bx[2] and bx[1] <= cy_norm <= bx[3]
            for bx in table_bboxes_pp
        )
        if not is_in_table:
            v6_body_indices.append(vi)

    if len(body_words_raw) != len(v6_body_indices):
        # text/length 불일치 → fallback
        return record, "body_mismatch"

    # 본문 word group_id 부여
    body_groups = [v6_word_groups[vi] for vi in v6_body_indices]

    # camelot EAV
    eav_words, eav_cell_ids = _camelot_eav_words(pdf_path, page_idx, table_bboxes_pp, W, H)
    if not eav_words:
        return record, "no_camelot"

    # cell_id → 새 group_id (본문 max + 1 부터)
    max_body_group = max((g for g in body_groups if g >= 0), default=-1)
    eav_groups = [max_body_group + 1 + cid for cid in eav_cell_ids]

    # merge + reading order
    merged = list(zip(body_words_raw, body_groups)) + list(zip(eav_words, eav_groups))
    merged.sort(key=lambda x: (round(x[0]["top"] / 5) * 5, x[0]["x0"]))

    new_words = [w["text"] for w, _ in merged]
    new_bboxes = [[
        max(0, min(1000, int(w["x0"] / W * 1000))),
        max(0, min(1000, int(w["top"] / H * 1000))),
        max(0, min(1000, int(w["x1"] / W * 1000))),
        max(0, min(1000, int(w["bottom"] / H * 1000))),
    ] for w, _ in merged]
    new_groups = [g for _, g in merged]

    char_text, char_labels, char_to_word = words_to_bio(new_words, new_groups)

    return {
        "pdf": pdf_name,
        "page": page_idx,
        "words": new_words,
        "bboxes": new_bboxes,
        "char_text": char_text,
        "char_labels": char_labels,
        "char_to_word": char_to_word,
        "n_words": len(new_words),
        "n_chars": len(char_text),
        "n_b_sent": char_labels.count(LABEL_B),
        "n_i_sent": char_labels.count(LABEL_I),
        "n_o": char_labels.count(LABEL_O),
    }, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sys.path.insert(0, "/app")

    stats: dict[str, int] = defaultdict(int)
    n_total = 0
    t0 = time.time()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.src, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            record = json.loads(line)
            n_total += 1
            if args.limit and n_total > args.limit:
                break
            new_record, status = rebuild_record(record, args.pdf_dir)
            stats[status] += 1
            fout.write(json.dumps(new_record, ensure_ascii=False) + "\n")
            if n_total % 50 == 0:
                elapsed = time.time() - t0
                print(f"  [{n_total}] elapsed={elapsed:.0f}s  {dict(stats)}", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"\n=== Done ({elapsed:.0f}s, total {n_total}) ===", file=sys.stderr)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {v:5d} ({100*v/n_total:.1f}%)", file=sys.stderr)
    print(f"Output: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
