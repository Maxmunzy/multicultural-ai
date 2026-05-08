from app.services.calendar_event_builder import build_calendar_events_from_sentence_document
from app.services.sentence_skeleton import SentenceListDocument, SentenceListItem


def _item(sentence_id: str, text: str, role_hint: str, order: int) -> SentenceListItem:
    return SentenceListItem(
        sentence_id=sentence_id,
        text=text,
        role_hint=role_hint,
        source_order=order,
        contains_slots=["date"],
    )


def test_build_calendar_events_period_and_one_day():
    doc = SentenceListDocument(
        document_title="토요프로그램 안내",
        sentence_list=[
            _item("s1", "신청기간: 2026. 4. 21.(화) 10:00 ~ 4. 24.(금) 24:00", "application_period", 1),
            _item("s2", "운영일시: 2026. 5. 9.(토) 10:00 ~ 12:00", "event_datetime", 2),
        ],
    )

    events = build_calendar_events_from_sentence_document(doc, notice_id="n1", title="토요프로그램")

    assert len(events) == 2
    assert events[0].type == "application_period"
    assert events[0].start_date == "2026-04-21"
    assert events[0].end_date == "2026-04-24"
    assert events[0].color == "blue"
    assert events[1].type == "event_datetime"
    assert events[1].start_date == "2026-05-09"
    assert events[1].end_date == "2026-05-09"
    assert events[1].color == "green"


def test_build_calendar_events_holiday_uses_red():
    doc = SentenceListDocument(
        document_title="재량휴업일 안내",
        sentence_list=[
            _item("s1", "재량휴업일: 2026년 5월 6일", "etc", 1),
        ],
    )

    events = build_calendar_events_from_sentence_document(doc, notice_id="n2")

    assert len(events) == 1
    assert events[0].type == "holiday"
    assert events[0].color == "red"
    assert events[0].start_date == "2026-05-06"


def test_calendar_event_url_actions():
    doc = SentenceListDocument(
        sentence_list=[
            _item("s1", "신청기간: 2026. 4. 21. ~ 4. 24. https://example.com/apply", "application_period", 1),
        ],
    )

    event = build_calendar_events_from_sentence_document(doc, notice_id="n3")[0]

    action_types = [action.type for action in event.actions]
    assert action_types == ["open_url"]
    assert event.actions[0].value == "https://example.com/apply"


def test_calendar_event_january_after_december_notice_uses_next_year():
    doc = SentenceListDocument(
        document_title="겨울방학 프로그램 안내",
        sentence_list=[
            SentenceListItem(
                sentence_id="s0",
                text="발송일: 2025. 12. 20.",
                role_hint="info",
                source_order=0,
                contains_slots=[],
            ),
            _item("s1", "운영일시: 1. 15. 10:00 ~ 12:00", "event_datetime", 1),
        ],
    )

    events = build_calendar_events_from_sentence_document(doc, notice_id="n4")

    assert len(events) == 1
    assert events[0].start_date == "2026-01-15"
