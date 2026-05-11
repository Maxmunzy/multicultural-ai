"""미등록 글로사리 용어 수집기.

translate_term() 에서 glossary 매칭 실패 시 호출 → 메모리 set에 누적.
서버 재시작 시 초기화 (시연용 인메모리). 운영 시 DB/파일로 교체 예정.
"""
from __future__ import annotations

_unknown: dict[str, set[str]] = {}  # term → set of target_langs that missed


def log_unknown(term: str, target_lang: str) -> None:
    """glossary 미등록 용어 + 요청 언어 기록. 예외는 조용히 무시."""
    try:
        if term not in _unknown:
            _unknown[term] = set()
        _unknown[term].add(target_lang)
    except Exception:
        pass


def get_unknown_terms() -> list[dict]:
    """미등록 용어 리스트 반환 — 언어별 요청 횟수 포함."""
    return [
        {"term": term, "requested_langs": sorted(langs)}
        for term, langs in sorted(_unknown.items())
    ]


def clear_unknown_terms() -> int:
    """수집된 미등록 용어 초기화. 삭제된 항목 수 반환."""
    count = len(_unknown)
    _unknown.clear()
    return count
