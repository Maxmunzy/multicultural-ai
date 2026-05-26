"""PDF → PNG 렌더링 — PointerDoc 학습 이미지 준비.

build_kd_data.py가 저장한 bbox는 pdfplumber point 좌표계 (origin top-left, 1pt = 1/72 inch).
PointerDoc 학습 시 bbox는 [0, 1] 정규화하므로 (page_width/height로 나눔) 렌더링 DPI와 무관.

사용:
    python sentence_extraction/render_pdfs.py \\
        --pdf-dir sentence_extraction/data/all_pdfs \\
        --out-dir sentence_extraction/data/page_images \\
        --max-side 518
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz  # pymupdf
from PIL import Image


def render_pdf(pdf_path: Path, out_dir: Path, max_side: int = 518) -> list[Path]:
    """각 페이지를 PNG로 저장. longer side를 max_side에 맞춤 (비율 유지).

    출력 파일: <out_dir>/<pdf_stem>__p<page_idx>.png
    """
    out_paths: list[Path] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"  FAIL open {pdf_path.name}: {e}", file=sys.stderr)
        return []

    for i, page in enumerate(doc):
        try:
            rect = page.rect
            page_w, page_h = float(rect.width), float(rect.height)
            longer = max(page_w, page_h)
            zoom = max_side / longer if longer > 0 else 1.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out_path = out_dir / f"{pdf_path.stem}__p{i}.png"
            img.save(out_path, optimize=True)
            out_paths.append(out_path)
        except Exception as e:
            print(f"  FAIL render {pdf_path.name} page {i}: {e}", file=sys.stderr)

    doc.close()
    return out_paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--max-side", type=int, default=518, help="더 긴 변 픽셀 (default 518)")
    ap.add_argument("--workers", type=int, default=4, help="병렬 worker (default 4)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]
    print(f"Found {len(pdfs)} PDFs")

    total_pages = 0
    failed: list[str] = []

    if args.workers <= 1:
        for pdf in pdfs:
            paths = render_pdf(pdf, args.out_dir, args.max_side)
            total_pages += len(paths)
            if not paths:
                failed.append(pdf.name)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            future_to_pdf = {
                ex.submit(render_pdf, pdf, args.out_dir, args.max_side): pdf
                for pdf in pdfs
            }
            for i, fut in enumerate(as_completed(future_to_pdf), 1):
                pdf = future_to_pdf[fut]
                paths = fut.result()
                total_pages += len(paths)
                if not paths:
                    failed.append(pdf.name)
                if i % 100 == 0:
                    print(f"  [progress] {i}/{len(pdfs)}  pages={total_pages}  fail={len(failed)}", flush=True)

    print(f"\nDone. {len(pdfs)} PDFs → {total_pages} PNG pages in {args.out_dir}")
    if failed:
        print(f"Failed: {len(failed)} PDFs")
        for n in failed[:10]:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
