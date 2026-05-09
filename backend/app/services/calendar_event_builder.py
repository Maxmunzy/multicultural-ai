"""Build mini-calendar events from preserved sentence-list slots.

The calendar is a UX layer over slot preservation: dates are not just text to
translate, but action reminders that can be shown as bars/dots in Android.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from app.models.schemas import CalendarAction, CalendarEvent
from app.services.sentence_skeleton import SentenceListDocument, SentenceListItem


FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*(?:[.\-/년])\s*"
    r"(?P<month>\d{1,2})\s*(?:[.\-/월])\s*"
    r"(?P<day>\d{1,2})"
)
MD_DOT_RE = re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*\.\s*(?P<day>\d{1,2})\s*\.?")
MD_KO_RE = re.compile(r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일")
TIME_RE = re.compile(
    r"(?P<start>(?:[01]?\d|2[0-4]):[0-5]\d)"
    r"(?:\s*[~\-]\s*(?P<end>(?:[01]?\d|2[0-4]):[0-5]\d))?"
)
URL_RE = re.compile(r"https?://[^\s\])}>,]+|www\.[^\s\])}>,]+", re.IGNORECASE)


ROLE_EVENT_TYPE: dict[str, tuple[str, str, str]] = {
    "application_period": ("application_period", "신청기간", "blue"),
    "event_datetime": ("event_datetime", "운영일시", "green"),
    "result_announcement": ("result_announcement", "결과발표", "purple"),
    "submit": ("submit_deadline", "제출", "orange"),
    "fee": ("payment_deadline", "납부/비용", "gold"),
}

HOLIDAY_HINTS = ("공휴일", "휴업", "재량휴업", "기념일", "어린이날", "스승의 날")

# 일반 안내문 표현 — content_hint에서 제외 (display_text 오염 방지)
_GENERIC_NOTICE_RE = re.compile(
    r"드릴\s*말씀|아래와\s*같이|계획하여\s*운영|실시할\s*예정"
    r"|참고하시어|안전하고\s*즐거운|교육과정\s*운영"
    r"|보고\s*교육과정|이에\s*안내|와\s*같이\s*운영"
)

# 2026년 공휴일/기념일 static map.
# TODO: 서비스 전환 시 공공데이터포털 특일정보 API(data.go.kr) 또는
#       연도별 holiday table로 대체. 음력 공휴일(설날·추석)은 매년 날짜가 달라지므로
#       연도별 선제 갱신 필요.
KOREAN_HOLIDAYS_2026: dict[str, str] = {
    "2026-01-01": "신정",
    "2026-02-16": "설날 연휴",
    "2026-02-17": "설날",
    "2026-02-18": "설날 연휴",
    "2026-03-01": "삼일절",
    "2026-05-05": "어린이날",
    "2026-06-06": "현충일",
    "2026-08-15": "광복절",
    "2026-09-24": "추석 연휴",
    "2026-09-25": "추석",
    "2026-09-26": "추석 연휴",
    "2026-10-03": "개천절",
    "2026-10-09": "한글날",
    "2026-12-25": "성탄절",
}

_HOLIDAY_MAP_BY_YEAR: dict[int, dict[str, str]] = {
    2026: KOREAN_HOLIDAYS_2026,
}


def build_holiday_events(year: int) -> list[CalendarEvent]:
    """Static 공휴일 CalendarEvent 목록 반환. 미지원 연도는 빈 리스트."""
    holidays = _HOLIDAY_MAP_BY_YEAR.get(year, {})
    events: list[CalendarEvent] = []
    for iso, name in holidays.items():
        events.append(CalendarEvent(
            event_id=f"holiday_{iso}",
            notice_id="",
            title=name,
            type="holiday",
            label="휴업/기념일",
            start_date=iso,
            end_date=iso,
            time=None,
            display_text=name,
            color="red",
            source_text=name,
            translated="",
            actions=[],
        ))
    return events


def _base_year_month(texts: Iterable[str]) -> tuple[int, int | None]:
    for text in texts:
        match = FULL_DATE_RE.search(text or "")
        if match:
            return int(match.group("year")), int(match.group("month"))
    return date.today().year, None


def _resolve_year(default_year: int, default_month: int | None, month: int) -> int:
    """Infer next-year dates for winter notices that mention January/February."""
    if default_month in (10, 11, 12) and month in (1, 2):
        return default_year + 1
    return default_year


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_dates(text: str, default_year: int, default_month: int | None = None) -> list[str]:
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in FULL_DATE_RE.finditer(text or ""):
        iso = _iso(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        if iso and iso not in found:
            found.append(iso)
            occupied.append(match.span())

    def overlaps(span: tuple[int, int]) -> bool:
        return any(not (span[1] <= a or span[0] >= b) for a, b in occupied)

    for pattern in (MD_KO_RE, MD_DOT_RE):
        for match in pattern.finditer(text or ""):
            if overlaps(match.span()):
                continue
            month = int(match.group("month"))
            year = _resolve_year(default_year, default_month, month)
            iso = _iso(year, month, int(match.group("day")))
            if iso and iso not in found:
                found.append(iso)
    return found


def _extract_time(text: str) -> str | None:
    match = TIME_RE.search(text or "")
    if not match:
        return None
    start = match.group("start")
    end = match.group("end")
    return f"{start}~{end}" if end else start


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(text or ""):
        url = match.group().rstrip(".,)]}")
        if url.startswith("www."):
            url = "https://" + url
        if url not in urls:
            urls.append(url)
    return urls


def _event_meta(item: SentenceListItem) -> tuple[str, str, str] | None:
    text = item.text or ""
    if any(hint in text for hint in HOLIDAY_HINTS):
        return "holiday", "휴업/기념일", "red"
    if item.role_hint in ROLE_EVENT_TYPE:
        return ROLE_EVENT_TYPE[item.role_hint]
    if "deadline" in item.contains_slots or "date" in item.contains_slots:
        return "school_event", "일정", "gray"
    return None


def _actions(urls: list[str], start_date: str) -> list[CalendarAction]:
    actions: list[CalendarAction] = []
    if urls:
        actions.append(CalendarAction(type="open_url", label="바로가기", value=urls[0]))
    return actions


def _extract_header_value(text: str) -> str:
    """'헤더: 값' 형태에서 값 부분 반환. 구분자 없으면 text 그대로."""
    for sep in ("：", ":"):
        if sep in text:
            parts = text.split(sep, 1)
            val = parts[1].strip()
            if val:
                return val
    return text.strip()


def build_calendar_events_from_sentence_document(
    document: SentenceListDocument,
    *,
    notice_id: str = "",
    title: str = "",
) -> list[CalendarEvent]:
    """Build calendar events from hard-fact sentence-list items."""
    texts = [item.text for item in document.sentence_list]
    default_year, default_month = _base_year_month(texts)

    # 장소·활동 내용 수집 — display_text 보강용 (학부모가 "무슨 행사인지" 알 수 있게)
    place_items = [
        item for item in document.sentence_list if item.role_hint == "location"
    ]
    content_items = [
        item for item in document.sentence_list
        if item.role_hint in ("content", "program_title")
    ]
    place_hint = _extract_header_value(place_items[0].text) if place_items else ""
    # 일반 안내문 아닌 첫 번째 content 항목만 사용 — "드릴 말씀은...", "아래와 같이..." 필터
    content_hint = ""
    for _ci in content_items:
        _val = _extract_header_value(_ci.text)
        if not _GENERIC_NOTICE_RE.search(_val):
            content_hint = _val
            break

    doc_title = title or document.document_title
    events: list[CalendarEvent] = []

    for item in sorted(document.sentence_list, key=lambda x: x.source_order):
        meta = _event_meta(item)
        if not meta:
            continue
        dates = _extract_dates(item.text, default_year, default_month)
        if not dates:
            continue
        event_type, label, color = meta
        is_period = event_type.endswith("_period") or "기간" in item.text
        start_date = dates[0]
        end_date = dates[1] if is_period and len(dates) > 1 else start_date
        urls = _extract_urls(item.text)

        # display_text: 원문 + 장소·활동 보강 (달력 상세 모달에서 행사 맥락 표시)
        display = item.text.strip()
        if place_hint and place_hint not in display:
            display += f"\n장소: {place_hint}"
        if content_hint and content_hint not in display:
            display += f"\n활동: {content_hint}"

        events.append(CalendarEvent(
            event_id=f"{notice_id or 'notice'}_{item.sentence_id}_{len(events) + 1}",
            notice_id=notice_id,
            title=doc_title,
            type=event_type,
            label=label,
            start_date=start_date,
            end_date=end_date,
            time=_extract_time(item.text),
            display_text=display,
            color=color,
            source_text=item.text.strip(),
            translated="",
            actions=_actions(urls, start_date),
        ))

    return _dedup_events(events)


def _dedup_events(events: list[CalendarEvent]) -> list[CalendarEvent]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[CalendarEvent] = []
    for event in events:
        key = (event.type, event.start_date, event.end_date or "", event.display_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


def merge_with_holidays(events: list[CalendarEvent], year: int) -> list[CalendarEvent]:
    """문서 이벤트에 해당 연도 공휴일을 merge해서 반환.

    build_calendar_events_from_sentence_document 는 순수하게 문서 슬롯만 반환.
    호출부(notice.py)에서 이 함수를 통해 공휴일을 명시적으로 합친다.
    """
    return _dedup_events(events + build_holiday_events(year))
