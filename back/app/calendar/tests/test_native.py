"""Local commands, occurrence identity, history and durable task admission."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from app.agent.task_port import task_port
from app.calendar import dispatch, service, store
from app.calendar.models import CalendarEvent, CalendarEventRevision, CalendarTrigger, CalendarOccurrence, CalendarFeed
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarEventDelete, CalendarActionWrite, CalendarOccurrenceSelection, CalendarFeedCreate, CalendarFeedUpdate
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
    assert service.serialize_feed(feed, agent.id).is_default
    with pytest.raises(ValueError, match="one automatic personal agenda"):
        await service.create_feed(CalendarFeedCreate(connection_id=connection.id, label="Synthetic secondary agenda"))
    with pytest.raises(ValueError, match="cannot be disabled"):
        await service.update_feed(feed.id, CalendarFeedUpdate(active=False))
    with pytest.raises(ValueError, match="default personal agenda"):
        await service.delete_feed(feed.id)
    assert len(await service.list_feeds(connection_id=connection.id)) == 1
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
async def test_an_event_without_an_alarm_automatically_admits_one_task_with_its_complete_context(db, agent, personal, monkeypatch):
    _, feed = personal
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    created = await service.create_calendar_event(feed.id, agent.id, appointment(
        description="Prepare the synthetic report and its conclusions", location="Synthetic meeting room"))
    trigger = (await db.scalars(select(CalendarTrigger))).one()
    assert trigger.action_key == "event:start" and trigger.occurrence_at == NOW + timedelta(minutes=30)
    assert await service.list_actions(feed.id, created.uid) == []
    assert await dispatch.dispatch_due(now=NOW) == 0
    await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(
        expected_revision=1, description="Prepare the revised synthetic report and its conclusions"))
    assert await dispatch.dispatch_due(now=NOW + timedelta(minutes=30)) == 1
    assert await dispatch.dispatch_due(now=NOW + timedelta(minutes=30)) == 0
    task = (await db.scalars(select(Task))).one()
    context = task.data["event"]
    assert context["summary"] == "Synthetic appointment"
    assert context["description"] == "Prepare the revised synthetic report and its conclusions"
    assert context["location"] == "Synthetic meeting room"
    assert datetime.fromisoformat(context["start"]) == NOW + timedelta(minutes=30)
    assert datetime.fromisoformat(context["end"]) == NOW + timedelta(minutes=60)
    assert context["timezone_name"] == "Europe/Paris"
    assert context["description"] in task.objective and context["location"] in task.objective
    journal = await service.list_reminders(feed.connection_id, event_id=created.event_id)
    assert journal.total == 1 and journal.items[0].task_uri == f"galaris://task/{task.id}"
    task.status = TaskStatus.SUCCESS
    await db.commit()
    await service.relaunch_execution(feed.id, trigger.id, agent.id, uuid4(), 2)
    assert await dispatch.dispatch_due(now=datetime.now(timezone.utc) + timedelta(seconds=1)) == 1


@pytest.mark.asyncio
async def test_existing_personal_calendar_is_adopted_without_creating_a_duplicate(db, personal):
    connection, feed = personal
    feed.is_default = False
    await db.commit()
    assert (await service._ensure_native_feed(connection)).id == feed.id
    assert (await service._ensure_native_feed(connection)).id == feed.id
    assert await db.scalar(select(func.count()).select_from(type(feed)).where(type(feed).connection_id == connection.id)) == 1


@pytest.mark.asyncio
async def test_external_calendars_expose_their_tool_label_and_never_the_personal_default_marker(db, agent, personal, calendar_connection):
    from app.tools.models import Tool
    tool = await db.get(Tool, calendar_connection.tool_id)
    tool.label = "Synthetic calendar provider"
    external = CalendarFeed(connection_id=calendar_connection.id, label="Synthetic external calendar",
        source_kind="caldav", is_default=True, active=True, initialized=True)
    db.add(external)
    await db.commit()
    rows = await service.list_feeds(agent_id=agent.id)
    assert [row.id for row in rows if row.is_default] == [personal[1].id]
    assert next(row for row in rows if row.id == external.id).tool_label == tool.label
    tool.label = "Renamed synthetic provider"
    await db.commit()
    rows = await service.list_feeds(agent_id=agent.id)
    assert next(row for row in rows if row.id == external.id).tool_label == tool.label
    assert external.is_default  # Synchronization keeps its private discovery-root marker.


@pytest.mark.asyncio
@pytest.mark.parametrize('first_check', [NOW - timedelta(hours=1), NOW + timedelta(minutes=30)])
async def test_missed_early_notification_falls_back_to_event_start_without_duplicate_admission(db, agent, personal, monkeypatch, first_check):
    _, feed = personal
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    await service.create_calendar_event(feed.id, agent.id, appointment(reminder_minutes_before=180,
        description='Deliver a complete synthetic response.'))
    count = await dispatch.dispatch_due(now=first_check)
    if first_check < NOW + timedelta(minutes=30):
        assert count == 0
        assert await dispatch.dispatch_due(now=NOW + timedelta(minutes=30)) == 1
    else:
        assert count == 1
    assert await dispatch.dispatch_due(now=NOW + timedelta(minutes=30)) == 0
    task = (await db.scalars(select(Task))).one()
    assert task.data['missed_notification_at'] == (NOW - timedelta(minutes=150)).isoformat()
    assert task.data['fallback_at'] == (NOW + timedelta(minutes=30)).isoformat()
    assert task.data['event']['description'] in task.objective


@pytest.mark.asyncio
async def test_upcoming_legacy_events_without_actions_are_scheduled_by_the_existing_calendar_worker(db, agent, personal):
    from sqlalchemy import delete
    _, feed = personal
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(
        summary="Synthetic legacy appointment", start=start, end=start + timedelta(hours=1)))
    event = await db.get(CalendarEvent, created.event_id)
    assert event is not None
    event.has_actions = False
    await db.execute(delete(CalendarTrigger).where(CalendarTrigger.event_id == event.id))
    await db.commit()
    await service.sync_native_calendars()
    trigger = (await db.scalars(select(CalendarTrigger).where(CalendarTrigger.event_id == event.id))).one()
    assert trigger.action_key == "event:start" and trigger.status == "scheduled" and event.has_actions
    await service.sync_native_calendars()
    assert await db.scalar(select(func.count()).select_from(CalendarTrigger).where(CalendarTrigger.event_id == event.id)) == 1


@pytest.mark.asyncio
async def test_actions_have_distinct_tasks_results_and_recover_after_lost_admission_receipt(db, agent, personal, monkeypatch):
    connection, feed = personal
    agent_id, connection_id = agent.id, connection.id
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    created = await service.create_calendar_event(feed.id, agent.id, appointment(reminder_minutes_before=30))
    data = CalendarActionWrite(request_key=uuid4(), offset_minutes=-30, instructions="Prepare synthetic meeting")
    action = await service.write_action(feed.id, agent.id, created.uid, data)
    assert (await service.write_action(feed.id, agent.id, created.uid, data)).id == action.id
    with pytest.raises(store.CalendarConflictError):
        await service.write_action(feed.id, agent.id, created.uid, data.model_copy(update={"instructions": "Different synthetic work"}))
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
    occurrence = (await service.event_window(agent_id, NOW, NOW + timedelta(days=1))).items[0]
    summaries = await service.execution_summaries(connection_id, [CalendarOccurrenceSelection(event_id=created.event_id, recurrence_key=occurrence.recurrence_key)])
    assert len(summaries) == 1 and summaries[0].total == 2
    assert summaries[0].states == {"done": 1, "queued": 1}
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
    # The next surviving occurrence still launches automatically with its recurrence context.
    next_event = next(row for row in remaining if row.status != "CANCELLED")
    assert await dispatch.dispatch_due(now=next_event.start) == 1
    task = (await db.scalars(select(Task))).one()
    assert task.data["event_recurrence"]["rrule"] == "FREQ=DAILY;COUNT=3"


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
    connection, feed = personal
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
    summaries = await service.execution_summaries(connection.id, [CalendarOccurrenceSelection(event_id=created.event_id, recurrence_key=receipt.recurrence_key)])
    # Old failed launches remain in history; the calendar displays the latest launch per action.
    assert summaries[0].total == 2 and summaries[0].states == {"queued": 1}


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
