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


# ── parse_bytes_to_text — HWP (LibreOffice 모킹) ──────────────
def test_parse_hwp_calls_libreoffice_and_pdfplumber(monkeypatch, tmp_path):
    """HWP 입력 → LibreOffice 변환 호출 + pdfplumber 호출 확인."""
    called = {}

    def fake_hwp_to_pdf(hwp_path: Path, out_dir: Path) -> Path:
        called["hwp_path"] = hwp_path
        called["out_dir"] = out_dir
        # 실제 PDF 안 만들고 가짜 경로 반환
        fake_pdf = out_dir / "fake.pdf"
        fake_pdf.write_bytes(b"%PDF-fake")
        return fake_pdf

    def fake_pdf_to_text(pdf_path: Path) -> str:
        called["pdf_path"] = pdf_path
        return "본문 추출 결과"

    monkeypatch.setattr("app.services.parser._hwp_to_pdf", fake_hwp_to_pdf)
    monkeypatch.setattr("app.services.parser._pdf_to_text", fake_pdf_to_text)

    out = parse_bytes_to_text(b"HWP-bytes", "안내.hwp")

    assert out == "본문 추출 결과"
    assert called["hwp_path"].suffix == ".hwp"
    assert called["pdf_path"].suffix == ".pdf"


def test_parse_pdf_calls_pdfplumber_only(monkeypatch):
    """PDF 입력 → LibreOffice 우회, pdfplumber만 호출."""
    called = {"hwp": False, "pdf": False}

    def fake_hwp_to_pdf(*args, **kwargs):
        called["hwp"] = True
        raise AssertionError("PDF 입력에선 LibreOffice가 호출되면 안 됨")

    def fake_pdf_to_text(pdf_path: Path) -> str:
        called["pdf"] = True
        return "PDF 추출 결과"

    monkeypatch.setattr("app.services.parser._hwp_to_pdf", fake_hwp_to_pdf)
    monkeypatch.setattr("app.services.parser._pdf_to_text", fake_pdf_to_text)

    out = parse_bytes_to_text(b"%PDF-1.4 fake", "doc.pdf")

    assert out == "PDF 추출 결과"
    assert called["pdf"] is True
    assert called["hwp"] is False


def test_parse_libreoffice_failure_raises_parser_error(monkeypatch):
    def boom(*args, **kwargs):
        raise ParserError("LibreOffice 변환 실패")

    monkeypatch.setattr("app.services.parser._hwp_to_pdf", boom)

    with pytest.raises(ParserError):
        parse_bytes_to_text(b"HWP", "x.hwp")
