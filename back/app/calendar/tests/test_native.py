"""Local commands, occurrence identity, history and durable task admission."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from app.agent.task_port import task_port
from app.calendar import dispatch, service, store
from app.calendar.models import CalendarEvent, CalendarEventRevision, CalendarTrigger, CalendarOccurrence
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarEventDelete, CalendarActionWrite
from app.task.models import Task, TaskStatus

NOW = datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc)


def appointment(**kwargs):
    return CalendarEventCreate(summary="Synthetic appointment", start=NOW + timedelta(minutes=30),
        end=NOW + timedelta(minutes=60), **kwargs)


@pytest.mark.asyncio
async def test_local_agenda_commands_are_network_free_historized_and_revision_checked(db, agent, personal, monkeypatch):
    connection, feed = personal
    from app.calendar import synchronization
    network = AsyncMock(side_effect=AssertionError("Local commands must not access a provider"))
    monkeypatch.setattr(synchronization, "read_calendar", network)
    created = await service.create_calendar_event(feed.id, agent.id, appointment(uid="synthetic-unique@example.test"))
    replay = await service.create_calendar_event(feed.id, agent.id, appointment(uid=created.uid))
    assert replay.event_id == created.event_id
    page = await service.event_window(agent.id, NOW, NOW + timedelta(days=1))
    assert len(page.items) == page.total == 1 and page.complete
    with pytest.raises(store.CalendarConflictError):
        await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=9, summary="Stale"))
    updated = await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1, summary="Synthetic updated"))
    assert updated.revision == 2
    await service.delete_calendar_event(feed.id, agent.id, created.uid, CalendarEventDelete(expected_revision=2))
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == 0
    stored = await db.scalar(select(CalendarEvent).where(CalendarEvent.id == created.event_id).execution_options(include_historized=True))
    assert stored.deleted_at is not None and "Synthetic" not in stored.content_encrypted
    assert await db.scalar(select(func.count()).select_from(CalendarEventRevision).where(CalendarEventRevision.event_id == stored.id)) == 3
    network.assert_not_awaited()


@pytest.mark.asyncio
async def test_actions_have_distinct_tasks_results_and_recover_after_lost_admission_receipt(db, agent, personal, monkeypatch):
    connection, feed = personal
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    created = await service.create_calendar_event(feed.id, agent.id, appointment(reminder_minutes_before=30))
    await service.write_action(feed.id, agent.id, created.uid, CalendarActionWrite(offset_minutes=-30, instructions="Prepare synthetic meeting"))
    original = dispatch.submit_background_task
    lost = False
    async def admit(draft):
        nonlocal lost
        identity = await original(draft)
        if not lost:
            lost = True
            raise OSError("Synthetic receipt loss")
        return identity
    monkeypatch.setattr(dispatch, "submit_background_task", admit)
    await dispatch.dispatch_due(now=NOW)
    await dispatch.dispatch_due(now=NOW)
    assert await db.scalar(select(func.count()).select_from(Task)) == 2
    assert await dispatch.dispatch_due(now=NOW) == 0
    journal = await service.list_reminders(connection.id, event_id=created.event_id)
    assert journal.total == 2 and all(row.task_uri and not row.treated for row in journal.items)
    tasks = list((await db.scalars(select(Task))).all())
    tasks[0].status = TaskStatus.SUCCESS
    await db.commit()
    assert sum(row.treated for row in (await service.list_reminders(connection.id)).items) == 1
    assert all(task.goal_id is None for task in tasks)


@pytest.mark.asyncio
async def test_moving_and_deleting_occurrences_recalculates_pending_actions_without_affecting_other_instances(db, agent, personal, monkeypatch):
    _, feed = personal
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    created = await service.create_calendar_event(feed.id, agent.id, appointment(rrule="FREQ=DAILY;COUNT=3", reminder_minutes_before=30))
    rows = (await service.event_window(agent.id, NOW, NOW + timedelta(days=4))).items
    first_key = rows[0].recurrence_key
    moved = await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1,
        scope="occurrence", recurrence_key=first_key, start=NOW + timedelta(hours=2), end=NOW + timedelta(hours=3)))
    after = (await service.event_window(agent.id, NOW, NOW + timedelta(days=4))).items
    assert len(after) == 3 and after[0].recurrence_key == first_key and after[0].start == NOW + timedelta(hours=2)
    assert await dispatch.dispatch_due(now=NOW) == 0
    await service.delete_calendar_event(feed.id, agent.id, created.uid, CalendarEventDelete(expected_revision=moved.revision,
        scope="occurrence", recurrence_key=first_key))
    assert await dispatch.dispatch_due(now=NOW + timedelta(hours=2)) == 0
    remaining = (await service.event_window(agent.id, NOW, NOW + timedelta(days=4))).items
    assert len([row for row in remaining if row.status != "CANCELLED"]) == 2
    assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
async def test_late_actions_are_explicitly_skipped_and_foreign_agents_cannot_mutate(db, agent, personal):
    _, feed = personal
    created = await service.create_calendar_event(feed.id, agent.id, appointment(reminder_minutes_before=30))
    with pytest.raises(PermissionError):
        await service.update_calendar_event(feed.id, agent.id + 1000, created.uid, CalendarEventUpdate(expected_revision=1, summary="Forbidden"))
    assert await dispatch.dispatch_due(now=NOW + timedelta(hours=2)) == 0
    assert (await db.scalars(select(CalendarTrigger))).one().status == "skipped"
    assert (await db.scalars(select(CalendarOccurrence))).one().event_id == created.event_id


@pytest.mark.asyncio
async def test_browsing_old_months_does_not_change_scheduled_actions_or_lose_future_coverage(db, agent, personal):
    from sqlalchemy import update
    from app.calendar.maintenance import prune_calendar_cache
    from app.calendar.models import CalendarProjectionWindow
    _, feed = personal
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic long series",
        start=datetime(2020,1,1,10,tzinfo=timezone.utc), end=datetime(2020,1,1,11,tzinfo=timezone.utc),
        rrule="FREQ=DAILY", reminder_minutes_before=30))
    before = await db.scalar(select(func.count()).select_from(CalendarTrigger).where(CalendarTrigger.status == 'scheduled'))
    window = await service.event_window(agent.id, datetime(2020,1,1,tzinfo=timezone.utc), datetime(2020,2,1,tzinfo=timezone.utc))
    assert window.total == 31
    after = await db.scalar(select(func.count()).select_from(CalendarTrigger).where(CalendarTrigger.status == 'scheduled'))
    assert before == after and after > 0
    future = await service.event_window(agent.id, NOW, NOW + timedelta(days=30))
    assert future.total >= 30
    await db.execute(update(CalendarProjectionWindow).where(CalendarProjectionWindow.end_at < NOW - timedelta(days=365))
        .values(built_at=NOW - timedelta(days=90)))
    await db.commit()
    assert await prune_calendar_cache() == 31
    assert await db.scalar(select(func.count()).select_from(CalendarTrigger).where(CalendarTrigger.status == 'scheduled')) == before
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=30))).total == future.total
    assert (await service.event_window(agent.id, datetime(2020,1,1,tzinfo=timezone.utc), datetime(2020,2,1,tzinfo=timezone.utc))).total == 31


@pytest.mark.asyncio
async def test_an_admitted_task_is_reconciled_before_event_edit_and_terminal_task_can_be_relaunched(db, agent, personal, monkeypatch):
    from uuid import uuid4
    _, feed = personal
    calendar_id, agent_id = feed.id, agent.id
    monkeypatch.setattr(task_port, 'schedule', lambda _: None)
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic meeting",
        description="Synthetic complete execution context", start=NOW + timedelta(minutes=30), end=NOW + timedelta(hours=1), reminder_minutes_before=30))
    original = dispatch.submit_background_task
    async def lost(draft):
        await original(draft)
        raise OSError('Synthetic lost receipt')
    monkeypatch.setattr(dispatch, 'submit_background_task', lost)
    await dispatch.dispatch_due(now=NOW)
    await service.update_calendar_event(calendar_id, agent_id, created.uid, CalendarEventUpdate(expected_revision=1, description="Synthetic revised context"))
    receipt = (await db.scalars(select(CalendarTrigger))).one()
    task = (await db.scalars(select(Task))).one()
    assert receipt.task_id == task.id and receipt.status == 'submitted'
    assert task.data['event']['description'] == 'Synthetic complete execution context'
    assert await dispatch.dispatch_due(now=NOW) == 0
    task.status = TaskStatus.ERROR
    await db.commit()
    request_key = uuid4()
    relaunched = await service.relaunch_execution(calendar_id, receipt.id, agent_id, request_key, 2)
    replay = await service.relaunch_execution(calendar_id, receipt.id, agent_id, request_key, 2)
    assert replay.id == relaunched.id
    monkeypatch.setattr(dispatch, 'submit_background_task', original)
    await dispatch.dispatch_due(now=datetime.now(timezone.utc) + timedelta(seconds=1))
    tasks = list((await db.scalars(select(Task))).all())
    assert len(tasks) == 2 and task.status == TaskStatus.ERROR
    newer = next(row for row in tasks if row.id != task.id)
    assert newer.data['event']['description'] == 'Synthetic revised context'


@pytest.mark.asyncio
async def test_following_rule_change_preserves_past_occurrences_and_future_exceptions(db, agent, personal):
    _, feed = personal
    created = await service.create_calendar_event(feed.id, agent.id, appointment(rrule='FREQ=DAILY;COUNT=5'))
    rows = (await service.event_window(agent.id, NOW, NOW + timedelta(days=10))).items
    await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1,
        scope='occurrence', recurrence_key=rows[4].recurrence_key, summary='Synthetic exceptional meeting'))
    changed = await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=2,
        scope='following', recurrence_key=rows[2].recurrence_key, rrule='FREQ=WEEKLY;COUNT=2'))
    window = await service.event_window(agent.id, NOW, NOW + timedelta(days=20))
    assert len([row for row in window.items if row.event_id == created.event_id]) == 2
    assert changed.event_id != created.event_id
    assert any(row.summary == 'Synthetic exceptional meeting' for row in window.items)
    assert (await service.event_detail(feed.id, changed.uid)).parent_event_id == created.event_id
