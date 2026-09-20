"""Pure RFC 5545 recurrence, alarm and mutation contracts."""

from datetime import datetime, timezone

from bridge.calendar import ical
from bridge.calendar.schemas import CalendarEventCreate, CalendarEventUpdate


CALENDAR = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Galaris Tests//EN\r
BEGIN:VEVENT\r
UID:standup@example.test\r
DTSTAMP:20260820T080000Z\r
DTSTART:20260822T100000Z\r
DTEND:20260822T103000Z\r
RRULE:FREQ=DAILY;COUNT=2\r
SUMMARY:Daily stand-up\r
DESCRIPTION:External description\r
LOCATION:Room 1\r
BEGIN:VALARM\r
TRIGGER:-PT15M\r
ACTION:DISPLAY\r
DESCRIPTION:Reminder\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_recurring_events_and_alarm_are_expanded() -> None:
    start = datetime(2026, 8, 22, 9, 40, tzinfo=timezone.utc)
    end = datetime(2026, 8, 23, 10, 5, tzinfo=timezone.utc)

    events = ical.events_between(CALENDAR, start, end)
    actions = ical.due_actions(
        CALENDAR,
        start,
        end,
        trigger_on_start=True,
        trigger_on_alarm=True,
    )

    assert [event.start.hour for event in events] == [10, 10]
    assert [(action.kind, action.occurrence_at.hour, action.occurrence_at.minute) for action in actions] == [
        ("alarm", 9, 45),
        ("start", 10, 0),
        ("alarm", 9, 45),
        ("start", 10, 0),
    ]
    assert len({action.fingerprint for action in actions}) == 4


def test_create_update_and_delete_event_round_trip() -> None:
    created, uid = ical.create_event(
        CALENDAR,
        CalendarEventCreate(
            summary="Planning",
            start=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            end=datetime(2026, 8, 24, 13, tzinfo=timezone.utc),
        ),
    )
    events = ical.events_between(
        created,
        datetime(2026, 8, 24, tzinfo=timezone.utc),
        datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert [(event.uid, event.summary) for event in events] == [(uid, "Planning")]

    updated = ical.update_event(created, uid, CalendarEventUpdate(summary="Updated planning"))
    events = ical.events_between(
        updated,
        datetime(2026, 8, 24, tzinfo=timezone.utc),
        datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert events[0].summary == "Updated planning"

    deleted = ical.delete_event(updated, uid)
    assert not ical.events_between(
        deleted,
        datetime(2026, 8, 24, tzinfo=timezone.utc),
        datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
