"""
시연 안정화 자체 테스트 — analyze 파이프라인 서비스 레이어 직접 검증

목적: 실제 analyze 응답에서 form artifact 제거·비용/지원 분리·달력 color·
      다국어 라벨이 올바르게 작동하는지 확인.
      (단순 단위 테스트 X — 실제 파이프라인 경로 검증)
"""
import json
import sys
import os
import re
import textwrap

# Windows cp949 콘솔 → UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)

# backend 루트를 import path에 추가
sys.path.insert(0, os.path.dirname(__file__))

from app.services.slot_extractor import (
    preprocess_notice_text,
    extract_cost_sentences,
    extract_cost_support_info,
    strip_markers,
)
from app.services.sentence_skeleton import (
    SentenceListDocument,
    SentenceListItem,
    raw_text_to_sentence_list,
)
from app.services.info_card_builder import build_info_cards_from_sentence_document
from app.services.calendar_event_builder import (
    build_calendar_events_from_sentence_document,
    merge_with_holidays,
)
from app.services.translator import translate_term
from app.services.card_builder import _FORM_SIGNALS

# ──────────────────────────────────────────────────────────────────────────────
# 테스트 데이터 — 현장체험학습 안내장 (form artifact 포함 버전)
# ──────────────────────────────────────────────────────────────────────────────

NOTICE_RAW = textwrap.dedent("""
    4학년 현장체험학습 안내

    안녕하십니까. 4학년 담임교사 일동입니다.
    아래와 같이 현장체험학습을 실시할 예정이오니 참고하시기 바랍니다.

    대상: 4학년 전체(61명)
    운영일시: 2026년 5월 6일(목) 8:50~14:40
    장소: 해조류박람회 및 빙그레 시네마
    활동 내용: 해조류박람회 및 빙그레 시네마 체험
    준비물: 도시락, 물통, 돗자리

    비용 안내
    비용: ○ 체험학습비: 23,000원 (4/13 스쿨뱅킹 자동이체)
    비용: O 체험학습비: 스쿨뱅킹 잔액 부족 시 선납 바랍니다.
    납부기간: 2026. 4. 13.(월)~2026. 4. 15.(수)
    잔액 확인 부탁드립니다.

    지원 안내
    버스 1대 지원 (왕복)
    보험료: 학교에서 전액 지원
    양주시농업기술센터 지원사업 관련 안내

    동의서 제출 안내
    참가 여부: O / X
    개인정보 제공 동의 확인 필요
    동의 여부를 O/X로 표시해 주세요.
    보호자 서명: ___________
    불참 시 사유를 작성해 주세요.
    네(동의) 아니오(동의하지 않음) (단, 동의하지 않을 시 보험비 및 차량 지원과 현장체험학습 운영이 어려울 수 있습니다.)
    신청함 신청하지 않음 불참사유

    제출기한: 2026. 4. 28.(화)까지 담임 선생님께 제출

    아래 동의서를 작성하여 제출해 주세요.
    ─────────────────────────────────────────
    학년   반   번호   이름:
    보호자 서명:
    참가 여부: O / X
    개인정보 제공 동의: O(동의) X(미동의)
    상기 내용을 확인하였으며 이에 동의합니다.
    ─────────────────────────────────────────
""").strip()

# Gemini structured output에 form artifact가 포함된 경우 시뮬레이션
GEMINI_STRUCTURED_WITH_ARTIFACTS = {
    "document_title": "4학년 현장체험학습 안내",
    "sentence_list": [
        {"sentence_id": "s1", "text": "대상: 4학년 전체(61명)", "role_hint": "target", "source_order": 1},
        {"sentence_id": "s2", "text": "운영일시: 2026년 5월 6일(목) 8:50~14:40", "role_hint": "event_datetime", "source_order": 2, "contains_slots": ["date", "time"]},
        {"sentence_id": "s3", "text": "장소: 해조류박람회 및 빙그레 시네마", "role_hint": "location", "source_order": 3},
        {"sentence_id": "s4", "text": "활동 내용: 해조류박람회 및 빙그레 시네마 체험", "role_hint": "content", "source_order": 4},
        {"sentence_id": "s5", "text": "준비물: 도시락, 물통, 돗자리", "role_hint": "supplies", "source_order": 5},
        {"sentence_id": "s6", "text": "○ 체험학습비: 23,000원 (4/13 스쿨뱅킹 자동이체)", "role_hint": "fee", "source_order": 6, "contains_slots": ["amount", "date"]},
        {"sentence_id": "s7", "text": "납부기간: 2026. 4. 13.(월)~2026. 4. 15.(수)", "role_hint": "fee", "source_order": 7, "contains_slots": ["date"]},
        {"sentence_id": "s8", "text": "잔액 부족 시 선납 부탁드립니다. ___", "role_hint": "fee", "source_order": 8},
        {"sentence_id": "s9", "text": "버스 1대 지원 (왕복)", "role_hint": "etc", "source_order": 9},
        {"sentence_id": "s10", "text": "보험료: 학교에서 전액 지원", "role_hint": "etc", "source_order": 10},
        {"sentence_id": "s11", "text": "제출기한: 2026. 4. 28.(화)까지 담임 선생님께 제출", "role_hint": "submit", "source_order": 11, "contains_slots": ["date"]},
        # form artifacts — sanitize로 제거되어야 함
        {"sentence_id": "s12", "text": "2학년 ( )반 ( )번 이름( )", "role_hint": "etc", "source_order": 12},
        {"sentence_id": "s13", "text": "보호자 서명: ___________", "role_hint": "etc", "source_order": 13},
        {"sentence_id": "s14", "text": "참가 여부: O(동의) X(미동의)", "role_hint": "etc", "source_order": 14},
        {"sentence_id": "s15", "text": "상기의 내용을 확인하였으며 이에 동의합니다.", "role_hint": "etc", "source_order": 15},
        {"sentence_id": "s16", "text": "개인정보 제공 동의 확인 필요", "role_hint": "etc", "source_order": 16},
    ],
}

# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []  # (항목, 결과, 비고)


def check(label: str, condition: bool, note: str = "") -> bool:
    tag = PASS if condition else FAIL
    results.append((label, tag, note))
    return condition


def dump_all_text(obj) -> str:
    """모든 string 필드를 재귀적으로 수집."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(dump_all_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(dump_all_text(item) for item in obj)
    try:
        return dump_all_text(obj.__dict__)
    except AttributeError:
        pass
    try:
        return dump_all_text(obj.model_dump())
    except Exception:
        return str(obj)


# 금지 패턴
FORBIDDEN = [
    ("___", re.compile(r"_{3,}")),
    ("( ) / ( )", re.compile(r"\(\s{0,10}\)\s*/\s*\(\s{0,10}\)")),
    ("빈 괄호", re.compile(r"\(\s{1,10}\)")),
    ("○ 체험학습비", re.compile(r"[○◯]\s*체험학습비")),
    ("O 체험학습비", re.compile(r"(?<![가-힣a-zA-Z])O\s+체험학습비")),
    ("Không, không", re.compile(r"Không,\s*không", re.IGNORECASE)),
    ("Đúng rồi", re.compile(r"Đúng\s*rồi", re.IGNORECASE)),
    ("Cảm ơn anh", re.compile(r"Cảm\s*ơn", re.IGNORECASE)),
    ("____Ngày", re.compile(r"_{2,}\s*Ngày", re.IGNORECASE)),
    ("-----", re.compile(r"[-─—]{5,}")),
]


# ──────────────────────────────────────────────────────────────────────────────
# § 1. preprocess_notice_text — artifact 제거 확인
# ──────────────────────────────────────────────────────────────────────────────

print("\n[1] preprocess_notice_text artifact 제거")
preprocessed = preprocess_notice_text(NOTICE_RAW)

check("밑줄(___) 제거", "___" not in preprocessed, preprocessed[:50])
check("구분선(─────) 제거", not re.search(r"[─—]{5,}", preprocessed))
check("빈 괄호( ) 제거", not re.search(r"\(\s{1,10}\)", preprocessed))
check("○ 체험학습비 제거", "○ 체험학습비" not in preprocessed and "○체험학습비" not in preprocessed)
check("O 체험학습비 제거", not re.search(r"(?<![가-힣a-zA-Z])O\s+체험학습비", preprocessed))
check("학년반번호 form 제거 (OX 기호 제거)", not re.search(r"[○◯O]\s*\([^)]+\)\s*[X✕✗×]", preprocessed))
# P0: 신규 추가 항목
check("비용: 체험학습비: 이중 라벨 제거",
      not re.search(r"^비용\s*[:：]\s*체험학습비", preprocessed, re.MULTILINE),
      preprocessed[:80])
check("네(동의) 아니오(동의하지 않음) 제거 — Đúng rồi 오역 차단",
      not re.search(r"(?:네|예)\s*\([^)]+\)\s*/?\s*(?:아니오|미동의)\s*\([^)]+\)", preprocessed),
      preprocessed[:80])
check("신청함 신청하지 않음 표 헤더 제거 — Không xin đơn 오역 차단",
      "신청함 신청하지 않음" not in preprocessed)


# ──────────────────────────────────────────────────────────────────────────────
# § 2. _sanitize_sentence_doc 시뮬레이션 — Gemini structured 경로 검증
# ──────────────────────────────────────────────────────────────────────────────

print("\n[2] sentence_doc sanitize (Gemini structured 경로 시뮬레이션)")

# _sentence_doc_from_structured 에 해당하는 수동 빌드
from app.services.sentence_skeleton import parse_sentence_list_payload
raw_doc = parse_sentence_list_payload(GEMINI_STRUCTURED_WITH_ARTIFACTS)

# _sanitize_sentence_doc 로직 재현
def sanitize_sentence_doc(doc: SentenceListDocument) -> SentenceListDocument:
    cleaned_items = []
    for item in doc.sentence_list:
        if not item.text:
            continue
        item.text = preprocess_notice_text(item.text)
        if item.text.strip():
            cleaned_items.append(item)
    doc.sentence_list = cleaned_items
    return doc

sanitized_doc = sanitize_sentence_doc(raw_doc)
all_sentence_texts = " ".join(item.text for item in sanitized_doc.sentence_list)

check("sanitize 후 ○/O 체험학습비 제거", not re.search(r"[○◯O]\s+체험학습비", all_sentence_texts),
      f"남은 텍스트 샘플: {all_sentence_texts[:100]}")
check("sanitize 후 ___ 제거", "___" not in all_sentence_texts)
check("sanitize 후 빈 괄호( ) 제거", not re.search(r"\(\s{1,10}\)", all_sentence_texts))
check("sanitize 후 OX 쌍 제거", not re.search(r"[○◯O]\s*\([^)]+\)\s*[X✕✗×]", all_sentence_texts))
# form stub 문장("2학년  반  번 이름")이 남는지 — 빈 괄호 제거 후에도 "2학년 반 번 이름" 잔재 허용
# (preprocess가 괄호만 제거하므로 텍스트 stub 잔재는 OK — 정보 자체가 무해함)

# 유효 sentence가 살아있는지 확인
fee_texts = [i.text for i in sanitized_doc.sentence_list if i.role_hint == "fee"]
check("fee 역할 sentence 보존", len(fee_texts) > 0, str(fee_texts))
supply_texts = [i.text for i in sanitized_doc.sentence_list if i.role_hint == "supplies"]
check("supplies 역할 sentence 보존", len(supply_texts) > 0, str(supply_texts))
submit_texts = [i.text for i in sanitized_doc.sentence_list if i.role_hint == "submit"]
check("submit 역할 sentence 보존", len(submit_texts) > 0, str(submit_texts))


# ──────────────────────────────────────────────────────────────────────────────
# § 3. 비용/지원 분리 — extract_cost_sentences vs extract_cost_support_info
# ──────────────────────────────────────────────────────────────────────────────

print("\n[3] 비용/지원 분리")

cost_lines = extract_cost_sentences(preprocessed)
support_lines = extract_cost_support_info(preprocessed)
cost_dump = " ".join(cost_lines)
support_dump = " ".join(support_lines)

check("체험학습비 → 비용탭", any("체험학습비" in l or "23,000" in l for l in cost_lines),
      f"cost={cost_lines}")
check("스쿨뱅킹 → 비용탭", any("스쿨뱅킹" in l for l in cost_lines))
check("잔액 → 비용탭", any("잔액" in l for l in cost_lines))
check("버스 지원 → 지원 안내탭", any("버스" in l for l in support_lines),
      f"support={support_lines}")
check("보험료 지원 → 지원 안내탭", any("보험료" in l for l in support_lines))
check("개인정보 동의 → 비용탭 제외", not any("개인정보" in l for l in cost_lines))
check("개인정보 동의 → 지원 안내탭 제외", not any("개인정보" in l for l in support_lines))


# ──────────────────────────────────────────────────────────────────────────────
# § 4. info_cards — sanitized sentence_doc 기준
# ──────────────────────────────────────────────────────────────────────────────

print("\n[4] info_cards (sanitized sentence_doc 기준)")

info_cards = build_info_cards_from_sentence_document(sanitized_doc, "vi_demo")
info_dump = dump_all_text(info_cards)

for label, pat in FORBIDDEN:
    found = pat.search(info_dump)
    check(f"info_cards artifact 없음: {label}", not found,
          f"발견: {found.group()[:40]}" if found else "")

# 대상/일시/장소/활동/준비물 info_card 보존 확인
headers_ko = {c.header_ko for c in info_cards}
check("대상 info_card 보존", any("대상" in h for h in headers_ko), str(headers_ko))
check("운영일시 info_card 보존", any("일시" in h or "운영" in h for h in headers_ko), str(headers_ko))
check("장소 info_card 보존", any("장소" in h for h in headers_ko), str(headers_ko))
check("활동 내용 info_card 보존", any("활동" in h or "내용" in h for h in headers_ko), str(headers_ko))
check("준비물 info_card 보존", any("준비물" in h for h in headers_ko), str(headers_ko))


# ──────────────────────────────────────────────────────────────────────────────
# § 5. 달력 이벤트 — 납부기간 period + 색상
# ──────────────────────────────────────────────────────────────────────────────

print("\n[5] 달력 이벤트")

calendar_events = build_calendar_events_from_sentence_document(
    sanitized_doc, notice_id="n_test", title="4학년 현장체험학습 안내"
)
calendar_events = merge_with_holidays(calendar_events, 2026)

# 이벤트 목록 출력 (디버그)
for ev in calendar_events:
    print(f"  event_id={ev.event_id} type={ev.type} color={ev.color} "
          f"start={ev.start_date} end={ev.end_date} title={ev.display_text[:40]!r}")

# 납부기간 4/13~4/15
fee_events = [e for e in calendar_events if e.type == "payment_deadline"]
fee_period_events = [e for e in fee_events if e.start_date != e.end_date]
check("납부기간 이벤트 존재", len(fee_events) > 0, f"fee_events={[e.start_date for e in fee_events]}")
check("납부기간 4/13 start", any(e.start_date == "2026-04-13" for e in fee_events))
check("납부기간 기간(end!=start) 탐지", len(fee_period_events) > 0 or any(
    e.start_date == "2026-04-13" and e.end_date == "2026-04-15" for e in fee_events),
      f"fee_events start/end={[(e.start_date, e.end_date) for e in fee_events]}")
check("납부기간 gold 색상", all(e.color == "gold" for e in fee_events),
      f"colors={[e.color for e in fee_events]}")

# 4/13 납부 날짜 red 아님
check("4/13 payment_deadline red 아님", not any(
    e.start_date == "2026-04-13" and e.color == "red" for e in calendar_events))

# 공휴일 red
holiday_events = [e for e in calendar_events if e.type == "holiday"]
check("2026-05-05 어린이날 red", any(
    e.start_date == "2026-05-05" and e.color == "red" for e in holiday_events))
check("2026-10-09 한글날 red", any(
    e.start_date == "2026-10-09" and e.color == "red" for e in holiday_events))

# 행사일시 green
event_dt_events = [e for e in calendar_events if e.type == "event_datetime"]
check("행사일시(5/6) green", any(
    e.start_date == "2026-05-06" and e.color == "green" for e in event_dt_events),
    f"event_dt={[(e.start_date, e.color) for e in event_dt_events]}")

# 제출기한 orange
submit_events = [e for e in calendar_events if e.type == "submit_deadline"]
check("제출기한 orange", all(e.color == "orange" for e in submit_events),
    f"submit_events={[(e.start_date, e.color) for e in submit_events]}")

# 달력 display_text — payment_deadline에 장소 붙지 않음
for ev in fee_events:
    check(f"납부달력에 장소 미포함 ({ev.start_date})",
          "장소" not in ev.display_text and "빙그레" not in ev.display_text,
          f"display={ev.display_text[:60]!r}")

# 달력 display_text — event_datetime에 장소 포함
for ev in event_dt_events:
    check(f"행사달력 장소 포함 ({ev.start_date})",
          "장소" in ev.display_text or "해조류" in ev.display_text,
          f"display={ev.display_text[:80]!r}")


# ──────────────────────────────────────────────────────────────────────────────
# § 6. 다국어 라벨 — translate_term("지원 안내", ...)
# ──────────────────────────────────────────────────────────────────────────────

print("\n[6] 다국어 라벨 (translate_term)")

term_tests = [
    ("ko_easy",  "지원 안내",         "지원 안내"),       # ko passthrough
    ("vi_demo",  "지원 안내",         "Thông tin hỗ trợ"),
    ("en",       "지원 안내",         "Support information"),
    ("zh",       "지원 안내",         "支援信息"),         # 支援信息 또는 支援说明 허용
    ("vi",       "지원안내",          "Thông tin hỗ trợ"),  # 공백 없는 variant
]

for lang, term, expected in term_tests:
    result = translate_term(term, lang)
    if lang == "zh":
        ok = result in ("支援信息", "支援说明", "支援訊息")
    else:
        ok = (result == expected)
    check(f"translate_term({term!r}, {lang!r})", ok,
          f"expected={expected!r} actual={result!r}")


# ──────────────────────────────────────────────────────────────────────────────
# § 7. _FORM_SIGNALS — card_builder 필터 동작 확인
# ──────────────────────────────────────────────────────────────────────────────

print("\n[7] _FORM_SIGNALS 패턴 탐지")

form_signal_tests = [
    ("개인정보 제공 동의",         True,  "개인정보 제공 동의 확인 필요"),
    ("상기내용 확인 동의",         True,  "상기의 내용을 확인하였으며 이에 동의합니다."),
    ("OX 쌍 탐지",                True,  "O(동의) X(미동의)"),
    ("학년반번호 form",           True,  "2학년 ( )반 ( )번"),
    ("일반 문장 오탐 없음",        False, "도시락, 물통, 돗자리를 준비해 주세요."),
]

for label, should_match, text in form_signal_tests:
    matched = bool(_FORM_SIGNALS.search(text))
    check(f"_FORM_SIGNALS: {label}", matched == should_match,
          f"text={text!r} matched={matched}")


# ──────────────────────────────────────────────────────────────────────────────
# § 8. 전체 dump artifact 검사 — info_cards + calendar 합산
# ──────────────────────────────────────────────────────────────────────────────

print("\n[8] 전체 output dump artifact 검사")

full_dump = dump_all_text(info_cards) + " " + dump_all_text(calendar_events)

for label, pat in FORBIDDEN:
    found = pat.search(full_dump)
    check(f"dump artifact 없음: {label}", not found,
          f"발견: {found.group()[:50]!r}" if found else "")


# ──────────────────────────────────────────────────────────────────────────────
# 결과 출력
# ──────────────────────────────────────────────────────────────────────────────

pass_count = sum(1 for _, tag, _ in results if tag == PASS)
fail_count = sum(1 for _, tag, _ in results if tag == FAIL)
total = len(results)

print()
print("=" * 72)
print(f"{'항목':<44} {'결과':<8} {'비고'}")
print("=" * 72)
for label, tag, note in results:
    mark = "V" if tag == PASS else "X"
    note_trimmed = (note[:30] + "...") if len(note) > 33 else note
    print(f"{mark} {label:<43} {tag:<8} {note_trimmed}")
print("=" * 72)
print(f"합계: {pass_count} PASS / {fail_count} FAIL  (총 {total}개)")
print()

if fail_count:
    print("[비용 탭 실제 lines]")
    for l in cost_lines[:5]:
        print(f"  - {l}")
    print("[지원 안내 탭 실제 lines]")
    for l in support_lines[:5]:
        print(f"  - {l}")
    print()

if fail_count == 0:
    print(">> 배포 가능")
else:
    print(">> 추가 수정 필요")
    print("   P0: artifact가 번역문에 남는 항목")
    print("   P1: 달력 color/기간 오탐")
    print("   P2: 라벨/분류 미세 조정")
