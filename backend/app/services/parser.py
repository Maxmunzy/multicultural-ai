"""HWP/PDF/text 입력 → clean_text 변환.

파이프라인 [1] 단계. 호스트 앱이 어떤 양식으로 보내든 백엔드가 텍스트로 흡수.

지원:
  - text (text/plain) → 그대로
  - PDF (application/pdf) → pdfplumber 본문 + 표 [표] 섹션
  - HWP/HWPX → LibreOffice + H2Orestart로 ODT 변환 → content.xml 직접 파싱

이미지(.jpg/.png) OCR은 별도 단계 (세종님 OCR 합류 시 추가).

ODT 경로 채택 이유 (vs 이전 HWP→PDF):
  HWP→PDF→pdfplumber는 LibreOffice가 텍스트를 두 번 그려 글자가 중복
  추출되는 문제 ("22002266학학년년도도"). ODT(zip+content.xml)는 구조화된
  단일 출력이라 중복 0. 검증: hwp5txt 28b 실패, docx 0c 실패, odt 1899c
  키워드 6/6 보존.

보안 모델:
  - 원본 filename은 .suffix 추출에만 사용. 추출된 suffix는 화이트리스트 검사
    (TEXT_EXTS / PDF_EXTS / HWP_EXTS) 통과 못 하면 ParserError로 즉시 거부.
  - 디스크 저장 경로는 tempfile.TemporaryDirectory + 고정 이름 input{suffix}.
    원본 filename은 어떤 경로/명령에도 사용되지 않음.
  - subprocess 호출은 list 인자 형태(쉘 미사용) → 명령 주입 표면 없음.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# pdfplumber는 외부 의존이라 CI/테스트 안전하게 가드.
# 운영에선 requirements.txt + Dockerfile로 보장. 부재면 첫 PDF 호출 시점에 명확한 메시지.
try:
    import pdfplumber  # type: ignore
except ImportError as error:
    print(f"[parser] pdfplumber unavailable: {error}")
    pdfplumber = None


PDF_EXTS = {".pdf"}
HWP_EXTS = {".hwp", ".hwpx"}
TEXT_EXTS = {".txt", ".md"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTS = PDF_EXTS | HWP_EXTS | TEXT_EXTS | IMG_EXTS

# LibreOffice 변환 타임아웃 (초). 큰 HWP는 ENV로 오버라이드 가능.
LIBREOFFICE_TIMEOUT_SECONDS = int(os.environ.get("PARSER_LIBREOFFICE_TIMEOUT", "300"))


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


# HWPX(H2Orestart) 추출본은 한 paragraph 안에 여러 문장이 squash 되는 경향.
# 일반화된 한국어 가통문 줄바꿈 복원 룰 (특정 문서 X, 한국어 보편 패턴):
#   (1) list enumeration "1. 대 상:...2. 장 소:..." 사이 줄바꿈
#       - HH:MM + N. → 시간 뒤 enum 보존: "14:404. 교 통" → "14:40\n4. 교 통"
#       - 비-디지트 + N. + 한글: "시네마3. 일 시" → "시네마\n3. 일 시"
#   (2) 한국어 문장 종결 어미 다음 줄바꿈
#       - "[다요까니][.?!](?=\S)" → 어미 + 문장부호 + 즉시 비공백
#       - "기원합니다.학부모님" → "기원합니다.\n학부모님"
#       - 이미 공백/줄바꿈 있는 정상 텍스트는 (?=\S) 로 no-op
#   (3) 원형 숫자(①②③) 앞 줄바꿈
#       - "유의사항① 참가" → "유의사항\n① 참가"
_TIME_THEN_ENUM = re.compile(r"(\d{1,2}:\d{2})(\d{1,2})\.\s+(?=[가-힣])")
_NONDIGIT_THEN_ENUM = re.compile(r"(?<=\S)(?<!\d)(\d{1,2})\.\s+(?=[가-힣])")
_SENTENCE_END = re.compile(r"([다요까니])([.?!])(?=\S)")
_CIRCLED_DIGIT = re.compile(r"(?<=\S)([①②③④⑤⑥⑦⑧⑨⑩⑪⑫])")

# 학년별 표 행 — "1 알림장, 클리어 화일, ..." 패턴.
# 한 행에 콤마 1개 이상 (나열) + 줄 시작 1~6 + 공백 + 한글 시작이면 학년 표로 간주.
# "{N} ..." → "{N}학년 준비물: ..." 변환해 윤정 모델·카드 빌더가
# fallback "기타"가 아닌 명확한 헤더로 카드를 만들 수 있게 한다.
_GRADE_TABLE_ROW = re.compile(
    r"^(?P<grade>[1-6])\s+(?P<items>[가-힣][^\n]*,[^\n]*)$",
    re.MULTILINE,
)


def _split_joined_enumerations(text: str) -> str:
    """HWPX 추출본의 붙은 list enumeration 사이에 줄바꿈 삽입."""
    text = _TIME_THEN_ENUM.sub(r"\1\n\2. ", text)
    text = _NONDIGIT_THEN_ENUM.sub(r"\n\1. ", text)
    return text


def _split_sentences_korean(text: str) -> str:
    """한국어 문장 종결 어미 + 원형 숫자 마커 앞에 줄바꿈."""
    text = _SENTENCE_END.sub(r"\1\2\n", text)
    text = _CIRCLED_DIGIT.sub(r"\n\1", text)
    return text


def _split_grade_table_rows(text: str) -> str:
    """학년별 표 행에 명시 헤더 부여 — fallback "기타" 카드 잘림 방지.

    학습준비물·신청서 등 학년별 표가 윤정 모델에 단일 단락으로 들어가
    한 카드에 6학년치가 뭉쳐 잘리는 문제 대응. 줄 시작 "1~6 + 공백 + 한글"
    + 콤마 나열 행에 한해 "{N}학년: ..." prefix 추가.
    """
    return _GRADE_TABLE_ROW.sub(r"\g<grade>학년: \g<items>", text)


def _pdf_to_text(pdf_path: Path) -> str:
    """본문 텍스트(표 영역 제외) + 표(행 단위 정리) 분리."""
    if pdfplumber is None:
        raise ParserError(
            "pdfplumber 미설치. backend 컨테이너 재빌드(docker compose build backend) "
            "또는 pip install pdfplumber 필요."
        )

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


def _image_to_text(img_path: Path) -> str:
    """카메라 사진(.jpg/.png) → 텍스트. Tesseract 한국어 OCR.

    전체 이미지 1차 OCR → 한국어 문자 외 노이즈 정리.
    표 영역 재처리(2차 OCR)는 별도 로직으로 확장 가능.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise ParserError(f"OCR 의존 미설치: {e}. Docker 재빌드 필요.")

    try:
        img = Image.open(img_path).convert("RGB")
    except Exception as e:
        raise ParserError(f"이미지 열기 실패: {e}")

    try:
        # psm 3: 자동 레이아웃 감지 (표·단락 혼재 가정통신문에 적합)
        text = pytesseract.image_to_string(img, lang="kor", config="--psm 3 --oem 1")
    except Exception as e:
        raise ParserError(f"Tesseract OCR 실패: {e}")

    return text


# ODT content.xml 네임스페이스
_ODT_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_ODT_TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_ODT_DRAW_NS = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"


def _hwp_to_odt(hwp_path: Path, out_dir: Path) -> Path:
    """LibreOffice headless로 HWP → ODT.

    HWP→PDF 경로의 doubled-char 문제 회피. ODT는 zip 구조라 본문/표가
    단일 트리에 한 번만 들어감. 타임아웃: PARSER_LIBREOFFICE_TIMEOUT.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless",
                "--convert-to", "odt",
                "--outdir", str(out_dir),
                str(hwp_path),
            ],
            capture_output=True, text=True,
            timeout=LIBREOFFICE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ParserError(
            f"LibreOffice 변환 타임아웃 ({LIBREOFFICE_TIMEOUT_SECONDS}초 초과). "
            "큰 HWP면 PARSER_LIBREOFFICE_TIMEOUT 환경변수로 늘릴 수 있음."
        )
    odt_path = out_dir / f"{hwp_path.stem}.odt"
    # H2Orestart가 ODT 변환 후 종료 시점에 종종 Signal 11 (cleanup 버그)을 내지만
    # 출력 파일은 정상. 파일 존재 여부를 성공 기준으로 — returncode/stderr는 참고만.
    if not odt_path.exists():
        raise ParserError(
            f"LibreOffice ODT 변환 실패 (출력 파일 없음). "
            f"returncode={result.returncode}, stderr={result.stderr.strip()[:200]}"
        )
    return odt_path


def hwp_to_pdf(hwp_path: Path, out_dir: Path) -> Path:
    """HWP/HWPX → PDF (LibreOffice + H2Orestart).

    학부모 안드 화면에 원본 풀화면 표시용. HWP는 안드 표준 viewer 없어
    PDF로 변환해서 PdfRenderer로 표시.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless",
                "--convert-to", "pdf",
                "--outdir", str(out_dir),
                str(hwp_path),
            ],
            capture_output=True, text=True,
            timeout=LIBREOFFICE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ParserError(
            f"HWP→PDF 변환 타임아웃 ({LIBREOFFICE_TIMEOUT_SECONDS}초 초과)"
        )
    pdf_path = out_dir / f"{hwp_path.stem}.pdf"
    if not pdf_path.exists():
        raise ParserError(
            f"HWP→PDF 변환 실패 (출력 없음). "
            f"returncode={result.returncode}, stderr={result.stderr.strip()[:200]}"
        )
    return pdf_path


def _odt_to_text(odt_path: Path, mark_header: bool = False) -> str:
    """ODT(zip) content.xml → 본문 + 표 영역 평면 텍스트.

    표 안 paragraph는 본문 처리에서 제외(중복 방지). 표는 셀 단위 공백 합치고
    행 단위 줄바꿈으로 평면화 — `|` 구분자 X, `[표]` 마커 X.
    윤정님 split_sentences가 헤더 키워드 lookahead("운영시간"/"운영방법"/...)로
    행 안에서 의미 단위 자연 분리하므로 셀 구분자 불필요.

    HWPX(H2Orestart) 중복 방지:
      - 중첩 text:p (outer 컨테이너 + 자식 paragraph 동시 존재) → leaf만 emit
      - 같은 본문이 여러 layout table/frame에 복제 → ≥15자 paragraph dedupe
      - 한 paragraph 안에 spans로 자체 복제 (HWPX 핵심 아티팩트) → 자체 시그니처
        재등장 지점에서 truncate
      - 시그니처(첫 60자) 가 이미 emit된 경우 → redundant로 skip

    mark_header=True: 각 표의 첫 번째 행 앞에 "[헤더] " 마킹 + 셀을 " | " 구분.
    기본값 False — 기존 호출부(parse_bytes_to_text, batch_convert.py) 변경 없음.
    """
    with zipfile.ZipFile(odt_path) as z:
        with z.open("content.xml") as f:
            tree = ET.parse(f)

    # 표/draw:frame 안 element id 모음 → 본문 처리에서 제외
    # draw:frame: 텍스트 상자/이미지 프레임 — 본문과 같은 텍스트가 중복 저장돼
    # 3배 이상 반복되는 아티팩트 원인. 표 inner 제외와 동일 방식.
    table_inner_ids: set[int] = set()
    for table in tree.iter(_ODT_TABLE_NS + "table"):
        for elem in table.iter():
            table_inner_ids.add(id(elem))
    for frame in tree.iter(_ODT_DRAW_NS + "frame"):
        for elem in frame.iter():
            table_inner_ids.add(id(elem))

    para_tags = (_ODT_TEXT_NS + "p", _ODT_TEXT_NS + "h")

    # HWPX는 outer text:p 안에 자식 text:p가 들어간 중첩 구조를 만든다.
    # tree.iter() + itertext()는 outer를 거대한 한 줄로 emit하면서 leaf도
    # 따로 emit해 같은 본문이 합쳐진 채 + 분리된 채 둘 다 들어감.
    # → 자식 paragraph 가진 outer는 건너뛰고 leaf paragraph만 emit.
    body_parts: list[str] = []
    for elem in tree.iter():
        if elem.tag not in para_tags:
            continue
        if id(elem) in table_inner_ids:
            continue
        if any(d.tag in para_tags for d in elem.iter() if d is not elem):
            continue
        text = "".join(elem.itertext()).strip()
        if text:
            body_parts.append(text)

    table_blocks: list[str] = []
    for table in tree.iter(_ODT_TABLE_NS + "table"):
        rows: list[str] = []
        for row_idx, row in enumerate(table.iter(_ODT_TABLE_NS + "table-row")):
            cells: list[str] = []
            for cell in row.iter(_ODT_TABLE_NS + "table-cell"):
                cell_text = "".join(cell.itertext()).strip()
                if cell_text:
                    cells.append(cell_text)
            if cells:
                if mark_header and row_idx == 0:
                    rows.append("[헤더] " + " | ".join(cells))
                else:
                    rows.append(" ".join(cells))
        if rows:
            table_blocks.append("\n".join(rows))

    # ≥15자 라인 dedupe + HWPX self-repeat 처리
    # HWPX(H2Orestart)는 한 paragraph 안에 spans로 본문을 2-3회 반복 복제하고,
    # 동일/유사 paragraph가 여러 layout 컨테이너에 다시 등장한다.
    # → (1) 자체 시그니처 재등장 시 truncate
    #   (2) 시그니처가 이미 emit된 경우 skip
    #   (3) 정확 일치하면 skip
    dedupe_min = 15
    sig_len = 60  # 시그니처 길이 (정상 문서엔 같은 60자가 다시 안 나타남)
    seen_long: set[str] = set()
    seen_sigs: list[str] = []  # 누적 본문 (substring 검사용)

    def truncate_self_repeat(text: str) -> str:
        if len(text) < sig_len * 2:
            return text
        sig = text[:sig_len]
        second = text.find(sig, sig_len)
        if second > 0:
            return text[:second].rstrip(" \t-")
        return text

    def dedupe_lines(lines: list[str]) -> list[str]:
        out: list[str] = []
        accumulated = "\n".join(seen_sigs)
        for line in lines:
            line = truncate_self_repeat(line)
            if not line:
                continue
            if len(line) >= dedupe_min:
                if line in seen_long:
                    continue
                # 시그니처가 이미 emit된 큰 본문에 들어있으면 redundant
                if len(line) >= sig_len and line[:sig_len] in accumulated:
                    continue
                seen_long.add(line)
                seen_sigs.append(line)
                accumulated = "\n".join(seen_sigs)
            out.append(line)
        return out

    body_parts = dedupe_lines(body_parts)
    table_blocks = [
        "\n".join(dedupe_lines(block.split("\n"))) for block in table_blocks
    ]
    table_blocks = [b for b in table_blocks if b.strip()]

    parts: list[str] = []
    if body_parts:
        parts.append("\n".join(body_parts))
    if table_blocks:
        parts.append("\n\n".join(table_blocks))
    return "\n\n".join(parts)


def parse_bytes_to_text(data: bytes, filename: str) -> str:
    """업로드된 bytes + 파일명 → 정규화된 clean_text.

    호출부(라우터)는 파일 확장자 분기 신경 안 쓰고 이 함수만 부르면 됨.
    """
    if not data:
        return ""

    suffix = Path(filename).suffix.lower()

    # 화이트리스트 검사: 알 수 없는 suffix는 일찍 거부.
    # (subprocess는 어차피 list-form이라 명령 주입은 불가능하지만 표면을 줄임)
    if suffix and suffix not in ALLOWED_EXTS:
        raise ParserError(f"지원하지 않는 파일 형식: {suffix}")

    if suffix in TEXT_EXTS or suffix == "":
        return normalize(data.decode("utf-8", errors="replace"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # 디스크 경로는 항상 tempdir 안의 고정 이름. 원본 filename은 어디에도 안 들어감.
        src_path = tmp_dir / f"input{suffix}"
        src_path.write_bytes(data)

        if suffix in PDF_EXTS:
            raw = _pdf_to_text(src_path)
            return normalize(raw)

        if suffix in HWP_EXTS:
            odt_path = _hwp_to_odt(src_path, tmp_dir)
            raw = _odt_to_text(odt_path)
            raw = _split_joined_enumerations(raw)
            raw = _split_sentences_korean(raw)
            raw = _split_grade_table_rows(raw)
            return normalize(raw)

        if suffix in IMG_EXTS:
            raw = _image_to_text(src_path)
            return normalize(raw)

    raise ParserError(f"지원하지 않는 파일 형식: {suffix}")
