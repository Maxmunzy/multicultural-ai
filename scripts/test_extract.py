"""PDF 텍스트 추출 비교 스크립트.

같은 PDF를 pdfplumber와 PyMuPDF로 각각 추출해서 결과 비교.
디지털 PDF 가정 (텍스트 레이어 존재).
"""
import sys
from pathlib import Path


def extract_pdfplumber(path: Path) -> tuple[str, list]:
    import pdfplumber
    texts = []
    tables = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            texts.append(t)
            for tbl in page.extract_tables() or []:
                tables.append(tbl)
    return "\n--- PAGE BREAK ---\n".join(texts), tables


def extract_pymupdf(path: Path) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    out = []
    for page in doc:
        out.append(page.get_text())
    doc.close()
    return "\n--- PAGE BREAK ---\n".join(out)


def main():
    if len(sys.argv) != 2:
        print("usage: test_extract.py <pdf_path>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}")
        sys.exit(1)

    print("=" * 70)
    print(f"FILE: {path.name}  ({path.stat().st_size:,} bytes)")
    print("=" * 70)

    print("\n[1] pdfplumber.extract_text()")
    print("-" * 70)
    pp_text, pp_tables = extract_pdfplumber(path)
    print(pp_text)
    print(f"\n  → {len(pp_text)} chars, {len(pp_tables)} tables")

    if pp_tables:
        print("\n[1-b] pdfplumber.extract_tables()")
        print("-" * 70)
        for i, tbl in enumerate(pp_tables):
            print(f"  table #{i}:")
            for row in tbl:
                print(f"    {row}")

    print("\n[2] PyMuPDF (fitz) get_text()")
    print("-" * 70)
    pm_text = extract_pymupdf(path)
    print(pm_text)
    print(f"\n  → {len(pm_text)} chars")

    print("\n[3] 차이 요약")
    print("-" * 70)
    print(f"  pdfplumber  : {len(pp_text):>6} chars, tables={len(pp_tables)}")
    print(f"  PyMuPDF     : {len(pm_text):>6} chars")
    print(f"  diff        : {abs(len(pp_text) - len(pm_text))} chars")


if __name__ == "__main__":
    main()
