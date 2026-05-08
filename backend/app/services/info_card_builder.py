"""Build "must-check info" cards from the sentence-list contract.

Model A/B focuses on action/todo sentences.  This builder preserves hard facts
that parents still need even when they are not action sentences: application
periods, event times, targets, URLs, and contacts.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.models.schemas import SlotCard
from app.services.sentence_skeleton import (
    RoleHint,
    SentenceListDocument,
    SentenceListItem,
    normalize_header,
    parse_sentence_list_payload,
    split_header_value,
)
from app.services.translator import translate_short_sentence, translate_term


INFO_ROLE_LABELS: dict[RoleHint, str] = {
    "target": "대상",
    "application_period": "신청기간",
    "event_datetime": "운영일시",
    "application_url": "신청 URL",
    "contact": "문의",
    "result_announcement": "결과발표",
    "location": "장소",
    "fee": "비용",
    "supplies": "준비물",
}

INFO_ROLE_IMPORTANCE: dict[RoleHint, float] = {
    "application_period": 0.98,
    "event_datetime": 0.96,
    "application_url": 0.95,
    "contact": 0.94,
    "target": 0.93,
    "location": 0.88,
    "result_announcement": 0.86,
    "fee": 0.85,
    "supplies": 0.84,
}

TRANSLATION_SKIP_ROLES: set[RoleHint] = {
    "application_url",
    "contact",
}

DATE_TIME_FRAGMENT = re.compile(
    r"^\s*(?:\d{4}\.\s*)?(?:\d{1,2}\.\s*)?\d{1,2}\.\s*\([^)]+\)"
    r"(?:\s*/?\s*(?:[01]?\d|2[0-4]):[0-5]\d\s*~\s*(?:[01]?\d|2[0-4]):[0-5]\d)?\s*$"
)


def is_nllb_skip_value(text: str, role_hint: RoleHint) -> bool:
    """Return True when a value should be formatted/preserved, not NLLB-translated."""
    s = (text or "").strip()
    if not s:
        return True
    if role_hint in TRANSLATION_SKIP_ROLES:
        return True
    if DATE_TIME_FRAGMENT.fullmatch(s):
        return True
    if re.fullmatch(r"(?:[01]?\d|2[0-4]):[0-5]\d(?:\s*~\s*(?:[01]?\d|2[0-4]):[0-5]\d)?", s):
        return True
    return False


def _value_from_sentence(item: SentenceListItem) -> tuple[str, str]:
    """Return (label, value) for an info sentence."""
    label = INFO_ROLE_LABELS.get(item.role_hint, "")
    header, value = split_header_value(item.text)
    if header:
        label = INFO_ROLE_LABELS.get(item.role_hint) or normalize_header(header)
        return label, value
    return label, item.text.strip()


def _translate_info_value(value: str, role_hint: RoleHint, target_lang: str) -> str:
    if target_lang == "ko_easy":
        return value
    if is_nllb_skip_value(value, role_hint):
        return value
    return translate_short_sentence(value, target_lang) or value


def _dedup_info_cards(cards: Iterable[SlotCard]) -> list[SlotCard]:
    seen: set[tuple[str, str]] = set()
    out: list[SlotCard] = []
    for card in cards:
        key = (
            re.sub(r"\s+", "", card.header_ko),
            re.sub(r"\s+", "", card.value_ko),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def build_info_cards_from_sentence_document(
    document: SentenceListDocument,
    target_lang: str,
    *,
    translate_values: bool = False,
) -> list[SlotCard]:
    """Build must-check info cards from sentence-list role hints."""
    cards: list[SlotCard] = []
    for item in sorted(document.sentence_list, key=lambda x: x.source_order):
        if item.role_hint not in INFO_ROLE_LABELS:
            continue

        label, value = _value_from_sentence(item)
        if not value:
            continue

        cards.append(SlotCard(
            header_ko=label,
            header_translated=translate_term(label, target_lang),
            value_ko=value,
            value_easy_ko=value,
            value_translated=(
                _translate_info_value(value, item.role_hint, target_lang)
                if translate_values else value
            ),
            chip=None,
            importance=INFO_ROLE_IMPORTANCE.get(item.role_hint, 0.8),
        ))

    cards = _dedup_info_cards(cards)
    cards.sort(key=lambda c: -c.importance)
    return cards


def build_info_cards_from_sentence_payload(
    payload: str | dict,
    target_lang: str,
    *,
    translate_values: bool = False,
) -> list[SlotCard]:
    """Validate sentence-list payload and build info cards."""
    return build_info_cards_from_sentence_document(
        parse_sentence_list_payload(payload),
        target_lang,
        translate_values=translate_values,
    )
