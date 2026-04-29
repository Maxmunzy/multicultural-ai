"""HWP → PDF (LibreOffice) → 텍스트 (pdfplumber) 파이프라인.

학습 데이터 전처리용. 1회성 로컬 작업.
LibreOffice headless가 .hwp 파일을 PDF로 변환하면 그 PDF를 기존 pdfplumber 경로로 흘림.

vanilla LibreOffice는 HWP 지원이 제한적. 변환 실패 시 H2Orestart 확장 설치 필요.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def hwp_to_pdf(hwp_path: Path, out_dir: Path) -> Path:
    """LibreOffice headless로 .hwp → .pdf 변환. 변환된 PDF 경로 반환."""
    result = subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(out_dir),
            str(hwp_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice 변환 실패: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
    pdf_path = out_dir / f"{hwp_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(
            f"변환은 성공했다고 보고됐지만 PDF가 없음: {pdf_path}\n"
            f"LibreOffice가 .hwp를 인식 못 한 가능성. H2Orestart 확장 설치 검토."
        )
    return pdf_path


def pdf_to_text_and_tables(pdf_path: Path) -> tuple[str, list]:
    import pdfplumber
    texts = []
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            texts.append(t)
            for tbl in page.extract_tables() or []:
                tables.append(tbl)
    return "\n--- PAGE BREAK ---\n".join(texts), tables


def main():
    if len(sys.argv) < 2:
        print("usage: hwp_to_text.py <input.hwp> [out_dir]")
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"not found: {src}")
        sys.exit(1)

    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/2] HWP → PDF (LibreOffice)")
    pdf_path = hwp_to_pdf(src, out_dir)
    print(f"      → {pdf_path}  ({pdf_path.stat().st_size:,} bytes)")

    print(f"[2/2] PDF → 텍스트 + 표 (pdfplumber)")
    text, tables = pdf_to_text_and_tables(pdf_path)

    txt_path = out_dir / f"{src.stem}_pdfplumber.txt"
    tbl_path = out_dir / f"{src.stem}_tables.json"

    txt_path.write_text(text, encoding="utf-8")
    tbl_path.write_text(
        json.dumps(tables, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"      → {txt_path}  ({len(text)} chars)")
    print(f"      → {tbl_path}  ({len(tables)} tables)")


if __name__ == "__main__":
    main()
