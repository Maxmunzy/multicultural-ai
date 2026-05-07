"""OCR slot correction helpers for high-value school notice fields.

The goal is not to replace OCR.  We only correct confusable characters inside
restricted slot contexts such as amounts, times, dates, grades, and phone
numbers.  This keeps broad OCR text intact while protecting information that
can directly affect a parent's action.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import re


@dataclass(frozen=True)
class OcrSlotCorrection:
    slot_type: str
    raw_text: str
    corrected_text: str
    reason: str
    start: int
    end: int
    review_required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


_DIGIT_CONFUSABLE = str.maketrans({
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
    "S": "5",
    "s": "5",
    "B": "8",
})

_WEEKDAY_CONFUSABLE = {
    "묵": "목",
    "귬": "금",
}

_AMOUNT_PATTERN = re.compile(
    r"(?P<num>[0-9OoIl|SsB][0-9OoIl|SsB,.]{1,})\s*(?P<unit>원|완)"
)
_TIME_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?P<hour>[0-9OoIl|]{1,2})\s*:\s*(?P<minute>[0-9OoIl|Ss]{2})(?![0-9A-Za-z])"
)
_DATE_MONTH_PATTERN = re.compile(
    r"(?P<month>[0-9OoIl|]{1,2})\s*(?P<month_unit>월|원)\s*"
    r"(?P<day>[0-9OoIl|]{1,2})\s*일"
)
_WEEKDAY_PATTERN = re.compile(r"\((?P<wday>[월화수목묵금귬토일])\)")
_GRADE_PATTERN = re.compile(
    r"(?P<start>[0-9OoIl|]{1,2})\s*(?:[-~]\s*(?P<end>[0-9OoIl|]{1,2}))?\s*"
    r"(?P<grade_unit>학|확)\s*년"
)
_CLASS_PATTERN = re.compile(r"(?P<num>[0-9OoIl|]{1,2})\s*(?P<class_unit>반|밤)")
_PHONE_PATTERN = re.compile(
    r"(?<![\w])(?P<phone>[0-9OoIl|Ss]{2,4}(?:-[0-9OoIl|Ss]{3,4}){1,2})(?![\w])"
)


def _digits(value: str) -> str:
    return value.translate(_DIGIT_CONFUSABLE)


def _normalize_amount_number(value: str) -> str:
    normalized = _digits(value).replace(".", ",")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _valid_time(hour: str, minute: str) -> bool:
    try:
        h = int(hour)
        m = int(minute)
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def _valid_month_day(month: str, day: str) -> bool:
    try:
        m = int(month)
        d = int(day)
    except ValueError:
        return False
    if not 1 <= m <= 12:
        return False
    # Lightweight validation is enough here; exact month length can be a later
    # layer if the year is known.
    return 1 <= d <= 31


def _append_if_changed(
    corrections: list[OcrSlotCorrection],
    *,
    slot_type: str,
    raw_text: str,
    corrected_text: str,
    reason: str,
    start: int,
    end: int,
    review_required: bool = False,
) -> None:
    if raw_text == corrected_text:
        return
    corrections.append(OcrSlotCorrection(
        slot_type=slot_type,
        raw_text=raw_text,
        corrected_text=corrected_text,
        reason=reason,
        start=start,
        end=end,
        review_required=review_required,
    ))


def find_ocr_slot_corrections(text: str) -> list[OcrSlotCorrection]:
    """Find safe OCR corrections inside high-value slot contexts."""
    corrections: list[OcrSlotCorrection] = []

    for m in _AMOUNT_PATTERN.finditer(text):
        raw = m.group(0)
        number = _normalize_amount_number(m.group("num"))
        # Avoid correcting unrelated fragments that only contain commas/spaces.
        if not re.search(r"\d", number):
            continue
        corrected = f"{number}원"
        _append_if_changed(
            corrections,
            slot_type="amount",
            raw_text=raw,
            corrected_text=corrected,
            reason="amount slot: digit/unit confusable correction",
            start=m.start(),
            end=m.end(),
        )

    for m in _TIME_PATTERN.finditer(text):
        raw = m.group(0)
        hour = _digits(m.group("hour"))
        minute = _digits(m.group("minute"))
        corrected = f"{hour}:{minute}"
        _append_if_changed(
            corrections,
            slot_type="time",
            raw_text=raw,
            corrected_text=corrected,
            reason="time slot: digit confusable correction",
            start=m.start(),
            end=m.end(),
            review_required=not _valid_time(hour, minute),
        )

    for m in _DATE_MONTH_PATTERN.finditer(text):
        raw = m.group(0)
        month = _digits(m.group("month"))
        day = _digits(m.group("day"))
        corrected = f"{month}월 {day}일"
        _append_if_changed(
            corrections,
            slot_type="date",
            raw_text=raw,
            corrected_text=corrected,
            reason="date slot: month/day confusable correction",
            start=m.start(),
            end=m.end(),
            review_required=not _valid_month_day(month, day),
        )

    for m in _WEEKDAY_PATTERN.finditer(text):
        raw = m.group(0)
        wday = m.group("wday")
        corrected_wday = _WEEKDAY_CONFUSABLE.get(wday, wday)
        _append_if_changed(
            corrections,
            slot_type="weekday",
            raw_text=raw,
            corrected_text=f"({corrected_wday})",
            reason="weekday slot: Hangul confusable correction",
            start=m.start(),
            end=m.end(),
        )

    for m in _GRADE_PATTERN.finditer(text):
        raw = m.group(0)
        start_grade = _digits(m.group("start"))
        end_grade = _digits(m.group("end")) if m.group("end") else None
        if end_grade:
            corrected = f"{start_grade}-{end_grade}학년"
        else:
            corrected = f"{start_grade}학년"
        _append_if_changed(
            corrections,
            slot_type="grade",
            raw_text=raw,
            corrected_text=corrected,
            reason="grade slot: digit/unit confusable correction",
            start=m.start(),
            end=m.end(),
        )

    for m in _CLASS_PATTERN.finditer(text):
        raw = m.group(0)
        corrected = f"{_digits(m.group('num'))}반"
        _append_if_changed(
            corrections,
            slot_type="class",
            raw_text=raw,
            corrected_text=corrected,
            reason="class slot: digit/unit confusable correction",
            start=m.start(),
            end=m.end(),
        )

    for m in _PHONE_PATTERN.finditer(text):
        raw = m.group(0)
        corrected = _digits(raw)
        _append_if_changed(
            corrections,
            slot_type="phone",
            raw_text=raw,
            corrected_text=corrected,
            reason="phone slot: digit confusable correction",
            start=m.start(),
            end=m.end(),
        )

    return sorted(corrections, key=lambda c: (c.start, c.end))


def apply_ocr_slot_corrections(text: str) -> tuple[str, list[dict]]:
    """Apply non-overlapping OCR slot corrections and return audit metadata."""
    corrections = find_ocr_slot_corrections(text)
    if not corrections:
        return text, []

    pieces: list[str] = []
    last = 0
    applied: list[OcrSlotCorrection] = []
    for correction in corrections:
        if correction.start < last:
            continue
        pieces.append(text[last:correction.start])
        pieces.append(correction.corrected_text)
        last = correction.end
        applied.append(correction)
    pieces.append(text[last:])

    return "".join(pieces), [c.to_dict() for c in applied]
