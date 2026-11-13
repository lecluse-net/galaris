"""Pure RFC 5545 recurrence, alarm and mutation contracts."""

from datetime import datetime, timezone, timedelta

from app.calendar import ical
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate


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
    )

    assert [event.start.hour for event in events] == [10, 10]
    assert ical.master_event(CALENDAR, 'Europe/Paris').timezone_name == 'UTC'
    assert [(action.kind, action.occurrence_at.hour, action.occurrence_at.minute) for action in actions] == [
        ("alarm", 9, 45),
        ("alarm", 9, 45),
    ]
    assert len({action.fingerprint for action in actions}) == 2
    without_alarm = CALENDAR.replace(CALENDAR[CALENDAR.index(b"BEGIN:VALARM"):CALENDAR.index(b"END:VALARM") + len(b"END:VALARM\r\n")], b"")
    assert ical.due_actions(without_alarm, start, end) == []


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

    updated = ical.update_event(created, uid, CalendarEventUpdate(expected_revision=1, summary="Updated planning"))
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


def test_cancelled_events_do_not_produce_actions_and_all_day_dates_are_exclusive():
    from datetime import date
    cancelled = CALENDAR.replace(b'SUMMARY:Daily stand-up', b'STATUS:CANCELLED\r\nSUMMARY:Daily stand-up')
    assert ical.due_actions(cancelled, datetime(2026,8,22,9,tzinfo=timezone.utc), datetime(2026,8,22,10,tzinfo=timezone.utc)) == []
    source, uid = ical.create_event(ical.EMPTY_CALENDAR, CalendarEventCreate(summary='Synthetic all-day',
        start=date(2026,10,25), end=date(2026,10,26), timezone='Europe/Paris'))
    event = ical.master_event(source, 'Europe/Paris')
    assert event.start_date == date(2026,10,25) and event.end_date == date(2026,10,26)
    assert event.end - event.start == timedelta(hours=25)


def test_named_timezone_recurrence_keeps_local_time_across_daylight_saving():
    source, uid = ical.create_event(ical.EMPTY_CALENDAR, CalendarEventCreate(summary='Synthetic DST series',
        start=datetime.fromisoformat('2026-03-28T09:00:00+01:00'), end=datetime.fromisoformat('2026-03-28T10:00:00+01:00'),
        timezone='Europe/Paris', rrule='FREQ=DAILY;COUNT=3'))
    events = ical.events_between(source, datetime(2026,3,27,tzinfo=timezone.utc), datetime(2026,3,31,tzinfo=timezone.utc))
    assert [row.start.hour for row in events] == [8,7,7]
    assert all(row.timezone_name == 'Europe/Paris' for row in events)


def test_alarm_reordering_preserves_identities_and_resource_hash_matches_split_definition():
    second = b'BEGIN:VALARM\r\nTRIGGER:-PT30M\r\nACTION:DISPLAY\r\nDESCRIPTION:Another synthetic reminder\r\nEND:VALARM\r\n'
    original = CALENDAR.replace(b'END:VEVENT', second + b'END:VEVENT')
    first = original[original.index(b'BEGIN:VALARM'):original.index(b'END:VALARM')+len(b'END:VALARM\r\n')]
    reordered = original.replace(first,b'').replace(b'END:VEVENT',first+b'END:VEVENT')
    lower,upper = datetime(2026,8,22,tzinfo=timezone.utc),datetime(2026,8,23,tzinfo=timezone.utc)
    assert {row.key for row in ical.events_between(original,lower,upper)[0].alarms} == {row.key for row in ical.events_between(reordered,lower,upper)[0].alarms}
    assert ical.split_resources(original)[0].digest == ical.resource_digest(original)
