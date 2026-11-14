import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.calendar import calculation, ical


def explosive(recurrence="FREQ=SECONDLY;COUNT=5000"):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:explosive\r\n"
            "DTSTART:20260907T000000Z\r\nDTEND:20260907T000001Z\r\nRRULE:" + recurrence +
            "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def test_expansion_stops_before_converting_more_than_1000_occurrences(monkeypatch):
    from recurring_ical_events.occurrence import Occurrence
    converted = 0
    original = Occurrence.as_component

    def convert(self, *args, **kwargs):
        nonlocal converted
        converted += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Occurrence, "as_component", convert)
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="1000"):
        ical.events_between(explosive(), start, start + timedelta(seconds=5000))
    assert converted <= 1000


@pytest.mark.asyncio
async def test_isolated_calculation_preserves_loop_and_valid_recurrence():
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    beat = asyncio.create_task(heartbeat())
    try:
        with pytest.raises(ValueError):
            await calculation.events_between(explosive(), start, start + timedelta(hours=2))
        events = await calculation.events_between(explosive("FREQ=DAILY;COUNT=2"), start, start + timedelta(days=3))
        assert len(events) == 2 and ticks > 2
    finally:
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_projection_stops_its_other_worker_and_does_not_publish_partial_coverage(db, agent, personal, monkeypatch):
    import sys
    from sqlalchemy import func, select
    from app.calendar import store
    from app.calendar.models import CalendarProjectionWindow
    from app.calendar.tests.test_volume import synthetic_calendar

    _, feed = personal
    content = synthetic_calendar(20, dense=True).replace(b'END:VEVENT', b'RRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT')
    content = content.replace(b'RRULE:FREQ=DAILY;COUNT=3', b'RRULE:FREQ=SECONDLY;COUNT=5000', 1)
    rows = await store.import_new_resources(feed, ical.split_resources(content))
    processes = []
    original = asyncio.create_subprocess_exec
    launches = 0
    async def launch(*args, **kwargs):
        nonlocal launches
        launches += 1
        # The second real process stays alive until cancellation kills it.
        command = args if launches == 1 else (sys.executable, '-c', 'import time; time.sleep(30)')
        process = await original(*command, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launch)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(calculation.CalendarCalculationError):
        await store.project_events(feed, rows, agent_id=agent.id, start=start, end=start + timedelta(days=1), reschedule=False)
    assert len(processes) == 2 and all(process.returncode is not None for process in processes)
    assert await db.scalar(select(func.count()).select_from(CalendarProjectionWindow)) == 0
