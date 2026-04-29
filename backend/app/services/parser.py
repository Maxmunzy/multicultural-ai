"""HWP/PDF/text 입력 → clean_text 변환.

파이프라인 [1] 단계. 호스트 앱이 어떤 양식으로 보내든 백엔드가 텍스트로 흡수.

지원:
  - text (text/plain) → 그대로
  - PDF (application/pdf) → pdfplumber 본문 + 표 [표] 섹션
  - HWP/HWPX → LibreOffice + H2Orestart로 PDF 변환 → pdfplumber

이미지(.jpg/.png) OCR은 별도 단계 (세종님 OCR 합류 시 추가).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# pdfplumber는 외부 의존이라 CI/테스트 안전하게 가드.
try:
    import pdfplumber  # type: ignore
except ImportError as error:
    print(f"[parser] pdfplumber unavailable: {error}")
    pdfplumber = None


PDF_EXTS = {".pdf"}
HWP_EXTS = {".hwp", ".hwpx"}
TEXT_EXTS = {".txt", ".md"}


class ParserError(RuntimeError):
    """변환 실패 시 호출부가 잡을 수 있는 단일 예외."""


def normalize(text: str) -> str:
    """null 제거 + 한 줄 안 다중 공백만 정리. 줄바꿈 보존, 연속 빈 줄은 1개로."""
    text = text.replace("\x00", " ")
    out_lines: list[str] = []
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


def _pdf_to_text(pdf_path: Path) -> str:
    """본문 텍스트(표 영역 제외) + 표(행 단위 정리) 분리."""
    if pdfplumber is None:
        raise ParserError("pdfplumber 미설치")

    body_pages: list[str] = []
    table_blocks: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                rows: list[str] = []
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

    parts: list[str] = []
    if body_pages:
        parts.append("\n\n".join(body_pages))
    if table_blocks:
        parts.append("[표]\n" + "\n\n".join(table_blocks))
    return "\n\n".join(parts)


def _hwp_to_pdf(hwp_path: Path, out_dir: Path) -> Path:
    """LibreOffice headless로 HWP → PDF. 실패하면 ParserError."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "libreoffice", "--headless",
            "--convert-to", "pdf",
            "--outdir", str(out_dir),
            str(hwp_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    pdf_path = out_dir / f"{hwp_path.stem}.pdf"
    if result.returncode != 0 or not pdf_path.exists():
        raise ParserError(
            f"LibreOffice 변환 실패. stderr={result.stderr.strip()[:200]}"
        )
    return pdf_path


def parse_bytes_to_text(data: bytes, filename: str) -> str:
    """업로드된 bytes + 파일명 → 정규화된 clean_text.

    호출부(라우터)는 파일 확장자 분기 신경 안 쓰고 이 함수만 부르면 됨.
    """
    if not data:
        return ""

    suffix = Path(filename).suffix.lower()

    if suffix in TEXT_EXTS or suffix == "":
        return normalize(data.decode("utf-8", errors="replace"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        src_path = tmp_dir / f"input{suffix}"
        src_path.write_bytes(data)

        if suffix in PDF_EXTS:
            raw = _pdf_to_text(src_path)
            return normalize(raw)

        if suffix in HWP_EXTS:
            pdf_path = _hwp_to_pdf(src_path, tmp_dir)
            raw = _pdf_to_text(pdf_path)
            return normalize(raw)

    raise ParserError(f"지원하지 않는 파일 형식: {suffix}")
