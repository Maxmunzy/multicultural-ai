"""v12: 본문/표 완전 분리 학습 데이터.

한 page → 본문 record(표 word 제외) + 표 record(camelot EAV word) **별도 2개 sample**.
v11(merge)과 달리 한 sequence에 본문/표를 절대 안 섞음 → 본문 흡수/뒤섞임 0.

라벨:
  - 본문 record: v6 sentence 라벨 그대로 (word 첫 char만 B → 단어 중간 잘림 없음)
  - 표 record: cell 단위 1 sentence (cell 첫 word B, 나머지 I)

표 없는 page는 본문 record만. camelot 실패 시 표 record 생략(본문은 유지).

사용:
    docker exec project-backend-1 python /app/sentence_extraction/rebuild_v12_split.py \\
        --src /app/sentence_extraction/data/layoutxlm_bio_train_v6.jsonl \\
        --pdf-dir /app/sentence_extraction/data/all_pdfs \\
        --out /app/sentence_extraction/data/layoutxlm_bio_train_v12.jsonl
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent))

# rebuild_v11 import 시 모듈 레벨에서 stdout/stderr를 UTF-8 TextIOWrapper로 재설정함.
# v12에서 다시 감싸면 이전 wrapper가 닫혀 "I/O on closed file" → 재설정하지 않고 그대로 사용.
from rebuild_v11_camelot_eav import (  # noqa: E402
    words_to_bio, extract_v6_word_groups, _in_bbox, _camelot_eav_words,
    LABEL_B, LABEL_I, LABEL_O,
)


import re as _re

_NORM = _re.compile(r"[^가-힣A-Za-z0-9]")


def _repeat_ratio(words: list[str]) -> float:
    """인접 단어 중복 비율 — 학교 헤더/로고 표어가 표로 오인되면 높음.

    camelot이 레이아웃 중첩 영역을 중복 추출 → "참 참", "Leader Leader",
    "멋 멋", "품으로 품으로" 같은 인접 반복. 정상 표는 거의 0.
    특수문자/prefix(··, MOTHer- 등)는 비교에서 무시 (검출용, 텍스트는 안 바꿈).
    """
    norm = [_NORM.sub("", w) for w in words]
    norm = [w for w in norm if w]
    if len(norm) < 2:
        return 0.0
    rep = sum(1 for i in range(len(norm) - 1) if norm[i] == norm[i + 1])
    return rep / (len(norm) - 1)


def _single_char_ratio(words: list[str]) -> float:
    """1글자 word 비율 — 자간 표어("참 된 배 움 멋 과 감 성")가 표로 오인되면 높음."""
    norm = [_NORM.sub("", w) for w in words]
    norm = [w for w in norm if w]
    if len(norm) < 5:
        return 0.0
    return sum(1 for w in norm if len(w) == 1) / len(norm)


def _is_noise_table(words: list[str]) -> bool:
    """표 record가 헤더/로고/표어 오인 노이즈인지.

    - 인접 중복 비율 ≥ 0.12 ("참 참", "Leader Leader") 또는
    - 1글자 word 비율 ≥ 0.4 (자간 표어 "참 된 배 움")
    """
    return _repeat_ratio(words) >= 0.12 or _single_char_ratio(words) >= 0.4


MAX_CELL_CHARS = 200  # cell이 이보다 길면 표 아닌 본문 오검출


def _tbl_bbox_pp(tbl, H):
    """camelot table의 pdfplumber(top-down) 좌표 bbox."""
    cells = [c for row in tbl.cells for c in row if c is not None]
    if not cells:
        return None
    x1 = min(c.x1 for c in cells)
    x2 = max(c.x2 for c in cells)
    pp_top = H - max(c.y2 for c in cells)
    pp_bottom = H - min(c.y1 for c in cells)
    return (x1, pp_top, x2, pp_bottom)


def _camelot_eav_words_clean(pdf_path, page_idx, table_bboxes_pp, W, H):
    """table 단위 노이즈 필터 + cell EAV word.

    각 table 전체 텍스트로 노이즈(헤더/표어) 또는 본문 오검출(긴 cell) 판정 → skip.
    정상 table의 EAV word + 정상 table 영역 bbox(clean_bboxes) 반환.
    노이즈/본문오검출 table 영역은 clean_bboxes에 없으므로 본문 word로 복귀됨.
    (camelot accuracy는 헤더 박스가 100으로 나와 못 거름 — table 단위 텍스트 필터가 정확.)

    Returns: (out_words, out_cell_ids, clean_bboxes)
    """
    try:
        import camelot
    except ImportError:
        return [], [], []

    table_areas = [f"{bx[0]},{H - bx[1]},{bx[2]},{H - bx[3]}" for bx in table_bboxes_pp]
    try:
        tables = camelot.read_pdf(
            str(pdf_path), flavor="lattice",
            pages=str(page_idx + 1), table_areas=table_areas,
        )
    except Exception:
        return [], [], []

    out_words: list[dict] = []
    out_cell_ids: list[int] = []
    clean_bboxes: list[tuple] = []
    cell_counter = 0

    def _emit(text, cell):
        nonlocal cell_counter
        top, bottom = H - cell.y2, H - cell.y1
        toks = text.split()
        if not toks:
            return
        x_step = (cell.x2 - cell.x1) / len(toks)
        for wi_, wt in enumerate(toks):
            out_words.append({
                "text": wt, "x0": cell.x1 + wi_ * x_step,
                "x1": cell.x1 + (wi_ + 1) * x_step, "top": top, "bottom": bottom,
            })
            out_cell_ids.append(cell_counter)
        cell_counter += 1

    for tbl in tables:
        df = tbl.df
        n_rows, n_cols = len(df), len(df.columns)
        tbl_words = []
        max_cell_len = 0
        for r in range(n_rows):
            for c in range(n_cols):
                ct = str(df.iloc[r][c]).strip()
                tbl_words.extend(ct.split())
                max_cell_len = max(max_cell_len, len(ct))
        # 노이즈(헤더/표어) 또는 본문 오검출(긴 cell) → skip (본문으로 복귀)
        if _is_noise_table(tbl_words) or max_cell_len > MAX_CELL_CHARS:
            continue
        bbox = _tbl_bbox_pp(tbl, H)
        if bbox:
            clean_bboxes.append(bbox)
        if n_rows < 2:
            for cidx in range(n_cols):
                t = str(df.iloc[0][cidx]).strip()
                if t:
                    _emit(t, tbl.cells[0][cidx])
        else:
            header_row = df.iloc[0]
            for ridx in range(1, n_rows):
                for cidx in range(n_cols):
                    ct = str(df.iloc[ridx][cidx]).strip()
                    ht = str(header_row[cidx]).strip()
                    if not ct or not ht:
                        continue
                    _emit(f"{ht}: {ct}", tbl.cells[ridx][cidx])
    return out_words, out_cell_ids, clean_bboxes


def _make_record(pdf_name, page_idx, words, groups, bboxes_raw, W, H, kind):
    """word + group_id + raw bbox(dict) → v6 형식 record."""
    char_text, char_labels, char_to_word = words_to_bio(words, groups)
    if not char_text:
        return None
    norm_bboxes = [[
        max(0, min(1000, int(b["x0"] / W * 1000))),
        max(0, min(1000, int(b["top"] / H * 1000))),
        max(0, min(1000, int(b["x1"] / W * 1000))),
        max(0, min(1000, int(b["bottom"] / H * 1000))),
    ] for b in bboxes_raw]
    return {
        "pdf": pdf_name,
        "page": page_idx,
        "kind": kind,  # "body" | "table"
        "words": words,
        "bboxes": norm_bboxes,
        "char_text": char_text,
        "char_labels": char_labels,
        "char_to_word": char_to_word,
        "n_words": len(words),
        "n_chars": len(char_text),
        "n_b_sent": char_labels.count(LABEL_B),
        "n_i_sent": char_labels.count(LABEL_I),
        "n_o": char_labels.count(LABEL_O),
    }


def make_records(record: dict, pdf_dir: Path) -> tuple[list[dict], str]:
    """v6 record → [body_record, table_record]. 완전 분리.

    raw_words 재추출 안 함 — v6 word(라벨 보유)를 clean_bboxes로 직접 분리.
    → mismatch/fallback 없음. 본문(clean_bboxes 밖)과 표(camelot EAV)가 절대 안 겹침.
    """
    import pdfplumber

    pdf_name = record["pdf"]
    page_idx = record["page"]
    pdf_path = pdf_dir / pdf_name
    if not pdf_path.exists():
        return [], "no_pdf"

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return [], "no_page"
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return [], "no_page"
            try:
                table_bboxes_pp = [tbl.bbox for tbl in page.find_tables()]
            except Exception:
                table_bboxes_pp = []
    except Exception as e:
        return [], f"error:{type(e).__name__}"

    # --- camelot: 정상 table EAV word + 정상 table 영역(clean_bboxes) ---
    # 노이즈(헤더/표어)·본문 오검출(긴 cell) table은 clean_bboxes에서 빠짐
    # → 그 영역 v6 word는 본문 제외 대상이 아니므로 본문에 남음 (완전 복귀).
    eav_words, eav_cell_ids, clean_bboxes = [], [], []
    if table_bboxes_pp:
        eav_words, eav_cell_ids, clean_bboxes = _camelot_eav_words_clean(
            pdf_path, page_idx, table_bboxes_pp, W, H,
        )

    v6_groups = extract_v6_word_groups(record)
    v6_words = record["words"]
    v6_bboxes = record["bboxes"]
    out: list[dict] = []
    status = "ok_body_only"

    # --- 본문 record: clean_bboxes 밖 v6 word (라벨 그대로, mismatch 0) ---
    body_idx = []
    for vi, vb in enumerate(v6_bboxes):
        cx = (vb[0] + vb[2]) / 2 / 1000 * W
        cy = (vb[1] + vb[3]) / 2 / 1000 * H
        if not any(bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3] for bx in clean_bboxes):
            body_idx.append(vi)

    if body_idx:
        body_words = [v6_words[vi] for vi in body_idx]
        body_groups = [v6_groups[vi] for vi in body_idx]
        body_bboxes = [v6_bboxes[vi] for vi in body_idx]
        char_text, char_labels, char_to_word = words_to_bio(body_words, body_groups)
        if char_text:
            out.append({
                "pdf": pdf_name, "page": page_idx, "kind": "body",
                "words": body_words, "bboxes": body_bboxes,
                "char_text": char_text, "char_labels": char_labels, "char_to_word": char_to_word,
                "n_words": len(body_words), "n_chars": len(char_text),
                "n_b_sent": char_labels.count(LABEL_B),
                "n_i_sent": char_labels.count(LABEL_I),
                "n_o": char_labels.count(LABEL_O),
            })

    # --- 표 record: camelot EAV word (cell 단위 라벨) ---
    if eav_words:
        rec = _make_record(pdf_name, page_idx, [w["text"] for w in eav_words],
                           eav_cell_ids, eav_words, W, H, "table")
        if rec:
            out.append(rec)
            status = "ok_body_table"
    elif table_bboxes_pp:
        status = "no_clean_table"

    return out, status


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    stats: dict[str, int] = defaultdict(int)
    n_total = 0
    n_body = 0
    n_table = 0
    t0 = time.time()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.src, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            record = json.loads(line)
            n_total += 1
            if args.limit and n_total > args.limit:
                break
            recs, status = make_records(record, args.pdf_dir)
            stats[status] += 1
            for r in recs:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                if r.get("kind") == "table":
                    n_table += 1
                else:
                    n_body += 1
            if n_total % 50 == 0:
                print(f"  [{n_total}] elapsed={time.time()-t0:.0f}s  body={n_body} table={n_table}  {dict(stats)}", file=sys.stderr)

    print(f"\n=== Done ({time.time()-t0:.0f}s, src {n_total}) ===", file=sys.stderr)
    print(f"본문 record: {n_body}, 표 record: {n_table}, 총: {n_body + n_table}", file=sys.stderr)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:18s} {v:5d} ({100*v/n_total:.1f}%)", file=sys.stderr)
    print(f"Output: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
