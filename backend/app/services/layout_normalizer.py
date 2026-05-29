"""가정통신문 텍스트 정규화/문장 추출 — 자체 모델(kiwi + camelot) 기반.

2026-05-29: LLM API(Claude/Gemini) 전면 제거.
  - extract_sentences: PDF → kiwi(본문) + camelot(표) 결정적 추출. 변형 0, API 호출 0.
  - normalize_text: text 입력은 LLM 정제 없이 그대로 사용 (passthrough).

공개 API (notice.py가 사용):
  - extract_sentences(text, inline_data) -> (structured, status, elapsed)
  - normalize_text(text) -> (normalized, status, elapsed)
  - VISION_SUPPORTED_MIMES
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# PDF만 자체 추출(kiwi+camelot) 지원. 이미지는 text layer가 없어 미지원(스캔본은 빈 결과).
VISION_SUPPORTED_MIMES = frozenset({
    "application/pdf",
})


def _empty_structured() -> dict:
    return {"document_title": "", "cleaned_text": "", "sentence_list": []}


def _structured_from_sentences(sentences: list[str]) -> dict:
    """문장 리스트 → notice.py가 기대하는 structured dict."""
    return {
        "document_title": "",
        "cleaned_text": "\n".join(sentences),
        "sentence_list": [
            {
                "sentence_id": f"s{i:04d}",
                "text": s,
                "role_hint": "",
                "source_order": i,
                "is_action_candidate": False,
            }
            for i, s in enumerate(sentences)
        ],
    }


def extract_sentences(
    text: str = "",
    inline_data: tuple[bytes, str] | None = None,
) -> tuple[dict, str, float]:
    """PDF/text → {document_title, cleaned_text, sentence_list}.

    자체 모델 사용 (LLM API 비의존, 변형 0):
      - PDF 모드 (inline_data): kiwi(본문 종결어미 분리) + camelot(표 cell=1문장)
      - text 모드: 줄 단위 단순 분리 (LLM 정제 없음)
    """
    started = time.monotonic()

    if inline_data is not None:
        raw_bytes, mime_type = inline_data
        if not raw_bytes:
            return _empty_structured(), "skip:empty", 0.0
        if mime_type != "application/pdf":
            logger.warning(
                "extract_sentences: unsupported mime %s (PDF only)", mime_type,
            )
            return _empty_structured(), f"skip:unsupported_mime:{mime_type}", 0.0
        try:
            from app.services.kiwi_camelot_extractor import (
                extract_sentences_from_pdf_bytes,
            )
            sents = extract_sentences_from_pdf_bytes(raw_bytes)
        except Exception as e:
            logger.exception("kiwi+camelot extract failed")
            return (
                _empty_structured(),
                f"error:extract:{type(e).__name__}",
                time.monotonic() - started,
            )
        elapsed = time.monotonic() - started
        structured = _structured_from_sentences(sents)
        logger.warning(
            "extract_sentences kiwi+camelot OK: sentences=%d elapsed=%.2fs",
            len(sents), elapsed,
        )
        return structured, "ok:kiwi_camelot", elapsed

    # text 모드 — LLM 없이 줄 분리 passthrough (원문 그대로)
    if not text or not text.strip():
        return _empty_structured(), "skip:empty", 0.0
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    elapsed = time.monotonic() - started
    return _structured_from_sentences(lines), "ok:text_passthrough", elapsed


def normalize_text(text: str) -> tuple[str, str, float]:
    """text 정규화 — LLM 제거됨. 원문 그대로 반환 (passthrough).

    notice.py text-fallback 경로 호환용. status != 'ok'이라 호출부는 원본 유지.
    """
    return text or "", "skip:llm_disabled", 0.0
