"""갈산초 가정통신문 일괄 변환.

입력: 폴더에 섞여있는 .hwp / .hwpx / .pdf
처리: hwp/hwpx는 LibreOffice로 PDF 변환 후 pdfplumber, pdf는 바로 pdfplumber
출력: 각 파일을 동일한 이름의 .txt로 출력 디렉토리에 저장
스킵: .jpg / .png / .xlsx / .xls (이미지/스프레드시트)

본문은 표 영역 제외하고 추출, 표는 행 단위로 깨끗하게 [표] 섹션에 별도 표시.
줄바꿈은 보존 (단락 구조 유지).
"""
import re
import subprocess
import sys
import time
from pathlib import Path


SKIP_EXTS = {".jpg", ".jpeg", ".png", ".xlsx", ".xls"}
DIRECT_PDF = {".pdf"}
LIBREOFFICE_EXTS = {".hwp", ".hwpx", ".doc", ".docx"}


def normalize(text: str) -> str:
    """null 제거 + 한 줄 안 다중 공백 정리. 줄바꿈은 보존, 연속 빈 줄은 1개로 합침."""
    text = text.replace("\x00", " ")
    out_lines = []
    prev_empty = False
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            if not prev_empty:
                out_lines.append(line)
            prev_empty = True
        else:
            out_lines.append(line)
            prev_empty = False
    return "\n".join(out_lines).strip()


def pdf_to_text(pdf_path: Path) -> str:
    """본문 텍스트(표 영역 제외) + 표(행 단위 정리) 분리 추출."""
    import pdfplumber

    body_pages = []
    table_blocks = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                rows = []
                for row in tbl:
                    cells = [(c or "").replace("\n", " ").strip() for c in row]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    table_blocks.append("\n".join(rows))

            table_bboxes = [t.bbox for t in (page.find_tables() or [])]

            if table_bboxes:
                def outside_tables(obj):
                    if obj.get("object_type") != "char":
                        return True
                    cx = (obj["x0"] + obj["x1"]) / 2
                    cy = (obj["top"] + obj["bottom"]) / 2
                    for bbox in table_bboxes:
                        x0, top, x1, bottom = bbox
                        if x0 <= cx <= x1 and top <= cy <= bottom:
                            return False
                    return True
                page_view = page.filter(outside_tables)
                body = page_view.extract_text() or ""
            else:
                body = page.extract_text() or ""

            if body:
                body_pages.append(body)

    parts = []
    if body_pages:
        parts.append("\n\n".join(body_pages))
    if table_blocks:
        parts.append("[표]\n" + "\n\n".join(table_blocks))
    return "\n\n".join(parts)


def convert_via_libreoffice(src_paths: list[Path], pdf_outdir: Path) -> None:
    """LibreOffice 일괄 변환. 한 세션에서 여러 파일 처리해 시동 비용 절감."""
    pdf_outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "libreoffice", "--headless", "--convert-to", "pdf",
        "--outdir", str(pdf_outdir),
    ] + [str(p) for p in src_paths]
    subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def main():
    if len(sys.argv) < 3:
        print("usage: batch_convert.py <input_dir> <output_dir>")
        sys.exit(1)
    src_dir = Path(sys.argv[1])
    txt_dir = Path(sys.argv[2])
    pdf_tmp = txt_dir / "_pdf_intermediate"

    txt_dir.mkdir(parents=True, exist_ok=True)
    pdf_tmp.mkdir(parents=True, exist_ok=True)

    all_files = sorted(p for p in src_dir.iterdir() if p.is_file())
    skipped = [p for p in all_files if p.suffix.lower() in SKIP_EXTS]
    direct_pdfs = [p for p in all_files if p.suffix.lower() in DIRECT_PDF]
    needs_libre = [p for p in all_files if p.suffix.lower() in LIBREOFFICE_EXTS]
    other = [p for p in all_files if p.suffix.lower()
             not in SKIP_EXTS | DIRECT_PDF | LIBREOFFICE_EXTS]

    print(f"총 {len(all_files)}개")
    print(f"  스킵 (이미지/스프레드시트): {len(skipped)}")
    print(f"  PDF 직접: {len(direct_pdfs)}")
    print(f"  LibreOffice 변환 필요: {len(needs_libre)}")
    print(f"  기타 (스킵): {len(other)}")

    success = 0
    failed = []

    if needs_libre:
        print(f"\n[LibreOffice 변환 시작]")
        BATCH = 50
        for i in range(0, len(needs_libre), BATCH):
            chunk = needs_libre[i:i+BATCH]
            t0 = time.time()
            try:
                convert_via_libreoffice(chunk, pdf_tmp)
            except Exception as e:
                print(f"  배치 {i//BATCH+1} 실패: {e}")
            print(f"  배치 {i//BATCH+1}: {len(chunk)}개 ({time.time()-t0:.1f}s)")

    print(f"\n[pdfplumber 텍스트 추출 시작]")
    pdf_targets: list[tuple[Path, Path]] = []
    for src in direct_pdfs:
        pdf_targets.append((src, src))
    for src in needs_libre:
        pdf_path = pdf_tmp / f"{src.stem}.pdf"
        if pdf_path.exists():
            pdf_targets.append((pdf_path, src))
        else:
            failed.append((src.name, "LibreOffice 변환 실패"))

    for i, (pdf_path, src) in enumerate(pdf_targets, 1):
        try:
            text = normalize(pdf_to_text(pdf_path))
            if not text:
                failed.append((src.name, "빈 텍스트"))
                continue
            txt_path = txt_dir / f"{src.stem}.txt"
            txt_path.write_text(text, encoding="utf-8")
            success += 1
        except Exception as e:
            failed.append((src.name, str(e)[:80]))
        if i % 20 == 0:
            print(f"  진행: {i}/{len(pdf_targets)}")

    print(f"\n결과")
    print(f"  성공: {success}")
    print(f"  실패: {len(failed)}")
    if failed:
        print(f"\n실패 목록:")
        for name, reason in failed[:20]:
            print(f"  - {name[:60]}: {reason}")
        if len(failed) > 20:
            print(f"  ... 외 {len(failed)-20}개")


if __name__ == "__main__":
    main()
