"""Build "must-check info" cards from the sentence-list contract.

Model A/B focuses on action/todo sentences.  This builder preserves hard facts
that parents still need even when they are not action sentences: application
periods, event times, targets, URLs, and contacts.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.models.schemas import Category, ChecklistItem, SlotCard
from app.services.card_builder import (
    _merge_orphan_numeric_pieces,
    _split_paren_note,
    _split_with_paren_protection,
    _stable_id,
)
from app.services.sentence_skeleton import (
    RoleHint,
    SentenceListDocument,
    SentenceListItem,
    normalize_header,
    parse_sentence_list_payload,
    split_header_value,
)
from app.services.slot_extractor import (
    _COST_SUPPORT_INFO_RE,
    _PAYMENT_ACTION_RE,
    extract_supplies,
)
from app.services.translator import translate_short_sentence, translate_term


# info_cards 중 학부모가 행동해야 할 role — 체크리스트 후보.
# fee/supplies/submit은 챙김·납부·제출 행동. 그 외(target/location/event_datetime/
# contact/url 등)는 정보 only — 체크박스 미표시.
_INFO_ACTION_ROLES: frozenset = frozenset({"fee", "supplies", "submit"})

# 콤마/슬래시 split을 적용할 role — 본질이 다중 항목 나열인 카테고리만 (준비물).
# fee/submit은 단일 액션이라 split 안 함 — card_builder._SPLIT_CHIPS와 일관.
_INFO_SPLIT_ROLES: frozenset = frozenset({"supplies"})


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
    "submit": "제출",
    # 활동/체험 내용 보존 — 현장체험학습·창의활동 통신문에서 학부모가 알아야 할
    # "무엇을 하는지" 정보를 info_card로 노출. 체크리스트 아님(행동 불필요).
    "content": "활동 내용",
    "program_title": "프로그램",
}

INFO_ROLE_IMPORTANCE: dict[RoleHint, float] = {
    "application_period": 0.98,
    "event_datetime": 0.96,
    "application_url": 0.95,
    "contact": 0.94,
    "target": 0.93,
    "content": 0.92,
    "program_title": 0.91,
    "location": 0.88,
    "result_announcement": 0.86,
    "fee": 0.85,
    "supplies": 0.84,
}

TRANSLATION_SKIP_ROLES: set[RoleHint] = {
    "application_url",
    "contact",
    "location",   # 고유명사(행사장/장소명) NLLB 오번역 방지 — ko passthrough
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
    # "★ 준비물: ..." 특수문자, "V 준비물: ..." 단일 알파벳 불릿 제거
    text = re.sub(r"^[^가-힣A-Za-z\d]+", "", (item.text or "").strip())
    text = re.sub(r"^[A-Za-z]\s+(?=[가-힣])", "", text)
    header, value = split_header_value(text)
    if header:
        label = INFO_ROLE_LABELS.get(item.role_hint) or normalize_header(header)
        return label, value
    return label, text.strip()


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


def _build_checklist_for_role(value: str, role_hint: RoleHint, target_lang: str) -> list[ChecklistItem]:
    """role_hint가 행동성이면 ChecklistItem 리스트 반환.

    role ∈ _INFO_SPLIT_ROLES (supplies): 콤마/슬래시 split → 다중 항목
    role ∈ _INFO_ACTION_ROLES \\ _INFO_SPLIT_ROLES (fee, submit): 단일 ChecklistItem
    그 외: 빈 리스트 (체크박스 미표시)
    """
    if role_hint not in _INFO_ACTION_ROLES:
        return []

    if role_hint in _INFO_SPLIT_ROLES:
        pieces = _split_with_paren_protection(value)
        pieces = _merge_orphan_numeric_pieces(pieces)
    else:
        pieces = [value.strip()] if value.strip() else []

    if not pieces:
        return []
    out: list[ChecklistItem] = []
    for piece in pieces:
        ko, note = _split_paren_note(piece)
        if not ko:
            continue
        translated = ""
        if target_lang != "ko_easy" and not is_nllb_skip_value(ko, role_hint):
            translated = translate_short_sentence(ko, target_lang) or ""
        out.append(ChecklistItem(
            item_id=_stable_id(f"{ko}|{note}"),
            ko=ko,
            note=note,
            translated=translated,
            checked=False,
        ))
    if role_hint in _INFO_SPLIT_ROLES:
        out = _expand_paren_supply_notes(out, role_hint, target_lang)
    return out


_SUPPLY_NOTE_NOISE_RE = re.compile(
    r"\s*(하나하나|이름\s*스티커|스티커.*|붙여서|넣어서|담는.*|처리용|사람만).*$"
)


def _expand_paren_supply_notes(
    items: list[ChecklistItem],
    role_hint: RoleHint,
    target_lang: str,
) -> list[ChecklistItem]:
    """준비물 항목 note 안에 콤마 나열된 개별 준비물을 추가 항목으로 확장.

    '학용품(색연필, 싸인펜, 풀, 가위, 연필 하나하나에 이름 스티커를 붙여서)'
    → [학용품, 색연필, 싸인펜, 풀, 가위, 연필]
    """
    seen = {item.ko for item in items}
    result = []
    for item in items:
        result.append(item)
        if not item.note:
            continue
        for raw in item.note.split(","):
            cleaned = _SUPPLY_NOTE_NOISE_RE.sub("", raw).strip()
            if not cleaned or len(cleaned) > 12 or cleaned in seen:
                continue
            if any(cleaned.endswith(e) for e in ("니다", "세요", "하여", "으로", "안에", "서서")):
                continue
            seen.add(cleaned)
            tr = ""
            if target_lang != "ko_easy" and not is_nllb_skip_value(cleaned, role_hint):
                tr = translate_short_sentence(cleaned, target_lang) or ""
            result.append(ChecklistItem(
                item_id=_stable_id(f"{cleaned}|"),
                ko=cleaned,
                note="",
                translated=tr,
                checked=False,
            ))
    return result


def build_info_cards_from_sentence_document(
    document: SentenceListDocument,
    target_lang: str,
    *,
    translate_values: bool = False,
) -> list[SlotCard]:
    """Build must-check info cards from sentence-list role hints."""
    cards: list[SlotCard] = []
    has_supplies_role = False

    for item in sorted(document.sentence_list, key=lambda x: x.source_order):
        if item.role_hint not in INFO_ROLE_LABELS:
            continue

        # fee 문장 중 납부 행위 없이 지원 키워드만 있는 경우 — Gemini 오분류 방지.
        # "체험학습비: 버스 1대 지원" 처럼 지원 설명이 fee로 잘못 태깅되면 비용 탭 혼입.
        if item.role_hint == "fee":
            has_payment = bool(_PAYMENT_ACTION_RE.search(item.text or ""))
            has_support = bool(_COST_SUPPORT_INFO_RE.search(item.text or ""))
            if has_support and not has_payment:
                continue  # 순수 지원 안내 → fee 탭 제외

        if item.role_hint == "supplies":
            has_supplies_role = True

        label, value = _value_from_sentence(item)
        if not value:
            continue

        cards.append(SlotCard(
            card_id=_stable_id(f"{label}|{value}"),
            header_ko=label,
            header_translated=translate_term(label, target_lang),
            value_ko=value,
            value_easy_ko=value,
            value_translated=(
                _translate_info_value(value, item.role_hint, target_lang)
                if translate_values else value
            ),
            chip=(
                Category.supplies.value if item.role_hint == "supplies"
                else Category.submission.value if item.role_hint == "submit"
                else None
            ),
            importance=INFO_ROLE_IMPORTANCE.get(item.role_hint, 0.8),
            checklist=_build_checklist_for_role(value, item.role_hint, target_lang),
        ))

    # Fallback: Gemini가 supplies role을 붙이지 않은 경우 regex로 추출.
    # 준비물은 체크리스트 핵심 항목 — role 누락 시 학부모에게 정보 미전달 방지.
    if not has_supplies_role:
        full_text = "\n".join(item.text for item in document.sentence_list if item.text)
        supply_items = extract_supplies(full_text)
        if supply_items:
            value = ", ".join(supply_items)
            cl = _build_checklist_for_role(value, "supplies", target_lang)
            if cl:
                cards.append(SlotCard(
                    card_id=_stable_id(f"준비물|{value}"),
                    header_ko="준비물",
                    header_translated=translate_term("준비물", target_lang),
                    value_ko=value,
                    value_easy_ko=value,
                    value_translated=value,
                    chip=Category.supplies.value,
                    importance=INFO_ROLE_IMPORTANCE.get("supplies", 0.84),
                    checklist=cl,
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
