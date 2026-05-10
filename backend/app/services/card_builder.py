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

import hashlib
import re

from app.models.schemas import Category, ChecklistItem, SlotCard, YunjeongTodo
from app.services.classifier import classify_category
from app.services.easy_korean import to_easy_korean
from app.services.header_split import split_header_value
from app.services.translator import (
    translate_short_sentence, translate_short_sentence_batch, translate_term,
)


# 체크리스트 후보 chip — 학부모가 챙김/제출/납부/안전수칙 이행하는 카테고리.
# 정보성(일정) + None(분류 불가)은 체크박스 미표시.
_ACTION_CHIPS: frozenset[str] = frozenset({
    Category.supplies.value,    # "준비물"
    Category.submission.value,  # "제출"
    Category.cost.value,        # "비용"
    Category.health.value,      # "건강·안전"
})

# 조사 — 준비물 dedup 시 "물통은 ..." 에서 "물통" prefix 판별용
_KO_PARTICLES: frozenset[str] = frozenset("은는이가을를의와과도")


def _stable_id(text: str) -> str:
    """문자열 stable hash 12자 — 카드/항목 식별자.

    같은 통신문 재분석에도 동일 ID — 카드 순서 변경/Claude 비결정성에 강건.
    sha1 12자 충돌 확률 무시 가능 (한 분석 안 카드/항목 < 100).
    """
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]

# 콤마/슬래시 split을 적용할 chip — 본질이 다중 항목 나열인 카테고리만.
# 제출/비용/건강·안전은 보통 단일 액션이라 split 안 함 ("2,3,5,6학년 학생은..." 같은
# 학년 나열을 의미 없는 단일 숫자 체크박스로 깨먹는 사고 방지). 세종님 우려 반영.
_SPLIT_CHIPS: frozenset[str] = frozenset({
    Category.supplies.value,    # "준비물" — 알림장, 색종이, 연필 ...
    # Category.cost 제외 — "23,000원" 천단위 쉼표에서 split되어 "23"/"000원"으로 깨짐
})


def _split_with_paren_protection(text: str) -> list[str]:
    """콤마/슬래시 split — 괄호 안 콤마는 보존.

    예: "필통 (깎은 연필 3자루, 지우개, 딱풀), 가위, 풀"
        → ["필통 (깎은 연필 3자루, 지우개, 딱풀)", "가위", "풀"]
    """
    if not text:
        return []
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch in ",/" and depth == 0:
            piece = "".join(cur).strip()
            if piece:
                parts.append(piece)
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


# 숫자만으로 된 짧은 토큰 — split 결과로 떨어지면 다음 항목과 머지 (학년 나열 깨짐 방지)
_NUMERIC_ONLY = re.compile(r"^\s*\d{1,3}\s*$")


def _merge_orphan_numeric_pieces(pieces: list[str]) -> list[str]:
    """split 후 숫자만 토큰을 다음 항목 앞에 머지 — "2,3,5,6학년" 깨짐 방지.

    예: ["2", "3", "5", "6학년 학생은..."] → ["2,3,5,6학년 학생은..."]
    """
    out: list[str] = []
    pending: list[str] = []
    for p in pieces:
        if _NUMERIC_ONLY.match(p):
            pending.append(p.strip())
        else:
            if pending:
                p = ",".join(pending) + "," + p
                pending = []
            out.append(p)
    if pending:
        if out:
            out[-1] = out[-1] + "," + ",".join(pending)
        else:
            out = [",".join(pending)]
    return out


# 끝부분 괄호 부연 — "샤프식 색연필 12색 (연필식 색연필 불가)" → ("샤프식 색연필 12색", "연필식 색연필 불가")
_TRAILING_PAREN = re.compile(r"^(.+?)\s*[\(（]\s*([^)）]+?)\s*[\)）]\s*$")


def _split_paren_note(item_text: str) -> tuple[str, str]:
    """항목 끝 괄호 부연을 (ko, note)로 분리. 괄호 없으면 (item_text, '')."""
    s = item_text.strip()
    m = _TRAILING_PAREN.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, ""


_SUPPLY_NOTE_NOISE_RE = re.compile(
    r"\s*(하나하나|이름\s*스티커|스티커.*|붙여서|넣어서|담는.*|처리용|사람만).*$"
)


def _expand_paren_supply_notes_card(
    items: list[ChecklistItem],
    target_lang: str,
) -> list[ChecklistItem]:
    """준비물 note 안 콤마 나열 항목을 추가 ChecklistItem으로 확장 (card_builder 경로용).

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
            if target_lang != "ko_easy":
                tr = translate_short_sentence(cleaned, target_lang) or ""
            result.append(ChecklistItem(
                item_id=_stable_id(f"{cleaned}|"),
                ko=cleaned,
                note=None,
                translated=tr,
                checked=False,
            ))
    return result


def _build_checklist_from_card(card: SlotCard, target_lang: str) -> list[ChecklistItem]:
    """경이 카테고리(chip) 기반 체크리스트 분리.

    chip ∈ _ACTION_CHIPS면 체크리스트 후보:
      - chip ∈ _SPLIT_CHIPS (준비물): 콤마/슬래시 split → 다중 항목
      - 그 외 (제출/비용/건강·안전): 단일 ChecklistItem (sentence 통째)

    정보성(일정) + None은 빈 리스트 → 체크박스 미표시.
    """
    if card.chip not in _ACTION_CHIPS:
        return []

    if card.chip in _SPLIT_CHIPS:
        pieces = _split_with_paren_protection(card.value_ko)
        pieces = _merge_orphan_numeric_pieces(pieces)
    else:
        # 제출/비용/건강·안전은 단일 액션 — 콤마 split 시 사고 발생 (학년 나열 등)
        pieces = [card.value_ko.strip()] if card.value_ko.strip() else []

    if not pieces:
        return []
    out: list[ChecklistItem] = []
    for piece in pieces:
        ko, note = _split_paren_note(piece)
        if not ko:
            continue
        translated = ""
        if target_lang != "ko_easy":
            translated = translate_short_sentence(ko, target_lang) or ""
        out.append(ChecklistItem(
            item_id=_stable_id(f"{ko}|{note}"),
            ko=ko,
            note=note,
            translated=translated,
            checked=False,
        ))
    if card.chip in _SPLIT_CHIPS:
        out = _expand_paren_supply_notes_card(out, target_lang)
    return out

# 헤더 추정 실패 시 fallback
_FALLBACK_HEADER = "기타"
_FALLBACK_MAX_CARDS = 3
_FALLBACK_MAX_KO_LEN = 80
_FALLBACK_MAX_TRANSLATED_LEN = 120

# 정상 헤더(명시) 카드도 value 과도하게 길면 trim — 신청방법 등이 전체 안내문 흡수하는 문제 방지
# translated는 translate_short_sentence 내부 MAX_TRANSLATE_CHARS=100으로 이미 제한됨
# 250 (이전 150)으로 상향 — Claude가 학년 prefix를 sentence 끝 괄호 ("(1학년 공용)")로
# 보존하는데 긴 학년별 준비물 sentence가 150자에서 잘려 끝의 학년 정보 잃는 문제 방지.
_NAMED_MAX_KO_LEN = 250

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
    "cost_support": "비용",
    "cost_support_info": "지원 안내",
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
    "cost_support": {"비용", "회비", "참가비", "수강료", "급식비"},
    "cost_support_info": {"지원", "지원사업", "지원안내"},
}


def _normalize_header(h: str) -> str:
    """헤더 비교용 공백 제거 — HWP "일 시" / "장 소" / "대 상" 변형 매치."""
    return re.sub(r"\s+", "", h or "")


def _build_card_from_todo(todo: YunjeongTodo, target_lang: str) -> SlotCard:
    """YunjeongTodo → SlotCard. value_translated 는 build_cards 마지막에 batch 번역."""
    header, value = split_header_value(todo.text)
    if header is None:
        header = _FALLBACK_HEADER
    elif len(value) > _NAMED_MAX_KO_LEN:
        # 명시 헤더 카드도 value가 너무 길면 trim (신청방법 등이 전체 안내문 흡수 방지)
        # _smart_trim은 이 함수보다 아래에 정의되지만 호출 시점엔 이미 존재
        value = _smart_trim(value, max_len=_NAMED_MAX_KO_LEN)

    category = classify_category(value)
    chip = category.value if category != Category.other else None

    return SlotCard(
        card_id=_stable_id(f"{header}|{value}"),
        header_ko=header,
        header_translated="" if header == _FALLBACK_HEADER else translate_term(header, target_lang),
        value_ko=value,
        value_easy_ko=to_easy_korean(value),
        value_translated="",  # build_cards 끝에서 batch 번역
        chip=chip,
        importance=todo.confidence,
        due_date=todo.due_date,  # 통합 체크리스트 마감일 정렬용
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
    """regex 슬롯 → 보강 SlotCard. todo 헤더가 이미 커버한 슬롯은 스킵.

    value_translated 는 urls/phones만 ko 그대로 사용(NLLB 거치면 placeholder
    잔재로 "Không, không" 같이 깨짐). 그 외 슬롯은 빈 문자열로 두고 build_cards
    끝의 batch 번역 단계가 채움.
    """
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
        # times: 상세 일정표에서 다수 추출될 수 있으므로 2개로 제한 (시작~종료만 노출).
        # 3개 이상이면 첫 두 개 (안내문에서 이벤트 시작~종료가 먼저 등장)
        if slot_name == "times":
            if len(values_ko) > 2:
                values_ko = values_ko[:2]
            value_ko = " ~ ".join(values_ko) if len(values_ko) == 2 else (values_ko[0] if values_ko else "")
        else:
            value_ko = ", ".join(values_ko)
        if not value_ko:
            continue

        # urls/phones/places는 NLLB 우회 — ko 그대로.
        # places는 "해조류박람회 및 빙그레 시네마" 같은 고유명사라 NLLB 오번역 심각.
        value_translated = value_ko if slot_name in ("urls", "phones", "places") else ""

        cards.append(SlotCard(
            card_id=_stable_id(f"{default_header}|{value_ko}"),
            header_ko=default_header,
            header_translated=translate_term(default_header, target_lang),
            value_ko=value_ko,
            value_easy_ko=to_easy_korean(value_ko),
            value_translated=value_translated,
            # supplies → 준비물 칩, amounts/cost_support → 비용 칩
            # cost_support_info(지원 안내)는 학부모가 납부하지 않으므로 chip=None
            # 나머지 regex 슬롯은 카테고리 모호 → chip=None (체크리스트 미생성)
            chip=(
                Category.supplies.value if slot_name == "supplies"
                else Category.cost.value if slot_name in ("amounts", "cost_support")
                else None
            ),
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
    r"|[○◯O]\s*(?:\([^)]+\))?\s*[✕✗×]"  # 체크박스 페어 (Unicode circle + ASCII O)
    r"|[✕✗×Xx]\s*[○◯]"          # 역순 페어 (✕ 먼저)
    r"|[O○◯]\s*\([^)]+\)\s*[Xx✕✗×]\s*\([^)]+\)"  # "O(동의) X(미동의)" 형태
    r"|(?:네|예|동의)\s*(?:\([^)]+\))?\s*[Xx✕✗×]"  # "네(동의) X" 형태
    r"|[Xx✕✗×]\s*(?:아니오|미동의|동의하지)"        # "X 아니오(동의하지 않음)"
    r"|참가\s*여부\s+불참\s*사유"  # 표 헤더 "참가여부 불참사유"
    r"|참가\s*여부를?\s*$"        # 동의서 form 끝 "참가 여부를" 잔재
    r"|^[\s,]*[✕✗×]\s*로\s+표시" # 잘린 "✕로 표시하여..."
    r"|\d+학년\s*\(\s*\)\s*반"   # "2학년 ( )반 ( )번"
    r"|신청함?\s+신청하지\s*않음"  # "신청함 신청하지 않음 불참사유" 표 헤더
    r"|(?:네|예)\s*\([^)]{1,20}\)\s*/?\s*(?:아니오|미동의)\s*\([^)]{1,30}\)"  # "네(동의) 아니오(동의하지 않음)"
    r"|개인\s*정보\s*(?:제공|수집|활용|처리|동의)"  # 개인정보 동의 문장
    r"|상기\s*(?:의\s*)?내용을?\s*(?:확인|동의|읽고)"  # "상기의 내용을 확인하였으며"
    r"|이에\s*(?:동의|서명)\s*합니다"  # 동의서 서명 문장
    r"|위\s*내용에?\s*(?:동의|서명)"   # "위 내용에 동의합니다"
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

    1. 첫 한국어 sentence (다요까니 + .!?) — 전체보다 짧을 때만
    2. 첫 generic sentence (.!?) — 전체보다 짧을 때만
    3. 전체가 한 sentence 거나 매치 X → hard cut + 어절 경계 + "..."
    """
    if len(text) <= max_len:
        return text
    m = _FIRST_KO_SENTENCE.match(text)
    if m and len(m.group(1)) < len(text):
        return m.group(1)
    m = _FIRST_GENERIC_SENTENCE.match(text)
    if m and len(m.group(1)) < len(text):
        return m.group(1)
    # 전체가 한 sentence 거나 매치 X → hard cut
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
    if len(card.value_ko) <= _FALLBACK_MAX_KO_LEN:
        return card
    new_ko = _smart_trim(card.value_ko, max_len=_FALLBACK_MAX_KO_LEN)
    new_easy = card.value_easy_ko
    if card.value_easy_ko and len(card.value_easy_ko) > _FALLBACK_MAX_KO_LEN:
        new_easy = _smart_trim(card.value_easy_ko, max_len=_FALLBACK_MAX_KO_LEN)
    new_tr = card.value_translated
    if card.value_translated and len(card.value_translated) > _FALLBACK_MAX_TRANSLATED_LEN:
        new_tr = _smart_trim(card.value_translated, max_len=_FALLBACK_MAX_TRANSLATED_LEN)
    return card.model_copy(update={
        "value_ko": new_ko,
        "value_easy_ko": new_easy,
        "value_translated": new_tr,
    })


def _limit_fallback_cards(cards: list[SlotCard], max_fallback: int = _FALLBACK_MAX_CARDS) -> list[SlotCard]:
    """Limit noisy fallback cards while preserving classified/regex cards.

    OCR paragraphs that fail header splitting become "기타" cards. Keeping all
    of them makes the translated section read as repeated "Khac:" blocks, so
    keep only the highest-importance fallback cards after sorting.
    """
    kept: list[SlotCard] = []
    fallback_count = 0
    for card in cards:
        if card.header_ko == _FALLBACK_HEADER:
            fallback_count += 1
            if fallback_count > max_fallback:
                continue
        kept.append(card)
    return kept


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


_FORM_CHECKBOX_RE = re.compile(r"[○◯✕✗×]")
_FORM_DIVIDER_RE = re.compile(r"[-─—|]{3,}")

# 순수 개인정보 동의 진술 — submission chip으로 변환하지 않고 완전 제거.
# "상기의 내용을 확인하였으며 개인정보 제공에 동의합니다"처럼 동의 '서술문'은
# 학부모 행동 항목이 아님. (인)/성명/학년반번호 같은 form 기재란과 구분.
_PURE_CONSENT_RE = re.compile(
    r"개인\s*정보\s*(?:제공|수집|활용|처리|동의)"
    r"|상기\s*(?:의\s*)?내용을?\s*(?:확인|동의|읽고)"
    r"|이에\s*(?:동의|서명)\s*합니다"
    r"|위\s*내용에?\s*(?:동의|서명)"
    r"|동의\s*(?:서명|날인)"
)


def _transform_form_cards(cards: list[SlotCard]) -> list[SlotCard]:
    """동의서 form 카드를 삭제 대신 제출 chip 항목으로 변환.

    서명·동의 여부·학년/반/번호 기재란은 학부모가 실제로 처리해야 할
    항목이므로 삭제하지 않고 제출(submission) 칩 카드로 보존.
    체크박스 기호(○/✕)·구분선은 제거 후 의미 있는 텍스트가 남으면 변환,
    4자 미만으로 짧아지면 제거.
    """
    out: list[SlotCard] = []
    for card in cards:
        if not _is_form_card(card):
            out.append(card)
            continue
        # 순수 동의 진술문은 submission chip 변환 없이 완전 제거 (제출 탭 혼입 방지)
        if _PURE_CONSENT_RE.search(card.value_ko):
            continue
        ko = _FORM_CHECKBOX_RE.sub("", card.value_ko)
        ko = _FORM_DIVIDER_RE.sub("", ko)
        ko = re.sub(r"\s{2,}", " ", ko).strip().strip(":.：")
        if not ko or len(ko) < 4:
            continue
        out.append(card.model_copy(update={
            "value_ko": ko,
            "value_easy_ko": ko,
            "value_translated": "",
            "chip": Category.submission.value,
        }))
    return out


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


def _dedup_supply_items(cards: list[SlotCard]) -> list[SlotCard]:
    """준비물 체크리스트 항목 간 중복 제거.

    regex 추출 "물통" + LLM 추출 "물통은 개인 이름을 적어서 가져오세요."가
    함께 있으면, 더 짧은 핵심 항목("물통")을 유지하고 문장형을 제거한다.
    판별 기준: 짧은 항목이 긴 항목의 prefix이고 그 다음 문자가 조사/공백일 때.
    """
    supply_kos: list[str] = [
        item.ko.strip()
        for card in cards
        if card.chip == Category.supplies.value and card.checklist
        for item in card.checklist
    ]
    if len(supply_kos) <= 1:
        return cards

    def is_dominated(ko: str) -> bool:
        for other in supply_kos:
            if other == ko or len(other) >= len(ko):
                continue
            if ko.startswith(other):
                rest = ko[len(other):]
                if rest and (rest[0] in _KO_PARTICLES or rest[0] in " \t"):
                    return True
        return False

    out: list[SlotCard] = []
    for card in cards:
        if card.chip != Category.supplies.value or not card.checklist:
            out.append(card)
            continue
        filtered = [item for item in card.checklist if not is_dominated(item.ko.strip())]
        out.append(
            card.model_copy(update={"checklist": filtered})
            if len(filtered) != len(card.checklist)
            else card
        )
    return out


def build_cards(
    todos: list[YunjeongTodo],
    regex_slots: dict[str, list[dict]],
    target_lang: str,
) -> list[SlotCard]:
    """todos + regex_slots → list[SlotCard]. dedup + importance 내림차순 정렬.

    번역은 dedup/sort/limit 후 살아남은 카드만 한 번에 batch — NLLB CPU 14회 호출
    오버헤드를 1회 batch로 줄임 (2026-05-07).
    """
    cards = [_build_card_from_todo(t, target_lang) for t in todos]

    todo_headers = {c.header_ko for c in cards}
    cards.extend(_build_cards_from_regex_slots(regex_slots, target_lang, todo_headers))

    cards = _transform_form_cards(cards)
    # orphan merge 는 cards 가 본문 순서일 때만 안전한데, 윤정 todos 가 confidence
    # 순으로 들어와 직전 카드 = 본문 직전 카드 보장 X. 잘못 붙는 사고 방지를
    # 위해 merge 대신 단순 필터로 통일 (정보 일부 손실 감수).
    cards = [c for c in cards if not _is_short_fallback_card(c)]
    cards = [_trim_long_fallback_card(c) for c in cards]
    cards = _dedup_cards(cards)
    cards.sort(key=lambda c: -c.importance)
    cards = _limit_fallback_cards(cards)

    # 장소 헤더 카드 — 고유명사라 NLLB 오번역 심각 (해조류박람회 → 한 남자의 작품).
    # ko 그대로 미리 채워서 batch 번역에서 제외.
    _LOCATION_HEADERS = frozenset({"장소", "위치", "행사장", "개최장소", "집합장소"})
    for i, c in enumerate(cards):
        if not c.value_translated:
            h_norm = re.sub(r"\s+", "", c.header_ko or "")
            if h_norm in _LOCATION_HEADERS:
                cards[i] = c.model_copy(update={"value_translated": c.value_ko})

    # 살아남은 카드 value 만 batch 번역 — value_translated 가 빈 카드만 대상
    # (urls/phones 는 _build_cards_from_regex_slots 에서 ko 로 이미 채워둠)
    pending_idx = [i for i, c in enumerate(cards) if not c.value_translated]
    if pending_idx:
        pending_texts = [cards[i].value_ko for i in pending_idx]
        translated = translate_short_sentence_batch(pending_texts, target_lang)
        for i, tr in zip(pending_idx, translated):
            cards[i] = cards[i].model_copy(
                update={"value_translated": tr or cards[i].value_ko},
            )

    # 체크리스트 — 경이 카테고리(chip)가 행동성이면 value_ko 콤마/슬래시 split.
    # 정보성(일정) + None은 빈 리스트 → 안드 UI 체크박스 영역 미표시.
    for i, c in enumerate(cards):
        cl = _build_checklist_from_card(c, target_lang)
        if cl:
            cards[i] = c.model_copy(update={"checklist": cl})

    # 준비물 항목 dedup — regex "물통" + LLM "물통은 ... 가져오세요." 동시 존재 시
    # 짧은 핵심 항목 우선, 조사 확장형 문장 제거.
    cards = _dedup_supply_items(cards)

    return cards
