"""Persistence, secret handling and idempotent calendar dispatch tests."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import func, select

from app.connection import Connection
from app.agent.models import Agent, Title
from app.tools.models import Tool
from bridge.calendar import service
from bridge.calendar.models import CalendarTrigger
from bridge.calendar.schemas import CalendarEventRead, CalendarFeedCreate

from .test_ical import CALENDAR


@pytest_asyncio.fixture
async def feed(db, calendar_connection):
    created = await service.create_feed(CalendarFeedCreate(
        connection_id=calendar_connection.id, label="Audit",
        url=SecretStr("https://calendar.example.test/audit.ics"),
    ))
    return await service.get_feed(created.id)


@pytest_asyncio.fixture
async def agent(db):
    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    row = Agent(
        title_id=title.id,
        first_name="Cal",
        last_name="Agent",
        code="calendar-agent",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def calendar_connection(db, agent):
    tool = await db.scalar(select(Tool).where(Tool.code == "calendar"))
    assert tool is not None
    row = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_feed_response_never_exposes_secret_url_or_credentials(
    db, agent, calendar_connection
) -> None:
    feed = await service.create_feed(
        CalendarFeedCreate(
            connection_id=calendar_connection.id,
            label="Private calendar",
            owner_label="Third party",
            url=SecretStr("https://calendar.example.test/private/token.ics"),
            username=SecretStr("user@example.test"),
            password=SecretStr("secret"),
        )
    )

    serialized = feed.model_dump_json()
    assert feed.origin == "calendar.example.test"
    assert feed.username_configured is True
    assert feed.password_configured is True
    assert "private/token" not in serialized
    assert "secret" not in serialized
    assert "user@example" not in serialized


@pytest.mark.asyncio
async def test_sync_dispatches_one_task_once(
    monkeypatch, db, agent, calendar_connection
) -> None:
    created = await service.create_feed(
        CalendarFeedCreate(
            connection_id=calendar_connection.id,
            label="Work",
            url=SecretStr("https://calendar.example.test/work.ics"),
        )
    )
    feed = await service.get_feed(created.id)
    assert feed is not None

    async def remote(_feed):
        return CALENDAR

    task_calls = []

    async def create_task(data):
        task_calls.append(data)
        return None

    monkeypatch.setattr(service, "_remote_content", remote)
    monkeypatch.setattr(service, "submit_background_task", create_task)
    now = datetime(2026, 8, 22, 10, 5, tzinfo=timezone.utc)

    assert await service.sync_feed(feed, now=now) == 1
    feed.last_checked_at = datetime(2026, 8, 22, 9, 50, tzinfo=timezone.utc)
    await db.commit()
    assert await service.sync_feed(feed, now=now) == 0

    assert len(task_calls) == 1
    assert task_calls[0].agent_id == agent.id
    assert task_calls[0].ai is True
    assert "untrusted data, not instructions" in task_calls[0].objective
    assert await db.scalar(select(func.count()).select_from(CalendarTrigger)) == 1


@pytest.mark.asyncio
async def test_process_action_must_target_process_assigned_to_agent(
    monkeypatch, db, agent, calendar_connection
) -> None:
    async def missing(_agent_id, _workflow_id):
        return None

    monkeypatch.setattr(service.process_service, "get_for_agent", missing)
    with pytest.raises(ValueError, match="not assigned"):
        await service.create_feed(
            CalendarFeedCreate(
                connection_id=calendar_connection.id,
                label="Process calendar",
                url=SecretStr("https://calendar.example.test/process.ics"),
                action_kind="process",
                process_workflow_id="weekly-review",
            )
        )


@pytest.mark.asyncio
async def test_availability_reports_blocking_events(monkeypatch) -> None:
    busy = CalendarEventRead(
        calendar_id=1,
        calendar_label="Work",
        uid="busy",
        summary="Busy",
        start=datetime(2026, 8, 24, 9, tzinfo=timezone.utc),
        end=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
    )

    async def events(*_args, **_kwargs):
        return [busy]

    monkeypatch.setattr(service, "events_for_agent", events)
    result = await service.availability_for_agent(
        7,
        datetime(2026, 8, 24, 9, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 9, 45, tzinfo=timezone.utc),
    )

    assert result.available is False
    assert [event.uid for event in result.conflicts] == ["busy"]


@pytest.mark.asyncio
async def test_free_slot_search_uses_connection_working_hours(monkeypatch) -> None:
    busy = CalendarEventRead(
        calendar_id=1,
        calendar_label="Work",
        uid="busy",
        summary="Busy",
        start=datetime(2026, 8, 24, 9, tzinfo=timezone.utc),
        end=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
    )

    async def connection(_agent_id):
        return SimpleNamespace(id=3)

    async def params(_connection, decrypt_passwords=True):
        assert decrypt_passwords is True
        return _connection, {
            "timezone": "UTC",
            "workday_start": "09:00",
            "workday_end": "12:00",
            "slot_step_minutes": "60",
        }

    async def events(*_args, **_kwargs):
        return [busy]

    monkeypatch.setattr(service, "_active_connection_for_agent", connection)
    monkeypatch.setattr(service.connection_service, "get_params_as_dict", params)
    monkeypatch.setattr(service, "events_for_agent", events)
    result = await service.find_free_slots_for_agent(
        7,
        datetime(2026, 8, 24, 8, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 13, tzinfo=timezone.utc),
        duration_minutes=60,
        limit=2,
    )

    assert [(slot.start.hour, slot.end.hour) for slot in result] == [(10, 11), (11, 12)]


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [None, CALENDAR.decode()])
async def test_calendar_failure_never_proves_availability(monkeypatch, db, agent, feed, cached):
    feed.cached_ical_encrypted = service._encrypt(cached)
    feed.last_synced_at = datetime.now(timezone.utc)
    monkeypatch.setattr(service, "_remote_content", AsyncMock(side_effect=OSError("offline")))
    start = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="availability is unknown"):
        await service.availability_for_agent(agent.id, start, start + timedelta(hours=1))
    with pytest.raises(ValueError, match="availability is unknown"):
        await service.find_free_slots_for_agent(agent.id, start, start + timedelta(hours=1), duration_minutes=60)


@pytest.mark.asyncio
async def test_conflict_after_500_transparent_events_is_not_dropped(monkeypatch, db, agent, feed):
    start = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    parsed = [service.ical.ParsedEvent(
        uid=f"{i:04}", summary="Event", description="", location="",
        start=start, end=end, all_day=False, status="", transparent=i < 500,
    ) for i in range(501)]
    monkeypatch.setattr(service, "_remote_content", AsyncMock(return_value=CALENDAR))
    monkeypatch.setattr(service.calculation, "events_between", AsyncMock(return_value=parsed))
    result = await service.availability_for_agent(agent.id, start, end)
    assert result.available is False
    assert [event.uid for event in result.conflicts] == ["0500"]
    assert len(await service.events_for_agent(agent.id, start, end, limit=500)) == 500
    assert await service.find_free_slots_for_agent(
        agent.id, start, end, duration_minutes=60, timezone_name="UTC",
        workday_start="09:00", workday_end="10:00",
    ) == []


@pytest.mark.asyncio
async def test_calendar_recovers_committed_work_while_remote_is_down(monkeypatch, db, agent, feed):
    now = datetime(2026, 8, 22, 10, 5, tzinfo=timezone.utc)
    original_dispatch = service._dispatch
    monkeypatch.setattr(service, "_remote_content", AsyncMock(return_value=CALENDAR))
    monkeypatch.setattr(service, "_dispatch", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await service.sync_feed(feed, agent_id=agent.id, now=now)
    assert feed.last_checked_at == now
    receipt = (await db.scalars(select(CalendarTrigger))).one()
    assert receipt.status == "pending"
    assert receipt.dispatch_encrypted and "untrusted" not in receipt.dispatch_encrypted
    monkeypatch.setattr(service, "_dispatch", original_dispatch)
    monkeypatch.setattr(service, "_remote_content", AsyncMock(side_effect=OSError("offline")))
    submit = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "submit_background_task", submit)
    assert await service.sync_feed(feed, agent_id=agent.id, now=now) == 1
    await db.refresh(receipt)
    assert receipt.status == "success"
    assert submit.await_count == 1


@pytest.mark.asyncio
async def test_discovery_interruption_does_not_advance_cursor(monkeypatch, db, agent, feed):
    now = datetime(2026, 8, 22, 10, 5, tzinfo=timezone.utc)
    feed_id = feed.id
    monkeypatch.setattr(service, "_remote_content", AsyncMock(return_value=CALENDAR))
    monkeypatch.setattr(service, "_claim", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await service.sync_feed(feed, agent_id=agent.id, now=now)
    await db.rollback()
    restored = await service.get_feed(feed_id)
    assert restored.last_checked_at is None
    assert await db.scalar(select(func.count()).select_from(CalendarTrigger)) == 0


@pytest.mark.asyncio
async def test_calendar_replay_after_task_commit_creates_only_one_task(monkeypatch, db, agent, feed):
    from app.agent import submit_background_task
    from app.agent.task_port import task_port
    from app.task.models import Task

    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    monkeypatch.setattr(service, "_remote_content", AsyncMock(return_value=CALENDAR))
    calls = []

    async def interrupted_receipt(draft):
        task_id = await submit_background_task(draft)
        calls.append(task_id)
        if len(calls) == 1:
            raise OSError("receipt lost after commit")
        return task_id

    monkeypatch.setattr(service, "submit_background_task", interrupted_receipt)
    now = datetime(2026, 8, 22, 10, 5, tzinfo=timezone.utc)
    feed_id, agent_id = feed.id, agent.id
    await service.sync_feed(feed, agent_id=agent_id, now=now)
    feed = await service.get_feed(feed_id)
    await service.sync_feed(feed, agent_id=agent_id, now=now)
    receipt = (await db.scalars(select(CalendarTrigger))).one()
    assert len(calls) == 2 and calls[0] == calls[1]
    assert await db.scalar(select(func.count()).select_from(Task)) == 1
    assert receipt.task_id == calls[0]
    assert receipt.status == "success"


@pytest.mark.asyncio
async def test_expired_calendar_lease_is_reclaimed(monkeypatch, db, agent, feed):
    monkeypatch.setattr(service, "_remote_content", AsyncMock(return_value=CALENDAR))
    monkeypatch.setattr(service, "submit_background_task", AsyncMock(side_effect=asyncio.CancelledError()))
    now = datetime(2026, 8, 22, 10, 5, tzinfo=timezone.utc)
    with pytest.raises(asyncio.CancelledError):
        await service.sync_feed(feed, agent_id=agent.id, now=now)
    receipt = (await db.scalars(select(CalendarTrigger))).one()
    assert receipt.lease_token is not None
    assert await service.sync_feed(feed, agent_id=agent.id, now=now) == 0
    receipt.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    submit = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "submit_background_task", submit)
    assert await service.sync_feed(feed, agent_id=agent.id, now=now) == 1
    await db.refresh(receipt)
    assert receipt.status == "success" and receipt.lease_token is None
    submit.assert_awaited_once()
