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
    "supplies": "준비물",
}

# regex 슬롯이 todo로 이미 흡수됐는지 판단할 헤더 매핑.
# 예: todo가 "운영시간" 헤더로 이미 추출됐으면 regex times 카드는 만들지 않음.
# HWP 표 셀 헤더는 "일 시", "장 소" 처럼 공백 들어간 변형이 많아 헤더 비교는
# 공백 제거 후 normalize 해서 매치 — _normalize_header().
_TODO_HEADER_COVERS: dict[str, set[str]] = {
    # "일시" 헤더는 dates + times 둘 다 커버 — todo value 에 보통 "5월 6일 8:50 ~ 14:40" 처럼
    # 날짜+시간 같이 들어가 regex times 카드가 따로 생기면 dup.
    "times": {"운영시간", "신청시간", "시간", "일시"},
    "dates": {"운영날짜", "일시", "기간", "운영기간"},
    "urls": {"신청 URL", "신청경로", "신청방법"},
    "phones": {"연락처", "문의", "문의처"},
    "amounts": {"비용", "회비", "참가비", "수강료", "급식비"},
    "supplies": {"준비물", "준비", "지참물", "준비사항"},
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
        values_translated = []
        for e in entries:
            ko = _slot_entry_ko(e)
            if not ko:
                continue
            tr = _slot_entry_translated(e)
            # translated가 ko와 같거나 비면 (placeholder), NLLB 번역 호출
            if not tr or tr == ko:
                tr = translate_short_sentence(ko, target_lang) or ko
            values_translated.append(tr)
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
    r"|참가\s*여부를?\s*$"        # 동의서 form 끝 "참가 여부를" 잔재
    r"|^[\s,]*[✕✗×]\s*로\s+표시" # 잘린 "✕로 표시하여..."
)


def _is_short_fallback_card(card: SlotCard) -> bool:
    """헤더 추출 실패(_FALLBACK_HEADER) + 짧은 value = 본문 split 잔재.

    예: "제출 바랍니다." (8자) — 한 sentence 가 윤정 model 안에서 둘로 쪼개져
    뒷부분만 떨어진 의미 없는 카드.
    """
    return card.header_ko == _FALLBACK_HEADER and len(card.value_ko) < 15


# 첫 문장 추출 — 한국어 종결 어미 + 문장부호. 최소 20자 이상부터 매칭해
# 너무 짧은 끊어짐 방지. "다.", "요.", "까.", "?", "!" 까지.
_FIRST_KO_SENTENCE = re.compile(r"^(.{20,}?[다요까니][.!?])(?:\s|$)")
_FIRST_GENERIC_SENTENCE = re.compile(r"^(.{30,}?[.!?])(?:\s|$)")


def _smart_trim(text: str, max_len: int = 100) -> str:
    """긴 텍스트 → 첫 sentence 우선, 없으면 max_len 에서 hard cut + ...

    표 셀이나 명사 나열 카드는 종결 어미 없어 _FIRST_KO_SENTENCE 매치 실패 →
    의미 단위로 끊는 대신 hard cut 으로라도 noise 줄임.
    """
    if len(text) <= max_len:
        return text
    m = _FIRST_KO_SENTENCE.match(text)
    if m:
        return m.group(1)
    m = _FIRST_GENERIC_SENTENCE.match(text)
    if m:
        return m.group(1)
    # hard cut: 어절(공백) 경계 찾아 자연스럽게
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.7:
        cut = cut[:last_space]
    return cut.rstrip(" ,.;") + "..."


def _trim_long_fallback_card(card: SlotCard) -> SlotCard:
    """[기타] 헤더 + 매우 긴 value → 첫 sentence 또는 hard cut.

    윤정 모델이 안내문 paragraph 통째로 todo로 분류 + split_header_value 가
    헤더 못 찾아 fallback "기타" 가 된 카드는 길고 noisy.
    의미 있는 헤더 가진 카드는 절대 자르지 않음.
    """
    if card.header_ko != _FALLBACK_HEADER:
        return card
    if len(card.value_ko) <= 100:
        return card
    new_ko = _smart_trim(card.value_ko, max_len=100)
    new_easy = card.value_easy_ko
    if card.value_easy_ko and len(card.value_easy_ko) > 100:
        new_easy = _smart_trim(card.value_easy_ko, max_len=100)
    new_tr = card.value_translated
    if card.value_translated and len(card.value_translated) > 150:
        new_tr = _smart_trim(card.value_translated, max_len=150)
    return card.model_copy(update={
        "value_ko": new_ko,
        "value_easy_ko": new_easy,
        "value_translated": new_tr,
    })


# 종결 어미로 끝나는 짧은 단편 — 윤정 split 의 잔재로 직전 카드에 흡수 대상
_ORPHAN_TAIL = re.compile(r"(바랍니다|드립니다|주세요|입니다|있습니다)\.?\s*$")


def _merge_orphan_fragments(cards: list[SlotCard]) -> list[SlotCard]:
    """짧은 fallback-header 단편 카드를 직전 본문 카드 value 끝에 합쳐 흡수.

    윤정 split_sentences 가 한 문장을 둘로 쪼개 "[기타] 제출 바랍니다." 같은
    단편이 생김. 단순 필터하면 정보 손실 → 직전 본문 카드(정상 헤더)의
    value 끝에 이어 붙여 한 문장 복원.

    조건 (모두 만족):
      - header == _FALLBACK_HEADER (split 실패)
      - value < 20자
      - 종결 어미로 끝남 (바랍니다/드립니다/주세요/입니다/있습니다)
      - 직전 카드가 본문 카드 (정상 헤더)
    """
    merged: list[SlotCard] = []
    for card in cards:
        is_orphan = (
            card.header_ko == _FALLBACK_HEADER
            and len(card.value_ko) < 20
            and _ORPHAN_TAIL.search(card.value_ko)
            and merged
            and merged[-1].header_ko != _FALLBACK_HEADER
        )
        if is_orphan:
            prev = merged[-1]
            sep = " " if not prev.value_ko.endswith((" ", "\n")) else ""
            prev_strip = prev.value_ko.rstrip(" ,.;")
            merged[-1] = prev.model_copy(update={
                "value_ko": prev_strip + sep + card.value_ko,
                "value_easy_ko": (prev.value_easy_ko or "").rstrip(" ,.;") + sep + (card.value_easy_ko or ""),
                "value_translated": (prev.value_translated or "").rstrip(" ,.;") + sep + (card.value_translated or ""),
            })
        else:
            merged.append(card)
    return merged


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
    """카드 value 가 다른 카드의 substring 이면 짧은 쪽 제거 (cross-header).

    예시 — 같은 정보가 여러 슬롯에 중복:
      [일 시] 2026년 5월 6일(목) 8:50 ~ 14:40   (윤정 todo, 길다)
      [시간] 8:50 ~ 14:40                       (regex, 짧음 — substring → 제거)
      [유의사항] 참가 동의서는 4월 28일(화) 까지 담임선생님께
      [마감일] 4월 28일(화)                     (regex, 짧음 — substring → 제거)

    pdfplumber 본문/표 중복도 같이 처리 (서대구초 운영방법 케이스).
    """
    sorted_cards = sorted(cards, key=lambda c: -len(c.value_ko))
    keep: list[SlotCard] = []
    kept_norms: list[str] = []
    for card in sorted_cards:
        norm = _normalize_for_dedup(card.value_ko)
        if not norm:
            continue
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
    # orphan merge 는 cards 가 본문 순서일 때만 안전한데, 윤정 todos 가 confidence
    # 순으로 들어와 직전 카드 = 본문 직전 카드 보장 X. 잘못 붙는 사고 방지를
    # 위해 merge 대신 단순 필터로 통일 (정보 일부 손실 감수).
    cards = [c for c in cards if not _is_short_fallback_card(c)]
    cards = [_trim_long_fallback_card(c) for c in cards]
    cards = _dedup_cards(cards)
    cards.sort(key=lambda c: -c.importance)
    return cards
