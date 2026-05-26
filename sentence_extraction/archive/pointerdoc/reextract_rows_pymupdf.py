"""기존 kd_train_pointerdoc.jsonl의 rows 필드를 pymupdf로 재추출.

라벨링은 그대로 유지 (sentences 필드). row 추출만 pymupdf get_text('dict')로
교체해서 LibreOffice 변환 PDF의 본문 quality 회복.

차이:
- 기존: pdfplumber.extract_words + y±2pt 묶기 → 컬럼 섞임, 단어 순서 깨짐
- 신규: pymupdf get_text('dict') line 단위 → 의미 단위 line, 컬럼 분리

사용:
    python sentence_extraction/reextract_rows_pymupdf.py \\
        --in sentence_extraction/data/kd_train_pointerdoc.jsonl \\
        --pdf-dir sentence_extraction/data/all_pdfs \\
        --out sentence_extraction/data/kd_train_pointerdoc_pymupdf.jsonl
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fitz  # pymupdf

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def extract_rows_pymupdf(pdf_path: Path) -> list[dict[str, Any]]:
    """pymupdf get_text('dict')로 line 단위 row 추출.

    각 line = pymupdf가 인식한 수평 텍스트 한 줄. PDF의 block/line 구조 그대로 사용.
    pdfplumber 대비 컬럼 분리·의미 단위 보존이 좋음.
    """
    rows: list[dict[str, Any]] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  FAIL open {pdf_path.name}: {e}", file=sys.stderr)
        return []

    for page_idx, page in enumerate(doc):
        page_w = float(page.rect.width)
        page_h = float(page.rect.height)
        try:
            data = page.get_text("dict")
        except Exception as e:
            print(f"  FAIL get_text {pdf_path.name} p{page_idx}: {e}", file=sys.stderr)
            continue

        for b in data.get("blocks", []):
            if b.get("type", 0) != 0:  # 0=text, 1=image
                continue
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                text = " ".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                bbox = line.get("bbox", [0, 0, 0, 0])
                rows.append({
                    "text": text,
                    "page": page_idx,
                    "page_width": page_w,
                    "page_height": page_h,
                    "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                })
    doc.close()
    return rows


def process_record(rec: dict[str, Any], pdf_dir: Path) -> tuple[dict[str, Any] | None, str]:
    """rows 필드만 pymupdf로 갱신. sentences 그대로 유지.

    sentences[].row_ids는 기존 fuzzy 결과인데, 새 row index 기준으로 다시 매핑해야
    하므로 일단 비움. prepare_pointerdoc.py --sequential 단계에서 자동 재매핑.
    """
    pdf_name = rec["pdf"]
    pdf_path = pdf_dir / pdf_name
    if not pdf_path.exists():
        return None, "missing"

    new_rows = extract_rows_pymupdf(pdf_path)
    if not new_rows:
        return None, "no_rows"

    # sentences 필드 유지하되 row_ids만 비움 (새 row 인덱스 기준 재매핑 필요)
    new_sentences = []
    for s in rec.get("sentences", []):
        new_sentences.append({
            "text": s.get("text", ""),
            "role_hint": s.get("role_hint", "etc"),
            "source_order": s.get("source_order", 0),
            "is_action_candidate": s.get("is_action_candidate", False),
            "row_ids": [],  # 재매핑 필요
        })

    return {
        "pdf": pdf_name,
        "document_title": rec.get("document_title", ""),
        "cleaned_text": rec.get("cleaned_text", ""),
        "rows": new_rows,
        "sentences": new_sentences,
        "n_rows": len(new_rows),
        "n_sentences": len(new_sentences),
        "n_matched": 0,  # 재매핑 후 prepare 단계에서 계산
        "claude_time_sec": rec.get("claude_time_sec", 0),
        "extractor": "pymupdf_line",
    }, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    records = []
    with open(args.in_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"Loaded {len(records)} records from {args.in_path.name}")

    stats = {"ok": 0, "missing": 0, "no_rows": 0}
    out_records = []

    if args.workers <= 1:
        for i, rec in enumerate(records, 1):
            new, status = process_record(rec, args.pdf_dir)
            stats[status] += 1
            if new:
                out_records.append(new)
            if i % 100 == 0:
                print(f"  [{i}/{len(records)}] {stats}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_record, rec, args.pdf_dir): rec for rec in records}
            for i, fut in enumerate(as_completed(futures), 1):
                try:
                    new, status = fut.result()
                except Exception as e:
                    print(f"  FAIL: {e}", file=sys.stderr)
                    status = "no_rows"
                    new = None
                stats[status] += 1
                if new:
                    out_records.append(new)
                if i % 100 == 0:
                    print(f"  [{i}/{len(records)}] {stats}", flush=True)

    # 입력 순서 보존을 위해 원래 PDF name 순으로 재정렬
    pdf_order = {rec["pdf"]: i for i, rec in enumerate(records)}
    out_records.sort(key=lambda r: pdf_order.get(r["pdf"], 1e9))

    with open(args.out, "w", encoding="utf-8") as f:
        for r in out_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_rows = sum(r["n_rows"] for r in out_records)
    print()
    print(f"Done. {len(out_records)} records written → {args.out}")
    print(f"  ok: {stats['ok']}, missing: {stats['missing']}, no_rows: {stats['no_rows']}")
    print(f"  total rows: {total_rows}")


if __name__ == "__main__":
    main()
