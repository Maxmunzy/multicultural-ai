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
_DATE_RELATIVE = ["내일", "모레", "오늘", "다음 주", "다음주", "이번 주", "이번주"]

_TIME_AMPM = re.compile(
    r"(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2})\s*시(?:\s*(?P<minute>\d{1,2})\s*분)?"
)
_TIME_24H = re.compile(r"(?<!\d)(?P<hour>\d{1,2}):(?P<minute>\d{2})(?!\d)")

_AMOUNT_KRW = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)\s*원")
_AMOUNT_KO = re.compile(r"(?P<num>\d+)\s*(?P<unit>만|천|억)\s*원")

# 까지 마감 표현: "5월 9일까지", "내일까지", "5월 9일(금)까지 ... 제출"
_DEADLINE_PHRASE = re.compile(r"([^.,\n]*?까지[^.,\n]*?)(?=[.,\n]|$)")


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
        ko = m.group(0).strip()
        if ko in seen:
            continue
        seen.add(ko)
        out.append({
            "ko": ko,
            "hour": int(m.group("hour")),
            "minute": int(m.group("minute")),
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
    """'까지'가 들어간 어구를 한 문장 단위로 추출."""
    return [m.group(1).strip() for m in _DEADLINE_PHRASE.finditer(text)]


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


# ── 통합 진입점 ──────────────────────────────────────────────────
def extract_summary_regex_slots(text: str, target_lang: str) -> dict[str, list[dict]]:
    """summary 슬롯 중 정규식으로 채울 수 있는 dates/times/amounts를 SlotEntry-ready dict로."""
    out = {"dates": [], "times": [], "amounts": []}
    for d in extract_dates(text):
        out["dates"].append({
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
_LIST_SEP = re.compile(r"[,，、]\s*|\s*(?:과|와|및)\s+")


def split_supply_tokens(text: str) -> list[str]:
    """카테고리=준비물 todo의 텍스트에서 항목 토큰 분리.

    안내 문구('준비물:', '준비해 주세요' 등)는 제거 후 분리.
    """
    cleaned = re.sub(r"준비물\s*[:：]?\s*", "", text)
    cleaned = re.sub(r"(을|를)?\s*(준비해|챙겨|가져).*$", "", cleaned)
    tokens = [t.strip() for t in _LIST_SEP.split(cleaned) if t and t.strip()]
    return [t for t in tokens if 1 < len(t) < 30]
