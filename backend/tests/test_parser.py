"""파서 단위 테스트.

LibreOffice 호출은 mocking. PDF 추출은 pdfplumber에 의존하므로
실 PDF 한 장은 monkeypatch 없이 검증해도 됨 (가벼움).
"""
from pathlib import Path

import pytest

from app.services.parser import (
    ParserError,
    normalize,
    parse_bytes_to_text,
)


# ── normalize ─────────────────────────────────────────────────
def test_normalize_strips_null_bytes():
    assert "\x00" not in normalize("a\x00b\x00c")


def test_normalize_collapses_inline_whitespace_but_keeps_newlines():
    out = normalize("foo   bar\n\n\nbaz")
    # 한 줄 안 다중 공백은 1개로
    assert out == "foo bar\n\nbaz"


def test_normalize_preserves_paragraph_breaks():
    """줄바꿈은 보존 (윤정님 요구: '줄바꿈만 살리고')."""
    src = "안녕하세요\n학부모님께\n\n알려드립니다"
    assert normalize(src) == "안녕하세요\n학부모님께\n\n알려드립니다"


def test_normalize_empty_returns_empty():
    assert normalize("") == ""
    assert normalize("   \n\n  ") == ""


# ── parse_bytes_to_text — 평문 ────────────────────────────────
def test_parse_text_passthrough():
    raw = "통신문 본문\n\n오늘 안내드립니다".encode("utf-8")
    assert parse_bytes_to_text(raw, "notice.txt") == "통신문 본문\n\n오늘 안내드립니다"


def test_parse_no_extension_treated_as_text():
    raw = "그냥 텍스트".encode("utf-8")
    assert parse_bytes_to_text(raw, "noext") == "그냥 텍스트"


def test_parse_empty_bytes_returns_empty():
    assert parse_bytes_to_text(b"", "anything.txt") == ""


def test_parse_unsupported_extension_raises():
    with pytest.raises(ParserError):
        parse_bytes_to_text(b"x", "image.heic")


def test_parse_unknown_extension_rejected():
    """알 수 없는 suffix는 화이트리스트(ALLOWED_EXTS)에서 거부."""
    with pytest.raises(ParserError):
        parse_bytes_to_text(b"x", "../../etc/passwd.exe")
    with pytest.raises(ParserError):
        parse_bytes_to_text(b"x", "weird.bin")


def test_parse_filename_metachars_safe(monkeypatch):
    """쉘 메타문자가 들어간 .hwp 파일명도 LibreOffice 호출에 안전.

    원본 filename은 어떤 경로/명령에도 들어가지 않고 tempdir/input.hwp로만 저장.
    subprocess 호출 시 list 인자 형태라 명령 주입 표면 자체가 없음.
    """
    captured_args = {}

    def fake_run(cmd, **kwargs):
        captured_args["cmd"] = cmd
        # 메타문자 흔적이 cmd 어디에도 안 보임을 검증
        for arg in cmd:
            assert "rm" not in arg
            assert ";" not in arg
            assert "$(" not in arg
        # 가짜 ODT 만들어서 변환 성공처럼
        out_dir = Path(cmd[cmd.index("--outdir") + 1])
        (out_dir / "input.odt").write_bytes(b"PK-fake-odt")

        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr("app.services.parser.subprocess.run", fake_run)
    monkeypatch.setattr(
        "app.services.parser._odt_to_text",
        lambda p: "ok",
    )

    parse_bytes_to_text(b"HWP-data", "$(rm -rf /).hwp")
    # 명령 주입은커녕 원본 filename이 cmd에 등장조차 안 함
    assert all("$(rm" not in arg for arg in captured_args["cmd"])


def test_parse_libreoffice_timeout_raises_with_message(monkeypatch):
    """타임아웃 발생 시 ParserError + 환경변수 안내 메시지."""
    import subprocess as sp

    def boom(*args, **kwargs):
        raise sp.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr("app.services.parser.subprocess.run", boom)
    with pytest.raises(ParserError) as exc:
        parse_bytes_to_text(b"HWP", "x.hwp")
    assert "타임아웃" in str(exc.value)
    assert "PARSER_LIBREOFFICE_TIMEOUT" in str(exc.value)


# ── parse_bytes_to_text — HWP (LibreOffice 모킹) ──────────────
def test_parse_hwp_calls_libreoffice_and_odt_extractor(monkeypatch, tmp_path):
    """HWP 입력 → LibreOffice ODT 변환 호출 + content.xml 추출 호출 확인."""
    called = {}

    def fake_hwp_to_odt(hwp_path: Path, out_dir: Path) -> Path:
        called["hwp_path"] = hwp_path
        called["out_dir"] = out_dir
        fake_odt = out_dir / "fake.odt"
        fake_odt.write_bytes(b"PK-fake-odt")
        return fake_odt

    def fake_odt_to_text(odt_path: Path) -> str:
        called["odt_path"] = odt_path
        return "본문 추출 결과"

    monkeypatch.setattr("app.services.parser._hwp_to_odt", fake_hwp_to_odt)
    monkeypatch.setattr("app.services.parser._odt_to_text", fake_odt_to_text)

    out = parse_bytes_to_text(b"HWP-bytes", "안내.hwp")

    assert out == "본문 추출 결과"
    assert called["hwp_path"].suffix == ".hwp"
    assert called["odt_path"].suffix == ".odt"


def test_parse_pdf_calls_pdfplumber_only(monkeypatch):
    """PDF 입력 → LibreOffice 우회, pdfplumber만 호출."""
    called = {"hwp": False, "pdf": False}

    def fake_hwp_to_odt(*args, **kwargs):
        called["hwp"] = True
        raise AssertionError("PDF 입력에선 LibreOffice가 호출되면 안 됨")

    def fake_pdf_to_text(pdf_path: Path) -> str:
        called["pdf"] = True
        return "PDF 추출 결과"

    monkeypatch.setattr("app.services.parser._hwp_to_odt", fake_hwp_to_odt)
    monkeypatch.setattr("app.services.parser._pdf_to_text", fake_pdf_to_text)

    out = parse_bytes_to_text(b"%PDF-1.4 fake", "doc.pdf")

    assert out == "PDF 추출 결과"
    assert called["pdf"] is True
    assert called["hwp"] is False


def test_parse_libreoffice_failure_raises_parser_error(monkeypatch):
    def boom(*args, **kwargs):
        raise ParserError("LibreOffice 변환 실패")

    monkeypatch.setattr("app.services.parser._hwp_to_odt", boom)

    with pytest.raises(ParserError):
        parse_bytes_to_text(b"HWP", "x.hwp")
