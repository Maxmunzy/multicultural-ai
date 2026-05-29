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


# 제목 키워드 — 가통문 제목에 흔한 어휘 (후보 중 우선 선택)
_TITLE_KEYWORDS = (
    "안내", "통신문", "모집", "신청", "공지", "가정통신", "동의", "협조", "조사",
)


def _guess_title(sentences: list[str]) -> str:
    """최상단 문장 중 제목 형태를 document_title로 추정.

    LLM 제거 후 document_title 공백 → notice.py 제목 휴리스틱이 본문 한 줄을
    잘못 잡는 regression 보완. 가통문 제목은 보통 페이지 최상단 + 종결어미/문장부호
    없는 짧은 명사구. 종결어미로 끝나는 본문 문장·너무 긴 문장은 후보 제외.
    """
    cands: list[str] = []
    for s in sentences[:3]:  # 최상단(y순 정렬) 3문장만 제목 후보
        t = s.strip()
        if not (5 <= len(t) <= 50):
            continue
        if t[-1] in ".?!" or t.endswith(("니다", "세요", "습니다", "바랍니다")):
            continue
        cands.append(t)
    for t in cands:  # "안내/통신문/모집" 등 제목 키워드 포함 후보 우선
        if any(k in t for k in _TITLE_KEYWORDS):
            return t
    return cands[0] if cands else ""


def _structured_from_sentences(sentences: list[str]) -> dict:
    """문장 리스트 → notice.py가 기대하는 structured dict."""
    return {
        "document_title": _guess_title(sentences),
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
        # status는 "ok"로 통일 — notice.py가 정확히 "ok"만 성공으로 인식(== "ok").
        # 추출 방식 세부(kiwi+camelot)는 logger에만 남김.
        logger.warning(
            "extract_sentences kiwi+camelot OK: sentences=%d elapsed=%.2fs",
            len(sents), elapsed,
        )
        return structured, "ok", elapsed

    # text 모드 — LLM 없이 줄 분리 passthrough (원문 그대로)
    if not text or not text.strip():
        return _empty_structured(), "skip:empty", 0.0
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    elapsed = time.monotonic() - started
    logger.warning("extract_sentences text-passthrough: lines=%d", len(lines))
    return _structured_from_sentences(lines), "ok", elapsed


def normalize_text(text: str) -> tuple[str, str, float]:
    """text 정규화 — LLM 제거됨. 원문 그대로 반환 (passthrough).

    notice.py text-fallback 경로 호환용. status != 'ok'이라 호출부는 원본 유지.
    """
    return text or "", "skip:llm_disabled", 0.0
