"""Sentence-list contract for the Gemini/Ollama normalizer stage.

This module defines the intermediate "bone structure" passed from the parser /
normalizer stage into slot preservation and the A/B models.  Gemini may produce
this JSON, but the rest of the SchoolBridge pipeline should depend on this
deterministic contract rather than provider-specific output text.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


SectionType = Literal[
    "program",
    "application_info",
    "contact",
    "notice",
    "footer",
    "unknown",
]

RoleHint = Literal[
    "program_title",
    "target",
    "content",
    "application_period",
    "event_datetime",
    "application_url",
    "contact",
    "result_announcement",
    "location",
    "fee",
    "supplies",
    "submit",
    "etc",
]


class SentenceListItem(BaseModel):
    """One normalized sentence/field line for downstream AI modules."""

    sentence_id: str
    text: str
    section: str = ""
    section_type: SectionType = "unknown"
    role_hint: RoleHint = "etc"
    is_action_candidate: bool = False
    contains_slots: list[str] = Field(default_factory=list)
    source_order: int
    page: int | None = None
    bbox: dict[str, float] | None = None
    source: str = "normalizer"


class SentenceListDocument(BaseModel):
    """Normalizer output contract consumed by slot preservation."""

    document_title: str = ""
    sentence_list: list[SentenceListItem] = Field(default_factory=list)


HEADER_NORMALIZE_MAP: dict[str, str] = {
    "대상": "대상",
    "대 상": "대상",
    "대  상": "대상",
    "신청url": "신청 URL",
    "신청 url": "신청 URL",
    "신 청 url": "신청 URL",
    "신 청 u r l": "신청 URL",
    "신청기간": "신청기간",
    "신 청 기 간": "신청기간",
    "수강신청": "수강신청",
    "수 강 신 청": "수강신청",
    "운영일시": "운영일시",
    "운 영 일 시": "운영일시",
    "일시": "일시",
    "장소": "장소",
    "연락처": "연락처",
    "연 락 처": "연락처",
    "문의": "문의",
    "내용": "내용",
    "비용": "비용",
    "준비물": "준비물",
}

ROLE_BY_HEADER: dict[str, RoleHint] = {
    "대상": "target",
    "내용": "content",
    "신청기간": "application_period",
    "수강신청": "application_period",
    "운영일시": "event_datetime",
    "일시": "event_datetime",
    "신청 URL": "application_url",
    "연락처": "contact",
    "문의": "contact",
    "장소": "location",
    "비용": "fee",
    "준비물": "supplies",
}

SLOT_PATTERNS: dict[str, re.Pattern[str]] = {
    "date": re.compile(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}|(?:\d{1,2}\.\s*)?\d{1,2}\.\s*\d{1,2}|\d{1,2}월\s*\d{1,2}일"),
    "time": re.compile(r"\b(?:[01]?\d|2[0-4]):[0-5]\d\b"),
    "url": re.compile(r"https?://[^\s\])}>,]+|www\.[^\s\])}>,]+", re.IGNORECASE),
    "phone": re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}(?:~\d+)?\b|\b\d{3,4}-\d{4}\b"),
    "amount": re.compile(r"\d{1,3}(?:,\d{3})+\s*원|\d+\s*원"),
}


GEMINI_SENTENCE_LIST_PROMPT = """\
너는 가정통신문 문서를 후속 AI 파이프라인이 처리하기 좋게 구조화하는 parser다.
요약가나 번역가가 아니다.

목표:
문서를 예쁘게 요약하지 말고, 원문 정보를 최대한 보존한 sentence list를 생성한다.

중요 규칙:
- 날짜, 시간, 금액, URL, 전화번호는 원문 그대로 보존한다.
- 신청기간과 운영일시는 반드시 구분한다.
- 프로그램이 여러 개 있으면 section으로 분리한다.
- 원문에 없는 정보는 추측하지 않는다.
- 번역하지 않는다.
- JSON만 출력한다.

출력 스키마:
{
  "document_title": string,
  "sentence_list": [
    {
      "sentence_id": string,
      "text": string,
      "section": string,
      "section_type": "program|application_info|contact|notice|footer|unknown",
      "role_hint": "program_title|target|content|application_period|event_datetime|application_url|contact|result_announcement|location|fee|supplies|submit|etc",
      "is_action_candidate": boolean,
      "contains_slots": string[],
      "source_order": number
    }
  ]
}

문서 텍스트:
{document_text}
"""


def build_gemini_sentence_list_prompt(document_text: str) -> str:
    """Return the provider prompt for sentence-list extraction."""
    return GEMINI_SENTENCE_LIST_PROMPT.format(document_text=document_text.strip())


def normalize_header(header: str) -> str:
    """Normalize spaced Korean form headers without touching normal sentences."""
    raw = (header or "").strip().rstrip(":：")
    compact = re.sub(r"\s+", "", raw).lower()

    for key, value in HEADER_NORMALIZE_MAP.items():
        if re.sub(r"\s+", "", key).lower() == compact:
            return value
    return raw


def split_header_value(text: str) -> tuple[str | None, str]:
    """Split a field-like sentence into (normalized_header, value)."""
    s = (text or "").strip()
    if not s:
        return None, ""

    # Prefer explicit delimiters.
    m = re.match(r"^\s*([가-힣A-Za-z\s]{1,12}(?:URL|url)?)[\s:：]+(.+)$", s)
    if m:
        header = normalize_header(m.group(1))
        if header in ROLE_BY_HEADER:
            return header, m.group(2).strip()

    # Handle compact headers with no colon: "운영일시 2026. 5. 9..."
    for header in sorted(ROLE_BY_HEADER, key=len, reverse=True):
        if s.startswith(header):
            value = s[len(header):].strip(" :：")
            if value:
                return header, value
    return None, s


def detect_contains_slots(text: str) -> list[str]:
    """Detect hard-fact slot kinds present in text."""
    found: list[str] = []
    header, _ = split_header_value(text)
    if header == "대상":
        found.append("target")
    if header == "장소":
        found.append("location")
    if header == "준비물":
        found.append("supplies")
    for slot, pattern in SLOT_PATTERNS.items():
        if pattern.search(text or ""):
            found.append(slot)
    return list(dict.fromkeys(found))


def infer_role_hint(text: str) -> RoleHint:
    """Best-effort role hint for fallback/local sentence-list adapters."""
    header, value = split_header_value(text)
    if header and header in ROLE_BY_HEADER:
        return ROLE_BY_HEADER[header]

    s = (text or "").strip()
    if "신청" in s and detect_contains_slots(s):
        return "application_period"
    if any(k in s for k in ("운영일시", "일시", "체험일", "행사일")) and detect_contains_slots(s):
        return "event_datetime"
    if "발표" in s or "알림" in s:
        return "result_announcement"
    if SLOT_PATTERNS["url"].search(s):
        return "application_url"
    if SLOT_PATTERNS["phone"].search(s):
        return "contact"
    return "etc"


def is_action_candidate(text: str, role_hint: RoleHint) -> bool:
    """Mark lines likely useful for model A's todo extraction."""
    if role_hint in {"application_period", "application_url", "submit", "fee", "supplies"}:
        return True
    return any(k in (text or "") for k in (
        "신청", "제출", "납부", "입금", "준비", "지참", "참석", "참여", "확인",
    ))


def parse_sentence_list_payload(payload: str | dict[str, Any]) -> SentenceListDocument:
    """Validate Gemini/Ollama sentence-list JSON and return a typed document."""
    data = json.loads(payload) if isinstance(payload, str) else payload
    return SentenceListDocument.model_validate(data)


def raw_text_to_sentence_list(raw_text: str) -> SentenceListDocument:
    """Local fallback adapter until Gemini sentence-list output is wired.

    This is intentionally simple: it preserves raw order and only infers headers,
    role hints, and hard-fact slots.  The Gemini path should produce richer
    section names, but downstream code can use the same contract.
    """
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    items: list[SentenceListItem] = []
    title = lines[0] if lines else ""

    for idx, line in enumerate(lines, start=1):
        role = infer_role_hint(line)
        items.append(SentenceListItem(
            sentence_id=f"s{idx:03d}",
            text=line,
            section="",
            section_type="unknown",
            role_hint=role,
            is_action_candidate=is_action_candidate(line, role),
            contains_slots=detect_contains_slots(line),
            source_order=idx,
            source="raw_text_adapter",
        ))

    return SentenceListDocument(document_title=title, sentence_list=items)
