"""원본 pdfplumber row + 모델 출력 sentence 둘 다 출력."""
from __future__ import annotations
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pointerdoc_infer import PointerDocInferer


def main(checkpoint: str, pdfs: list[Path], at: float = 0.3, rt: float = 0.4) -> None:
    inf = PointerDocInferer(checkpoint)
    for pdf in pdfs:
        print()
        print("=" * 80)
        print(f"PDF: {pdf.name}")
        print("=" * 80)
        rows = inf._extract_rows(pdf, 0)
        sents = inf.extract_page(pdf, 0, active_threshold=at, row_threshold=rt)

        print(f"\n--- pdfplumber 원본 행 ({len(rows)}개) ---")
        for i, r in enumerate(rows):
            text = r["text"]
            print(f"  [{i:02d}] {text}")

        print(f"\n--- PointerDoc 출력 sentence ({len(sents)}개) ---")
        for i, s in enumerate(sents):
            print(f"  [{i:02d}] {s}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("usage: show_inference.py <checkpoint> <pdf1> [<pdf2> ...]")
        sys.exit(1)
    main(args[0], [Path(p) for p in args[1:]])
