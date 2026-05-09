"""정규식 + i18n 포매터 기반 슬롯 추출기.

강사 처방(2026-04-28) 대응:
  - 날짜·시간·금액 같은 명확한 수치 데이터는 정규식으로 1차 안전 추출
  - LLM 추론에 100% 의존하지 않고 지정된 위치(슬롯)에 매핑
  - NLLB/glossary 거치지 않고 i18n 룰만으로 대상 언어 변환

설계:
  extract_dates/extract_times/extract_amounts → 구조화된 dict 리스트
  format_date/format_time/format_amount → 대상 언어 문자열
  extract_summary_regex_slots → 위 둘을 묶어 SlotEntry 호환 dict 반환
"""
from __future__ import annotations

import re

# ── 정규식 ────────────────────────────────────────────────────────
_DATE_FULL = re.compile(
    r"(?P<year>\d{4})\s*년\s*(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"(?:\s*\((?P<wday>[월화수목금토일])\))?"
)
_DATE_MD = re.compile(
    r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"(?:\s*\((?P<wday>[월화수목금토일])\))?"
)
_DATE_SLASH = re.compile(r"\b(?P<month>\d{1,2})\s*[/.]\s*(?P<day>\d{1,2})\b")
# 점 표기 ("2026. 4. 18.(토)" / "5. 16.(토)") — 요일 필수로 시간·금액 오탐 회피
_DATE_DOT = re.compile(
    r"(?:(?P<year>\d{4})\s*\.\s*)?"
    r"(?P<month>\d{1,2})\s*\.\s*"
    r"(?P<day>\d{1,2})\s*\.?"
    r"\s*\((?P<wday>[월화수목금토일])\)"
)
_DATE_RELATIVE = ["내일", "모레", "오늘", "다음 주", "다음주", "이번 주", "이번주"]

_TIME_AMPM = re.compile(
    r"(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2})\s*시(?:\s*(?P<minute>\d{1,2})\s*분)?"
)
_TIME_24H = re.compile(r"(?<!\d)(?P<hour>\d{1,2}):(?P<minute>\d{2})(?!\d)")

_AMOUNT_KRW = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)\s*원")
_AMOUNT_KO = re.compile(r"(?P<num>\d+)\s*(?P<unit>만|천|억)\s*원")

# URL: http(s)://… 또는 www.…  — NLLB가 토큰화하면서 깨먹는 패턴 방지용 슬롯
_URL = re.compile(r"\bhttps?://[^\s<>\"'()]+|\bwww\.[^\s<>\"'()]+", re.IGNORECASE)
# 전화번호: 02-xxx-xxxx, 02-xxxx-xxxx, 010-xxxx-xxxx, 1588-0260, 849-7003 등
# 시작·끝에 숫자 인접 금지 (15,000원 같은 금액 부분 매칭 회피)
_PHONE = re.compile(
    r"(?<![\d-])"
    r"(?:\d{2,4}-\d{3,4}-\d{4}|\d{4}-\d{4}|\d{3,4}-\d{4})"
    r"(?!\d)"
)

# 까지 마감 표현: "5월 9일까지", "내일까지", "5월 9일(금)까지 ... 제출"
# 콤마는 negation에서 제외 — "15,000원 (...까지...)" 같이 숫자 콤마에서 잘리는 버그 회피
# 한글 프로 마커(❍❏|※)도 종결자 — pdfplumber 본문이 한 줄로 들어와도 항목 단위로 끊김
_DEADLINE_PHRASE = re.compile(r"([^.\n❍❏|※]*?까지[^.\n❍❏|※]*?)(?=[.\n❍❏|※]|$)")

# 날짜 앞뒤 60자에 서명/발신 문구가 있으면 발송일(통지 날짜)로 판단 → dates 슬롯 제외.
# "드립니다"는 본문 어디서나 쓰이므로 "드림"만 단독 매칭 (드림니다 제외).
_NOTICE_SIGN_OFF = re.compile(
    r"드림(?!니다)"
    r"|올림(?!니다)"
    r"|담임\s*교사"
    r"|교\s*장\s*직인"
    r"|작성\s*일"
    r"|발송\s*일"
)

# 안내문 줄머리 장식 마크업 (■ ▶ ▸ etc.) — items/슬롯 추출 전 strip
# Latin O 는 유니코드 ○ 와 다른 코드포인트 — 별도 alt 패턴으로 추가
_MARKER_STRIP = re.compile(r"^(?:[\s■▶▸◆●○*\-•]+|O\s+(?=[가-힣]))")


def strip_markers(text: str) -> str:
    """줄머리 장식 마크업 제거. UI 표시·TTS 양쪽 노이즈 방지."""
    return _MARKER_STRIP.sub("", text).strip()


# ── 추출기 ────────────────────────────────────────────────────────
def extract_dates(text: str) -> list[dict]:
    """텍스트에서 날짜 후보를 모두 뽑는다. 중복은 표면형 기준으로 제거."""
    out: list[dict] = []
    seen: set[str] = set()

    for m in _DATE_FULL.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "year": int(m.group("year")),
            "month": int(m.group("month")),
            "day": int(m.group("day")),
            "weekday": m.group("wday"),
        })

    for m in _DATE_MD.finditer(text):
        # 이미 _DATE_FULL이 잡은 영역과 겹치면 스킵
        if any(s in text and m.start() >= text.find(s) and m.end() <= text.find(s) + len(s) for s in seen):
            continue
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "year": None,
            "month": int(m.group("month")),
            "day": int(m.group("day")),
            "weekday": m.group("wday"),
        })

    for m in _DATE_DOT.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "year": int(m.group("year")) if m.group("year") else None,
            "month": int(m.group("month")),
            "day": int(m.group("day")),
            "weekday": m.group("wday"),
        })

    for word in _DATE_RELATIVE:
        if word in text and word not in seen:
            seen.add(word)
            out.append({"ko": word, "year": None, "month": None, "day": None,
                        "weekday": None, "relative": word})

    return out


def extract_times(text: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for m in _TIME_AMPM.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "hour": int(m.group("hour")),
            "minute": int(m.group("minute")) if m.group("minute") else 0,
            "ampm": m.group("ampm"),
        })
    for m in _TIME_24H.finditer(text):
        hour = int(m.group("hour"))
        minute = int(m.group("minute"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "hour": hour,
            "minute": minute,
            "ampm": None,
        })
    return out


def extract_amounts(text: str) -> list[dict]:
    """원화 금액을 정규화된 정수와 함께 반환."""
    out: list[dict] = []
    seen: set[str] = set()

    for m in _AMOUNT_KRW.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        num = int(m.group("num").replace(",", ""))
        out.append({"ko": ko, "value": num, "currency": "KRW"})

    for m in _AMOUNT_KO.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        n = int(m.group("num"))
        unit = m.group("unit")
        mul = {"천": 1_000, "만": 10_000, "억": 100_000_000}[unit]
        out.append({"ko": ko, "value": n * mul, "currency": "KRW"})

    return out


def extract_deadline_phrases(text: str) -> list[str]:
    """'까지'가 들어간 어구를 한 문장 단위로 추출.

    URL 안 마침표(`.do`/`.kr` 등)에서 phrase가 잘려 무의미하게 길어지는 것 회피 —
    매칭 전 URL을 placeholder로 마스킹 후 매칭.
    """
    masked = _URL.sub(lambda m: "⟦U" + ("_" * (len(m.group(0)) - 3)) + "⟧", text)
    return [m.group(1).strip() for m in _DEADLINE_PHRASE.finditer(masked)]


_URL_TRAILING_JOSA = re.compile(r"[가-힣]+$")

def extract_urls(text: str) -> list[str]:
    """URL 표면형 그대로. NLLB로 보내지 말고 슬롯으로 격리."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL.finditer(text):
        ko = _URL_TRAILING_JOSA.sub("", m.group(0).strip().rstrip(".,)]"))
        if ko in seen:
            continue
        seen.add(ko)
        out.append(ko)
    return out


def extract_phones(text: str) -> list[str]:
    """전화번호 표면형. 같은 이유로 슬롯 격리."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _PHONE.finditer(text):
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append(ko)
    return out


# ── 다국어 포매터 ─────────────────────────────────────────────────
# 베트남어가 1차 시연 타깃이라 가장 정교하게. 나머지 언어는 안전한 디폴트.
_WEEKDAY_VI = {"월": "Thứ Hai", "화": "Thứ Ba", "수": "Thứ Tư", "목": "Thứ Năm",
               "금": "Thứ Sáu", "토": "Thứ Bảy", "일": "Chủ Nhật"}
_WEEKDAY_EN = {"월": "Mon", "화": "Tue", "수": "Wed", "목": "Thu",
               "금": "Fri", "토": "Sat", "일": "Sun"}
_RELATIVE_MAP = {
    "vi": {"내일": "Ngày mai", "모레": "Ngày kia", "오늘": "Hôm nay",
           "다음 주": "Tuần sau", "다음주": "Tuần sau",
           "이번 주": "Tuần này", "이번주": "Tuần này"},
    "en": {"내일": "Tomorrow", "모레": "Day after tomorrow", "오늘": "Today",
           "다음 주": "Next week", "다음주": "Next week",
           "이번 주": "This week", "이번주": "This week"},
}


def format_date(d: dict, target_lang: str) -> str:
    if d.get("relative"):
        return _RELATIVE_MAP.get(target_lang, {}).get(d["relative"], d["ko"])
    y, m, day, w = d.get("year"), d.get("month"), d.get("day"), d.get("weekday")
    if not (m and day):
        return d["ko"]
    if target_lang == "vi":
        s = f"Ngày {day}/{m}" + (f"/{y}" if y else "")
        if w:
            s += f" ({_WEEKDAY_VI[w]})"
        return s
    if target_lang == "en":
        months = ["", "January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        s = f"{months[m]} {day}" + (f", {y}" if y else "")
        if w:
            s += f" ({_WEEKDAY_EN[w]})"
        return s
    if target_lang in ("zh", "ja"):
        return f"{m}月{day}日" + (f" ({w})" if w else "")
    if target_lang == "ko_easy":
        return d["ko"]  # 그대로
    # ru / ms / th / mn 등은 일단 안전한 숫자 포맷
    return f"{day}/{m}" + (f"/{y}" if y else "")


def format_time(t: dict, target_lang: str) -> str:
    h, mm, ampm = t.get("hour"), t.get("minute") or 0, t.get("ampm")
    if h is None:
        return t["ko"]
    if target_lang == "vi":
        suffix = ""
        if ampm == "오전":
            suffix = " sáng"
        elif ampm == "오후":
            suffix = " chiều"
        return f"{h} giờ{(' ' + str(mm)) if mm else ''}{suffix}".strip()
    if target_lang == "en":
        ap = "AM" if ampm == "오전" else "PM" if ampm == "오후" else ""
        return f"{h}:{mm:02d} {ap}".strip() if ap else f"{h}:{mm:02d}"
    if target_lang in ("zh", "ja"):
        prefix = "上午" if ampm == "오전" else "下午" if ampm == "오후" else ""
        if target_lang == "ja":
            prefix = "午前" if ampm == "오전" else "午後" if ampm == "오후" else ""
        body = f"{h}時{mm:02d}分" if target_lang == "ja" else f"{h}时{mm:02d}分"
        return f"{prefix}{body}"
    if target_lang == "ko_easy":
        return t["ko"]
    return f"{h}:{mm:02d}"


def format_amount(a: dict, target_lang: str) -> str:
    n = a["value"]
    # 천단위 콤마. (베트남식 점 표기는 _post_process_vi와 충돌하므로 콤마로 통일)
    formatted = f"{n:,}"
    suffix = {
        "vi": " won", "en": " won", "ms": " won", "ru": " вон", "mn": " вон",
        "th": " วอน", "zh": "韩元", "ja": "ウォン", "ko_easy": "원",
    }.get(target_lang, " won")
    return f"{formatted}{suffix}"


# 같은 줄 콜론: "준비물: 도화지, 크레파스, ..."
_SUPPLIES_INLINE_RE = re.compile(
    r"^[ \t]*(?:\d+\.)?[ \t]*"
    r"(?:준\s*비물?|지\s*참\s*물?|준비\s*사항|챙길\s*것|준비할\s*것)"
    r"[ \t]*[:：][ \t]*(.+)$"
)

# 독립 헤더: "5. 준비물" (콜론/내용 없이 헤더만)
_SUPPLIES_STANDALONE_RE = re.compile(
    r"^[ \t]*(?:\d+\.)?[ \t]*"
    r"(?:준\s*비물?|지\s*참\s*물?|준비\s*사항|챙길\s*것|준비할\s*것)"
    r"[ \t]*$"
)

# 다음 번호 섹션 헤더: "6. 제출물", "7. 유의사항" 등
_NEXT_SECTION_RE = re.compile(r"^[ \t]*\d+\.[ \t]*\S")

# 명사 목록 구분자
_NOUN_SEP = re.compile(r"[,，、·/]\s*")

# 동사 어미 — 이 패턴이 있으면 명사 목록 아님
_VERB_END_RE = re.compile(
    r"주세요|해주세요|하세요|주십시오|하십시오"
    r"|됩니다|합니다|있습니다|입니다|바랍니다|주시기"
)


def _is_noun_list(line: str) -> bool:
    """줄이 콤마/슬래시/가운뎃점으로 구분된 짧은 명사 목록인지 판단."""
    s = line.strip()
    if not s or _VERB_END_RE.search(s):
        return False
    if not re.search(r"[,，、·/]", s):
        return False
    tokens = [t.strip() for t in _NOUN_SEP.split(s) if t.strip()]
    return bool(tokens) and all(0 < len(t) <= 20 for t in tokens)


def extract_supplies(text: str) -> list[str]:
    """본문에서 준비물 목록 추출.

    패턴 1 — 같은 줄 콜론:   "준비물: 도화지, 크레파스, ..."
    패턴 2 — 독립 헤더 + 다음 줄:
        "5. 준비물
         도화지, 크레파스, 사인펜, ..."

    다음 번호 섹션 헤더 또는 동사 어미 문장에서 수집 종료.
    """
    lines = text.splitlines()
    out: list[str] = []
    seen: set[str] = set()
    collecting = False
    block_lines: list[str] = []

    def emit_block() -> None:
        nonlocal collecting
        if block_lines:
            combined = ", ".join(block_lines)
            if combined not in seen:
                seen.add(combined)
                out.append(combined)
            block_lines.clear()
        collecting = False

    for line in lines:
        s = line.strip()

        m = _SUPPLIES_INLINE_RE.match(s)
        if m:
            emit_block()
            val = m.group(1).strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
            continue

        if _SUPPLIES_STANDALONE_RE.match(s):
            emit_block()
            collecting = True
            continue

        if not collecting:
            continue

        if _NEXT_SECTION_RE.match(s):
            emit_block()
            continue

        if not s:
            if block_lines:
                emit_block()
            continue

        if _is_noun_list(s):
            block_lines.append(s)
        else:
            emit_block()

    emit_block()
    return out


# ── 서식 아티팩트 제거 ───────────────────────────────────────────
_BLANK_UNDERSCORES = re.compile(r"_{3,}")
_BLANK_DASHES_LINE = re.compile(r"^[ \t\-─—]{5,}[ \t]*$", re.MULTILINE)
# 점선 구분선 단독 줄: "......" "······" 등
_BLANK_DOTS_LINE = re.compile(r"^[ \t]*[.·…]{5,}[ \t]*$", re.MULTILINE)
# 빈 괄호: "(   )" (공백 2개 이상 또는 1개)
_BLANK_PARENS = re.compile(r"\(\s+\)")
# OX 체크박스 기호 — 번역기에 "Không, không" 오번역 유발
# 동의(○)/미동의(×) 형태의 선택지 줄: "네(동의) X 아니오(동의하지 않음) X" 등
# Latin O(U+004F) 도 불릿 문맥에서 제거: "O 체험학습비" → "체험학습비"
_OX_CHOICE_SYMBOLS = re.compile(
    r"(?<![가-힣a-zA-Z])"        # 일반 단어 뒤에 오는 건 보존
    r"[○◯✕✗×XxO]\s*"            # OX 기호 + Latin O 불릿
    r"(?=[(\s]|$)"              # 기호 뒤 괄호·공백·줄끝
)
# 줄 전체가 기호+공백만인 순수 구분선 줄
_SYMBOL_ONLY_LINE = re.compile(
    r"^[ \t]*[━─=\-~·.○◯✕✗×▪▫■□▶▸◆●○*]{5,}[ \t]*$",
    re.MULTILINE,
)
# "네(동의) 아니오(동의하지 않음)" 한국어 YN 선택지 — 기호 없이 한국어로 적힌 OX
# NLLB가 "Đúng rồi. – Cảm ơn anh!" 오역 유발. 앞부분만 제거, 뒤 문장(단서 조항)은 보존.
_KO_YN_CHOICE_RE = re.compile(
    r"(?:네|예)\s*\([^)]{1,20}\)\s*/?\s*(?:아니오|미동의)\s*\([^)]{1,30}\)"
)
# "신청함 신청하지 않음 불참사유" — 신청 여부 선택 표 헤더 단독 줄
# Yunjeong가 todo로 잘못 추출, NLLB가 "Không xin đơn. Cần phải nộp..." 오역 유발.
_FORM_TABLE_HEADER_RE = re.compile(
    r"^[ \t]*신청함?\s+신청하지\s*않음[^\n]*$",
    re.MULTILINE,
)
# "비용: 체험학습비: 23,000원" → "체험학습비: 23,000원" — 줄머리 중복 비용 라벨 제거
# _OX_CHOICE_SYMBOLS 적용 후 "비용: O 체험학습비:" → "비용: 체험학습비:" → "체험학습비:"
# NLLB value_ko 번역 시 "Chi phí: phí trải nghiệm:" 이중 라벨 유발 차단.
_COST_OUTER_LABEL_RE = re.compile(
    r"^비용\s*[:：]\s*(?=체험\s*학습비|참가비|수강료|재료비|교재비|급식비|회비)",
    re.MULTILINE,
)


def preprocess_notice_text(text: str) -> str:
    """OCR 원문에서 서식 아티팩트 제거 — 번역 파이프라인 전 적용.

    제거 대상:
    - 기재란 밑줄(_____), 구분선(----- 단독 줄)
    - 점선 구분선(.....)
    - 빈 괄호((   ))
    - OX 체크박스 기호 (NLLB 오번역 유발)
    - 기호만으로 이루어진 구분선 줄
    - "네(동의) 아니오(동의하지 않음)" 한국어 YN 선택지 쌍
    - "신청함 신청하지 않음 불참사유" 신청 여부 표 헤더
    - "비용: 체험학습비:" 줄머리 이중 라벨 (번역 시 Chi phí: phí trải nghiệm: 방지)
    """
    text = _BLANK_UNDERSCORES.sub("", text)
    text = _BLANK_DASHES_LINE.sub("", text)
    text = _BLANK_DOTS_LINE.sub("", text)
    text = _SYMBOL_ONLY_LINE.sub("", text)
    text = _BLANK_PARENS.sub("", text)
    text = _OX_CHOICE_SYMBOLS.sub("", text)
    text = _COST_OUTER_LABEL_RE.sub("", text)    # "비용: 체험학습비:" → "체험학습비:"
    text = _KO_YN_CHOICE_RE.sub("", text)        # "네(동의) 아니오(동의하지 않음)" 제거
    text = _FORM_TABLE_HEADER_RE.sub("", text)   # 신청 여부 표 헤더 줄 제거
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 비용 문구 추출 (납부 vs 지원 분리) ──────────────────────────────
# 순수 금액 숫자 줄 — extract_amounts 가 이미 잡음
_PURE_AMOUNT_LINE = re.compile(r"^[\d,]+\s*(?:만|천|억)?\s*원$")

# 개인정보 동의·서명 문장 — 비용/지원 탭 모두 제외 (form artifact)
_CONSENT_RE = re.compile(
    r"개인\s*정보\s*(?:제공|수집|활용|처리|동의)"
    r"|상기\s*(?:의\s*)?내용을?\s*(?:확인|동의|읽고)"
    r"|이에\s*(?:동의|서명)"
    r"|동의\s*(?:서명|날인)"
    r"|위\s*내용에?\s*(?:동의|서명)"
)

# 학부모가 직접 납부·확인해야 하는 키워드
_COST_PAYMENT_RE = re.compile(
    r"스쿨뱅킹|자동이체|잔액|납부(?:기한|완료|대상|액)?|미납"
    r"|체험\s*학습비|참가비|재료비|교재비|급식비|회비|수강료"
)

# 학교·기관이 제공하는 지원 키워드 (학부모가 직접 납부 X)
_COST_SUPPORT_INFO_RE = re.compile(
    r"지원(?:\s*금)?|감면|보조|무료|무상"
)

# 전체 비용 관련 키워드 (1차 필터용)
_COST_ALL_RE = re.compile(
    r"지원(?:\s*금)?|보험료|스쿨뱅킹|자동이체|잔액"
    r"|감면|보조|무료|무상|체험\s*학습비|참가비|재료비"
    r"|교재비|급식비|납부|회비|수강료"
)


def extract_cost_sentences(text: str) -> list[str]:
    """납부·자동이체 등 학부모가 직접 처리해야 하는 비용 문구.

    '스쿨뱅킹 자동이체', '잔액 확인', '참가비 납부' 등.
    '버스 지원', '보험료 지원' 같은 학교 지원 안내는 extract_cost_support_info()로 분리.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        s = strip_markers(line).strip()
        if not s or len(s) > 80:
            continue
        if _PURE_AMOUNT_LINE.match(s):
            continue
        if not _COST_ALL_RE.search(s):
            continue
        # 개인정보 동의 문장은 form artifact — 비용 탭 제외
        if _CONSENT_RE.search(s):
            continue
        # 지원 키워드만 있고 납부 키워드 없으면 → support_info로 분리
        if _COST_SUPPORT_INFO_RE.search(s) and not _COST_PAYMENT_RE.search(s):
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def extract_cost_support_info(text: str) -> list[str]:
    """버스·보험료 지원 등 학교/기관이 제공하는 지원 안내 문구.

    '버스 1대 지원', '보험료 학교 지원', '지원사업 체험학습비 일부 지원' 등.
    학부모가 직접 납부하지 않는 항목 — cost 탭이 아닌 지원 안내로 분리.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        s = strip_markers(line).strip()
        if not s or len(s) > 80:
            continue
        if _PURE_AMOUNT_LINE.match(s):
            continue
        if not _COST_SUPPORT_INFO_RE.search(s):
            continue
        # 개인정보 동의 문장은 form artifact — 지원 안내 탭도 제외
        if _CONSENT_RE.search(s):
            continue
        # 납부 키워드가 같이 있으면 cost_sentences가 처리
        if _COST_PAYMENT_RE.search(s):
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ── 통합 진입점 ──────────────────────────────────────────────────
def extract_summary_regex_slots(text: str, target_lang: str) -> dict[str, list[dict]]:
    """summary 슬롯 중 정규식으로 채울 수 있는 항목들을 SlotEntry-ready dict로.

    urls/phones는 번역 안 거치고 ko 그대로 노출 (NLLB가 깨먹는 패턴 방어).
    """
    out: dict[str, list[dict]] = {
        "dates": [], "times": [], "amounts": [], "urls": [], "phones": [],
        "deadlines": [], "supplies": [], "cost_support": [], "cost_support_info": [],
    }
    for d in extract_dates(text):
        idx = text.find(d["ko"])
        is_deadline = False
        is_notice_date = False
        if idx >= 0:
            before = text[max(0, idx - 60) : idx]
            after = text[idx + len(d["ko"]) : idx + len(d["ko"]) + 60]
            # 날짜 뒤 60자 안에 "까지" / "마감" → 마감일 슬롯
            if "까지" in after[:30] or "마감" in after[:30]:
                is_deadline = True
            # 앞뒤 60자 안에 서명 문구(드림/올림/담임교사/교장직인) → 발송일 → 이벤트 슬롯 제외
            elif _NOTICE_SIGN_OFF.search(before) or _NOTICE_SIGN_OFF.search(after):
                is_notice_date = True
        if is_notice_date:
            continue
        target_key = "deadlines" if is_deadline else "dates"
        out[target_key].append({
            "ko": d["ko"],
            "translated": format_date(d, target_lang),
            "source": "regex",
        })
    for t in extract_times(text):
        out["times"].append({
            "ko": t["ko"],
            "translated": format_time(t, target_lang),
            "source": "regex",
        })
    for a in extract_amounts(text):
        out["amounts"].append({
            "ko": a["ko"],
            "translated": format_amount(a, target_lang),
            "source": "regex",
        })
    for url in extract_urls(text):
        out["urls"].append({"ko": url, "translated": url, "source": "regex"})
    for phone in extract_phones(text):
        out["phones"].append({"ko": phone, "translated": phone, "source": "regex"})
    for s in extract_supplies(text):
        # 번역은 _build_cards_from_regex_slots 에서 한 번에 처리되도록 placeholder
        out["supplies"].append({"ko": s, "translated": "", "source": "regex"})
    for s in extract_cost_sentences(text):
        out["cost_support"].append({"ko": s, "translated": "", "source": "regex"})
    for s in extract_cost_support_info(text):
        out["cost_support_info"].append({"ko": s, "translated": "", "source": "regex"})
    return out


def find_when_in_text(text: str, target_lang: str) -> str | None:
    """item.when 용 — 텍스트에서 첫 날짜 + 시간 조합."""
    dates = extract_dates(text)
    times = extract_times(text)
    parts: list[str] = []
    if dates:
        parts.append(format_date(dates[0], target_lang))
    if times:
        parts.append(format_time(times[0], target_lang))
    return " ".join(parts) if parts else None


def find_amount_in_text(text: str, target_lang: str) -> str | None:
    """item.amount 용 — 텍스트의 첫 금액(원문 ko 그대로 반환, 안드 표시는 summary 통해 i18n)."""
    amounts = extract_amounts(text)
    return amounts[0]["ko"] if amounts else None


def find_deadline_in_text(text: str) -> str | None:
    """item.deadline 용 — '까지'가 들어간 첫 어구의 ko 표면형."""
    phrases = extract_deadline_phrases(text)
    return phrases[0] if phrases else None


# ── 준비물 리스트 분해 ────────────────────────────────────────────
# "도시락, 물통, 돗자리, 편한 운동화, 여벌 옷" → 5개 토큰
_LIST_SEP = re.compile(r"[,，、·/]\s*|\s*(?:과|와|및)\s+")


def split_supply_tokens(text: str) -> list[str]:
    """카테고리=준비물 todo의 텍스트에서 항목 토큰 분리.

    안내 문구('준비물:', '준비해 주세요' 등)는 제거 후 분리.
    """
    cleaned = re.sub(r"준비물\s*[:：]?\s*", "", text)
    cleaned = re.sub(r"(을|를)?\s*(준비해|챙겨|가져).*$", "", cleaned)
    tokens = [t.strip() for t in _LIST_SEP.split(cleaned) if t and t.strip()]
    return [t for t in tokens if 1 < len(t) < 30]
