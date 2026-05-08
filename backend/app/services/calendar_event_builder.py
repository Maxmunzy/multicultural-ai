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
    "fee": ("payment_deadline", "납부/비용", "red"),
}

HOLIDAY_HINTS = ("공휴일", "휴업", "재량휴업", "기념일", "어린이날", "스승의 날")


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


def build_calendar_events_from_sentence_document(
    document: SentenceListDocument,
    *,
    notice_id: str = "",
    title: str = "",
) -> list[CalendarEvent]:
    """Build calendar events from hard-fact sentence-list items."""
    texts = [item.text for item in document.sentence_list]
    default_year, default_month = _base_year_month(texts)
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
        events.append(CalendarEvent(
            event_id=f"{notice_id or 'notice'}_{item.sentence_id}_{len(events) + 1}",
            notice_id=notice_id,
            title=title or document.document_title,
            type=event_type,
            label=label,
            start_date=start_date,
            end_date=end_date,
            time=_extract_time(item.text),
            display_text=item.text.strip(),
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
