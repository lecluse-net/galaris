"""Synthetic, durable agenda/cycle links and future-only schedule changes."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.goal import calendar, goal_service, runner
from app.goal.models import Goal, GoalCalendarPlan, GoalCycle, GoalCycleStatus, GoalOccurrence, GoalVerdict
from app.goal.schemas import GoalAgentReferrerInput, GoalCommand, GoalCreate, GoalRecurrence, GoalUpdate
from app.goal.tests.test_goal_runner import _new_agent
from app.task.models import Task, TaskStatus

UTC = timezone.utc
START = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=START - timedelta(minutes=1))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now.astimezone(tz or UTC)

    for module in (calendar, goal_service, runner):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=SimpleNamespace(id=None)))
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())
    return state


async def create_goal(db):
    agent, referrer = await _new_agent(db), await _new_agent(db)
    return await goal_service.create(GoalCreate(title="Synthetic daily objective",
        description="<p>Advance a synthetic dossier until its acceptance criteria are met.</p>",
        agent_id=agent.id, referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
        cycle_delay_seconds=None,
        recurrence=GoalRecurrence(start_at=START, timezone="Europe/Paris")))


def test_fixed_cadence_preserves_local_time_and_skips_invalid_dates():
    daily = GoalRecurrence(start_at=datetime(2026, 3, 28, 8, tzinfo=UTC), timezone="Europe/Paris")
    assert calendar.next_passage(daily, datetime(2026, 3, 29, 0, tzinfo=UTC)) == datetime(2026, 3, 29, 7, tzinfo=UTC)
    gap = daily.model_copy(update={"start_at": datetime(2026, 3, 28, 1, 30, tzinfo=UTC)})
    assert calendar.next_passage(gap, datetime(2026, 3, 29, 0, tzinfo=UTC)) == datetime(2026, 3, 30, 0, 30, tzinfo=UTC)
    monthly = GoalRecurrence(start_at=datetime(2026, 1, 31, 9, tzinfo=UTC), timezone="UTC", frequency="MONTHLY")
    assert calendar.next_passage(monthly, datetime(2026, 2, 1, tzinfo=UTC)) == datetime(2026, 3, 31, 9, tzinfo=UTC)
    with pytest.raises(ValidationError):
        GoalRecurrence(start_at=datetime(2026, 1, 1), timezone="UTC")
    with pytest.raises(ValidationError):
        GoalRecurrence(start_at=START, timezone="Unknown/Synthetic")


@pytest.mark.asyncio
async def test_legacy_cycle_snapshots_are_transactional_idempotent_and_survive_renaming(db, clock):
    from core.dbadmin import SchemaTransitionSet
    from app.goal.agenda_upgrade import backfill_snapshots, needs_agenda_snapshots, snapshots_complete

    goal = await create_goal(db)
    task = Task(agent_id=goal.agent_id, goal_id=goal.id, label="Synthetic previous work", status=TaskStatus.SUCCESS)
    cycle = GoalCycle(goal_id=goal.id, sequence=1, task=task, created_at=START - timedelta(days=3),
        status=GoalCycleStatus.DECIDED, verdict=GoalVerdict.CONTINUE)
    db.add_all([task, cycle])
    await db.commit()
    delta = SchemaTransitionSet(added_tables=frozenset({"goal_occurrences"}))
    assert needs_agenda_snapshots(delta)
    assert not needs_agenda_snapshots(SchemaTransitionSet())
    assert not await snapshots_complete(db, delta)
    with pytest.raises(OSError):
        async with db.begin_nested():
            await backfill_snapshots(db, delta)
            raise OSError("Synthetic snapshot transaction failure")
    assert not await snapshots_complete(db, delta)
    await backfill_snapshots(db, delta)
    await db.commit()
    assert await snapshots_complete(db, delta)
    await goal_service.update(goal.id, GoalUpdate(expected_revision=goal.revision, title="Synthetic future title"))
    await backfill_snapshots(db, delta)
    await db.commit()
    rows = (await calendar.agenda_window(goal.agent_id, START - timedelta(days=4), START)).items
    assert len(rows) == 1 and rows[0].title == "Synthetic daily objective"
    assert rows[0].id == cycle.id and rows[0].task_uri == f"galaris://task/{task.id}"
    assert rows[0].scheduled_at == START - timedelta(days=3)


@pytest.mark.asyncio
async def test_each_daily_event_opens_its_own_cycle_task_and_manual_work_is_separate(db, clock):
    goal = await create_goal(db)
    assert goal.cycle_delay_seconds is None
    window = lambda: calendar.agenda_window(goal.agent_id, START - timedelta(hours=1), START + timedelta(days=3))
    before = (await window()).items
    assert len(before) == 3 and all(item.projected and item.task_uri is None for item in before)
    assert await db.scalar(select(func.count()).select_from(GoalOccurrence)) == 0  # Reading never executes work.
    clock.now = START + timedelta(minutes=10)
    await calendar.materialize_due()
    await calendar.materialize_due()  # Restart/repeated scheduling is idempotent.
    assert await runner.start_due_cycle()
    assert not await runner.start_due_cycle()
    first = (await window()).items[0]
    assert first.id == before[0].id and not first.projected
    cycle = await db.get(GoalCycle, first.cycle_id)
    assert first.task_uri == f"galaris://task/{cycle.task_id}"
    assert first.scheduled_at == START and first.started_at == clock.now
    task = await db.get(Task, cycle.task_id)
    task.status = TaskStatus.SUCCESS
    cycle.status, cycle.verdict = GoalCycleStatus.DECIDED, GoalVerdict.CONTINUE
    await db.commit()
    clock.now = START + timedelta(days=1, minutes=5)
    await calendar.materialize_due()
    assert await runner.start_due_cycle()
    items = (await window()).items
    assert items[0].task_uri == first.task_uri
    assert items[1].task_uri and items[1].task_uri != first.task_uri
    assert items[1].scheduled_at == START + timedelta(days=1)
    assert await db.scalar(select(func.count()).select_from(GoalOccurrence)) == 2
    second_cycle = await db.get(GoalCycle, items[1].cycle_id)
    second_task = await db.get(Task, second_cycle.task_id)
    second_task.status = TaskStatus.SUCCESS
    second_cycle.status, second_cycle.verdict = GoalCycleStatus.DECIDED, GoalVerdict.CONTINUE
    await db.commit()
    clock.now += timedelta(minutes=1)
    current = await goal_service.get_read(goal.id)
    await goal_service.run_now(goal.id, GoalCommand(expected_revision=current.revision))
    assert await runner.start_due_cycle()
    after = (await window()).items
    assert after[1].id == items[1].id and after[1].task_uri == items[1].task_uri
    assert after[2].task_uri and after[2].task_uri != items[1].task_uri


@pytest.mark.asyncio
@pytest.mark.parametrize("task_status", [TaskStatus.SUCCESS, TaskStatus.ERROR])
async def test_elapsed_delay_passage_replaces_its_projection_and_preserves_the_next_one(db, clock, task_status):
    agent, referrer = await _new_agent(db), await _new_agent(db)
    created = await goal_service.create(GoalCreate(title="Synthetic delayed objective",
        description="<p>Advance the synthetic dossier.</p>", agent_id=agent.id,
        referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
        cycle_delay_seconds=3600))
    goal = await db.get(Goal, created.id)
    goal.next_cycle_at = START
    await db.commit()
    window = lambda: calendar.agenda_window(agent.id, START, START + timedelta(days=1))
    before = (await window()).items
    assert len(before) == 1 and before[0].projected

    task = Task(agent_id=agent.id, goal_id=goal.id, label="Synthetic completed cycle", status=task_status)
    cycle = GoalCycle(goal_id=goal.id, sequence=1, task=task, created_at=START + timedelta(seconds=2),
        status=GoalCycleStatus.DECIDED, verdict=GoalVerdict.CONTINUE)
    db.add_all([task, cycle])
    await db.flush()
    await calendar.attach_cycle(goal, cycle, now=START + timedelta(seconds=2), manual=False)
    await db.commit()
    clock.now = START + timedelta(minutes=1)

    # A retained eligibility must not recreate a planned entry for an admitted passage.
    after = (await window()).items
    assert len(after) == 1
    assert not after[0].projected and after[0].scheduled_at == START
    assert after[0].task_uri == f"galaris://task/{task.id}"
    assert after[0].state == ("done" if task_status == TaskStatus.SUCCESS else "error")

    goal.next_cycle_at = START + timedelta(hours=1)
    await db.commit()
    upcoming = (await window()).items
    assert len(upcoming) == 2 and upcoming[0] == after[0]
    assert upcoming[1].projected and upcoming[1].scheduled_at == goal.next_cycle_at
    assert upcoming[1].task_uri is None


@pytest.mark.asyncio
async def test_changing_schedule_preserves_elapsed_pending_and_running_passages(db, clock):
    goal = await create_goal(db)
    clock.now = START + timedelta(minutes=15)
    await calendar.materialize_due()
    old = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=2))).items[0]
    updated = await goal_service.update(goal.id, GoalUpdate(expected_revision=goal.revision,
        title="Synthetic revised objective", recurrence=GoalRecurrence(start_at=START + timedelta(hours=1), timezone="Europe/Paris")))
    assert updated.recurrence.start_at == START + timedelta(hours=1)
    assert await runner.start_due_cycle()  # Pending old passage survives the edit.
    rows = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=2))).items
    assert rows[0].id == old.id and rows[0].title == "Synthetic daily objective"
    assert rows[0].task_uri and rows[0].scheduled_at == START
    assert rows[1].scheduled_at == START + timedelta(hours=1)
    assert all(row.title == "Synthetic revised objective" for row in rows[1:])
    again = await goal_service.get_read(goal.id)
    await goal_service.update(goal.id, GoalUpdate(expected_revision=again.revision,
        recurrence=GoalRecurrence(start_at=START + timedelta(hours=2), timezone="Europe/Paris")))
    after = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=2))).items
    assert after[0] == rows[0]
    assert after[1].scheduled_at == START + timedelta(hours=2)
    assert await db.scalar(select(func.count()).select_from(GoalCycle)) == 1


@pytest.mark.asyncio
async def test_recovery_retains_old_schedule_without_replaying_missed_cycles(db, clock):
    goal = await create_goal(db)
    # No worker ran for two days. Closing the old series must still retain its history.
    clock.now = START + timedelta(days=2, minutes=5)
    updated = await goal_service.update(goal.id, GoalUpdate(expected_revision=goal.revision,
        recurrence=GoalRecurrence(start_at=START + timedelta(hours=1), timezone="Europe/Paris")))
    await calendar.materialize_due(limit=1)
    await calendar.materialize_due(limit=1)
    await calendar.materialize_due(limit=1)
    rows = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=3))).items
    assert [row.scheduled_at for row in rows[:3]] == [START + timedelta(days=n) for n in range(3)]
    assert [row.state for row in rows[:3]] == ["skipped", "skipped", "waiting"]
    assert await runner.start_due_cycle()
    await goal_service.complete(goal.id, GoalCommand(expected_revision=(await goal_service.get_read(goal.id)).revision))
    closed = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=5))).items
    assert len(closed) == 3 and not any(row.projected for row in closed)
    assert closed[2].task_uri and closed[0].task_uri is None
    assert await db.scalar(select(func.count()).select_from(GoalCalendarPlan)) == 2


@pytest.mark.asyncio
async def test_pause_closes_only_future_and_resume_does_not_replay_the_pause(db, clock):
    goal = await create_goal(db)
    clock.now = START + timedelta(minutes=10)
    goal = await goal_service.pause(goal.id, GoalCommand(expected_revision=goal.revision))
    clock.now = START + timedelta(days=3, minutes=10)
    goal = await goal_service.resume(goal.id, GoalCommand(expected_revision=goal.revision))
    await calendar.materialize_due()
    rows = (await calendar.agenda_window(goal.agent_id, START, START + timedelta(days=5))).items
    assert rows[0].scheduled_at == START and rows[0].state == "skipped"
    assert rows[1].scheduled_at == START + timedelta(days=4)
    assert len(rows) == 2
    assert not await runner.start_due_cycle()


@pytest.mark.asyncio
async def test_admission_rollback_and_concurrent_workers_keep_one_passage_cycle_and_task(inference_db, clock, monkeypatch):
    from core.database import get_db_session

    goal = await create_goal(inference_db)
    clock.now = START + timedelta(minutes=5)
    async with get_db_session():
        await calendar.materialize_due()
    attach = calendar.attach_cycle
    failed = False

    async def interrupted(*args, **kwargs):
        nonlocal failed
        await attach(*args, **kwargs)
        if not failed:
            failed = True
            raise OSError("Synthetic interruption before admission commit")

    monkeypatch.setattr(calendar, "attach_cycle", interrupted)
    with pytest.raises(OSError, match="Synthetic interruption"):
        async with get_db_session():
            await runner.start_due_cycle()
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.goal_id == goal.id)) == 0
        occurrence = (await db.scalars(select(GoalOccurrence).where(GoalOccurrence.goal_id == goal.id))).one()
        assert occurrence.state == "waiting" and occurrence.cycle_id is None
        identity = occurrence.id

    async def worker():
        async with get_db_session():
            await calendar.materialize_due()
            return await runner.start_due_cycle()

    assert sum(await asyncio.gather(worker(), worker())) == 1
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.goal_id == goal.id)) == 1
        rows = (await db.scalars(select(GoalOccurrence).where(GoalOccurrence.goal_id == goal.id))).all()
        assert len(rows) == 1 and rows[0].id == identity and rows[0].cycle_id is not None
        assert await db.scalar(select(func.count()).select_from(GoalCycle).where(GoalCycle.goal_id == goal.id)) == 1


@pytest.mark.asyncio
async def test_goal_agenda_http_checks_privileges_scope_and_bounds(client, monkeypatch):
    from app.agent import AgentManagementScope
    from app.goal import router as goal_router
    from core.user.models import User
    from core.user import create_access_token
    from core.user.user_service import user_identity_context
    from app.agent.models import Agent, Title

    # The integration authorization matrix is exercised below using a synthetic role/user.
    from core.authorize.models import Assignment, Privilege, Role
    from core.database import get_db_session
    async with get_db_session() as db:
        user = User(email="synthetic-goal-agenda@example.test", hashed_password="unused", is_active=True)
        db.add(user)
        await db.flush()
        with user_identity_context(user):
            title = Title(label="Synthetic agenda reader", gender="N")
            db.add(title)
            await db.flush()
            title_agent = Agent(user_id=user.id, title_id=title.id, code="synthetic-goal-agenda-reader", first_name="Synthetic", last_name="Agenda")
            db.add(title_agent)
            await db.flush()
        right = await db.scalar(select(Privilege).where(Privilege.code == "GOAL_ACCESS"))
        role = Role(code="synthetic-goal-agenda-reader", privileges=[right])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        await db.commit()
        user_id, agent_id = user.id, title_agent.id
    # Use the same native token contract as other HTTP suites.
    token = create_access_token({"sub": "synthetic-goal-agenda@example.test", "user_id": user_id})
    monkeypatch.setattr(goal_router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(user_id=user_id, agent_ids=frozenset({agent_id}))))
    params = {"agent_id": agent_id, "start": START.isoformat(), "end": (START + timedelta(days=1)).isoformat()}
    assert (await client.get("/api/goals/agenda", params=params)).status_code in (401, 403)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/goals/agenda", params=params, headers=headers)).status_code == 200
    assert (await client.get("/api/goals/agenda", params={**params, "agent_id": agent_id + 1}, headers=headers)).status_code == 404
    assert (await client.get("/api/goals/agenda", params={**params, "end": (START + timedelta(days=33)).isoformat()}, headers=headers)).status_code == 422
