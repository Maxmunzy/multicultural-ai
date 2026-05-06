"""슬롯 카드 빌더 — todos + regex_slots → list[SlotCard].

강사님 처방 "지저분한 줄글 X, 슬롯 위주 가공" 대응:
  한 카드 = 한 의미 단위 (운영시간 / 신청기간 / 운영방법 ...).

흐름:
  1. todos → 헤더 분해 + 분류 + 번역 + 쉬운 한국어
  2. regex 슬롯 (URL/시간/날짜/전화/금액) → 보강 카드 (todo로 못 잡은 정보)
  3. importance 내림차순 정렬

윤정님 모델이 임계값에서 컷한 정보(운영시간/신청기간 등)를 regex 슬롯이
보완 — 강사님 의견 "슬롯 위주 표시" 본질과 정합.
"""
from __future__ import annotations

import re

from app.models.schemas import Category, SlotCard, YunjeongTodo
from app.services.classifier import classify_category
from app.services.easy_korean import to_easy_korean
from app.services.header_split import split_header_value
from app.services.translator import translate_short_sentence, translate_term

# 헤더 추정 실패 시 fallback
_FALLBACK_HEADER = "기타"

# regex 슬롯별 기본 헤더 (todo에서 못 잡은 정보 보강용 카드)
# todo로 헤더가 추정된 경우엔 이 카드를 만들지 않음 (중복 방지).
_SLOT_HEADERS: dict[str, str] = {
    "dates": "일시",
    "deadlines": "마감일",
    "times": "시간",
    "urls": "신청 URL",
    "phones": "연락처",
    "amounts": "비용",
}

# regex 슬롯이 todo로 이미 흡수됐는지 판단할 헤더 매핑.
# 예: todo가 "운영시간" 헤더로 이미 추출됐으면 regex times 카드는 만들지 않음.
# HWP 표 셀 헤더는 "일 시", "장 소" 처럼 공백 들어간 변형이 많아 헤더 비교는
# 공백 제거 후 normalize 해서 매치 — _normalize_header().
_TODO_HEADER_COVERS: dict[str, set[str]] = {
    "times": {"운영시간", "신청시간", "시간"},
    "dates": {"운영날짜", "일시", "기간", "운영기간"},
    "urls": {"신청 URL", "신청경로", "신청방법"},
    "phones": {"연락처", "문의", "문의처"},
    "amounts": {"비용", "회비", "참가비", "수강료", "급식비"},
}


def _normalize_header(h: str) -> str:
    """헤더 비교용 공백 제거 — HWP "일 시" / "장 소" / "대 상" 변형 매치."""
    return re.sub(r"\s+", "", h or "")


def _build_card_from_todo(todo: YunjeongTodo, target_lang: str) -> SlotCard:
    """YunjeongTodo → SlotCard."""
    header, value = split_header_value(todo.text)
    if header is None:
        header = _FALLBACK_HEADER

    category = classify_category(value)
    chip = category.value if category != Category.other else None

    return SlotCard(
        header_ko=header,
        header_translated=translate_term(header, target_lang),
        value_ko=value,
        value_easy_ko=to_easy_korean(value),
        value_translated=translate_short_sentence(value, target_lang) or value,
        chip=chip,
        importance=todo.confidence,
    )


def _slot_entry_ko(entry: dict | str) -> str:
    if isinstance(entry, dict):
        return entry.get("ko", "")
    return entry


def _slot_entry_translated(entry: dict | str) -> str:
    if isinstance(entry, dict):
        return entry.get("translated") or entry.get("ko", "")
    return entry


def _build_cards_from_regex_slots(
    regex_slots: dict[str, list[dict]],
    target_lang: str,
    todo_headers: set[str],
) -> list[SlotCard]:
    """regex 슬롯 → 보강 SlotCard. todo 헤더가 이미 커버한 슬롯은 스킵."""
    cards: list[SlotCard] = []

    todo_headers_norm = {_normalize_header(h) for h in todo_headers}

    for slot_name, default_header in _SLOT_HEADERS.items():
        entries = regex_slots.get(slot_name, [])
        if not entries:
            continue
        # todo가 이미 이 슬롯을 커버하면 스킵 (중복 카드 방지) — 공백 normalize 후 비교
        covers_norm = {_normalize_header(h) for h in _TODO_HEADER_COVERS.get(slot_name, set())}
        if todo_headers_norm & covers_norm:
            continue

        # 슬롯당 한 카드 — 여러 값 결합
        values_ko = [_slot_entry_ko(e) for e in entries if _slot_entry_ko(e)]
        values_translated = [_slot_entry_translated(e) for e in entries if _slot_entry_ko(e)]
        # times: 2개면 시작-끝으로 보고 ~ 로 연결 (가독성). 그 외는 콤마.
        if slot_name == "times" and len(values_ko) == 2:
            value_ko = " ~ ".join(values_ko)
            value_translated = " ~ ".join(v or k for v, k in zip(values_translated, values_ko))
        else:
            value_ko = ", ".join(values_ko)
            value_translated = ", ".join(v or k for v, k in zip(values_translated, values_ko))
        if not value_ko:
            continue

        cards.append(SlotCard(
            header_ko=default_header,
            header_translated=translate_term(default_header, target_lang),
            value_ko=value_ko,
            value_easy_ko=to_easy_korean(value_ko),
            value_translated=value_translated or value_ko,
            chip=None,  # regex 슬롯은 칩 없음 — todo가 아니므로 카테고리 모호
            importance=0.7,  # todo 평균 confidence보다 살짝 낮음
        ))

    return cards


# dedup 비교용 — 표 구분자/콜론/연속 공백 정규화 (`|`/`:`/`：` 등 차이로 substring 놓치는 것 방지)
_DEDUP_NORMALIZE = re.compile(r"[\s|｜:：]+")

# form 시그널 — 학부모가 작성할 빈 칸 패턴. 본문이 아닌 동의서 form 영역의
# 텍스트가 todo로 들어왔을 때 슬롯 카드에서 제거하기 위한 필터.
# 보편 패턴 위주 — 특정 가통문 specific X.
_FORM_SIGNALS = re.compile(
    r"\(인\)"                    # 도장 칸
    r"|성\s*명\s*[:：]"           # "성명 :" 입력란 (공백 변형 허용)
    r"|[○◯][\s,]*[✕✗×]"         # 체크박스 페어 "○,✕" 또는 "○ ✕"
    r"|참가\s*여부\s+불참\s*사유"  # 표 헤더 "참가여부 불참사유"
    r"|^[\s,]*[✕✗×]\s*로\s+표시" # 잘린 "✕로 표시하여..."
)


def _normalize_for_dedup(text: str) -> str:
    """value 비교용 정규화 — 공백/구분자 차이 무시."""
    return _DEDUP_NORMALIZE.sub(" ", text).strip()


def _is_form_card(card: SlotCard) -> bool:
    """학부모가 작성할 동의서 form 영역 카드인지 검사.

    가통문은 보통 [본문 + 동의서 form] 구조. form 영역 ("학부모 성명",
    "(인)", "참가여부 불참사유" 등)은 학부모가 작성할 칸이지 분석 대상이
    아님. 윤정 모델이 form 텍스트를 todo로 잡으면 슬롯 카드가 지저분해짐.
    """
    return bool(_FORM_SIGNALS.search(card.value_ko))


def _dedup_cards(cards: list[SlotCard]) -> list[SlotCard]:
    """같은 헤더 안에서 substring 카드 제거.

    pdfplumber가 본문 + [표] 양쪽에서 같은 정보를 추출해 두 카드로 들어오는 경우
    (예: 서대구초 운영방법 156자 본문 카드 + 38자 표 영역 카드) 짧은 쪽이 긴
    쪽 안에 substring으로 들어있으면 짧은 쪽 제거. 정보 손실 0.

    헤더가 다르면 손대지 않음 — 운영방법/일시/시간/URL 등 다른 슬롯은 별개.
    """
    by_header: dict[str, list[SlotCard]] = {}
    for c in cards:
        by_header.setdefault(c.header_ko, []).append(c)

    keep: list[SlotCard] = []
    for group in by_header.values():
        # 긴 value 우선 — 짧은 게 긴 것 substring이면 제거 가능
        group.sort(key=lambda c: -len(c.value_ko))
        kept_norms: list[str] = []
        for card in group:
            norm = _normalize_for_dedup(card.value_ko)
            if any(norm in k for k in kept_norms):
                continue
            kept_norms.append(norm)
            keep.append(card)
    return keep


def build_cards(
    todos: list[YunjeongTodo],
    regex_slots: dict[str, list[dict]],
    target_lang: str,
) -> list[SlotCard]:
    """todos + regex_slots → list[SlotCard]. dedup + importance 내림차순 정렬."""
    cards = [_build_card_from_todo(t, target_lang) for t in todos]

    todo_headers = {c.header_ko for c in cards}
    cards.extend(_build_cards_from_regex_slots(regex_slots, target_lang, todo_headers))

    cards = [c for c in cards if not _is_form_card(c)]
    cards = _dedup_cards(cards)
    cards.sort(key=lambda c: -c.importance)
    return cards
