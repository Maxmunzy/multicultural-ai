"""Hybrid sentence extractor wrapper for backend pipeline.

LLM 기반 extract_sentences를 자체 모델로 대체.
(LayoutXLM frozen + KoCharELECTRA + BIO head + CRF + parser dedup)

변형 0 보장 — encoder + classifier only, generation X.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# sentence_extraction module path (docker volume: ./sentence_extraction:/app/sentence_extraction)
_SENTENCE_EXTRACTION_PATH = os.environ.get(
    "SENTENCE_EXTRACTION_PATH", "/app/sentence_extraction",
)
if _SENTENCE_EXTRACTION_PATH not in sys.path:
    sys.path.insert(0, _SENTENCE_EXTRACTION_PATH)

CHECKPOINT_PATH = os.environ.get(
    "HYBRID_CHECKPOINT_PATH",
    "/app/sentence_extraction/data/hybrid_v7_crf_best.pt",
)

_INFERER = None


def _get_inferer():
    """Lazy-load HybridInferer singleton — 모델 로딩 비용 1회만."""
    global _INFERER
    if _INFERER is None:
        from hybrid_infer import HybridInferer
        logger.info("Loading HybridInferer from %s", CHECKPOINT_PATH)
        _INFERER = HybridInferer(CHECKPOINT_PATH)
        logger.info("HybridInferer loaded.")
    return _INFERER


def extract_sentences_from_pdf_bytes(raw_bytes: bytes) -> list[str]:
    """PDF bytes → sentence list via Hybrid model. 임시 파일에 저장 후 처리."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = Path(tmp.name)
    try:
        inferer = _get_inferer()
        return inferer.extract_sentences(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
