"""Persistent multi-cycle supervision, with only model and scheduler boundaries replaced."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.goal import get_goal_document_store
from app.goal import goal_service, runner
from app.goal.models import Goal, GoalCycle, GoalCycleStatus, GoalStatus, GoalVerdict
from app.goal.schemas import GoalDecision
from app.goal.tests.factories import make_goal
from app.llm.structured_service import StructuredInferenceResult
from app.task import Task, TaskCreate, TaskStatus, initialize_scope, task_service
from core.user import UserModel


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def boundaries(monkeypatch):
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=SimpleNamespace(id=None)))
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())
    monkeypatch.setattr(task_service, "publish_created", AsyncMock())
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args: None)


def decision(action="CONTINUE"):
    return GoalDecision(action=action)


async def setup_cycle(db, *, sequence=1):
    owner = UserModel(email=f"autonomy-{uuid4().hex}@example.test", display_name="Synthetic owner",
                      hashed_password="unused", is_active=True)
    db.add(owner)
    await db.flush()
    title = await db.scalar(select(Title).limit(1))
    if title is None:
        title = Title(label="Synthetic", gender="M")
        db.add(title)
        await db.flush()
    agent = Agent(user_id=owner.id, title_id=title.id, code=f"autonomy-{uuid4().hex[:8]}", first_name="Synthetic", last_name="Reviewer")
    db.add(agent)
    await db.flush()
    goal = await make_goal(title="Improve a synthetic manual", description="<p>Make the manual usable.</p>",
        agent_id=agent.id, requester_user_id=owner.id, cycle_delay_seconds=0, status=GoalStatus.ACTIVE)
    db.add(goal)
    await db.flush()
    task = task_service.build(TaskCreate(
        label="Improve the manual", objective=goal.description, agent_id=agent.id,
        goal_id=goal.id, status=TaskStatus.SUCCESS, feedback="A first version exists.", cost=0.4))
    task.requester_user_id = owner.id
    await initialize_scope(task, source_reference=f"galaris://goal/{goal.id}")
    db.add(task)
    await db.flush()
    cycle = GoalCycle(goal_id=goal.id, sequence=sequence, task=task, status=GoalCycleStatus.RUNNING)
    db.add(cycle)
    await db.commit()
    return goal, cycle, task


def model(monkeypatch, *decisions):
    inference = AsyncMock(side_effect=[StructuredInferenceResult(output=item, cost=0.01, messages=[])
                                      for item in decisions])
    monkeypatch.setattr(runner, "evaluate_goal", inference)
    return inference


@pytest.mark.parametrize("action", ["CONTINUE", "STOP"])
async def test_judgement_finishes_without_an_extra_task(db, monkeypatch, action):
    goal, cycle, _ = await setup_cycle(db)
    inference = model(monkeypatch, decision(action))
    await runner.process_terminal_cycle()
    assert cycle.status == GoalCycleStatus.DECIDED
    assert goal.status == (GoalStatus.COMPLETED if action == "STOP" else GoalStatus.ACTIVE)
    assert goal.next_cycle_at is not None if action != "STOP" else goal.next_cycle_at is None
    assert inference.await_count == 1
    assert len(list(await db.scalars(select(Task).where(Task.goal_id == goal.id)))) == 1


async def test_stagnation_continues_on_schedule(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db, sequence=3)
    db.add_all([GoalCycle(goal_id=goal.id, sequence=n, status=GoalCycleStatus.DECIDED,
        verdict=GoalVerdict.CONTINUE, progress_changed=False) for n in (1, 2)])
    await db.commit()
    model(monkeypatch, decision())
    await runner.process_terminal_cycle()
    assert cycle.verdict == GoalVerdict.CONTINUE
    assert goal.status == GoalStatus.ACTIVE and goal.next_cycle_at is not None


async def test_monitoring_preserves_tracking_and_passes_task_result_to_next_cycle(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    tracking = "<p>Keep this human-maintained constraint and evidence.</p>"
    await get_goal_document_store().update(goal.tracking_document_id, content=tracking)
    revision = await get_goal_document_store().revision(goal.tracking_document_id)
    source.feedback = "Synthetic verified outcome. " * 2000 + "Unresolved final constraint."
    await db.commit()
    model(monkeypatch, decision())
    await runner.process_terminal_cycle()
    assert (await goal_service.read_markdown(goal)).tracking == tracking
    assert await get_goal_document_store().revision(goal.tracking_document_id) == revision
    assert cycle.continuation_context == source.feedback
    assert source.feedback in await runner._cycle_task_objective(goal, 2)
    assert cycle.progress_changed is None and cycle.progress_summary is None


@pytest.mark.parametrize("change", ["goal", "tracking", "work"])
async def test_changed_context_discards_stale_decision_and_preserves_paid_cost(db, monkeypatch, change):
    goal, cycle, source = await setup_cycle(db)

    async def evaluate(**_kwargs):
        if change == "goal":
            goal.description = "<p>Revised original constraint.</p>"
        elif change == "tracking":
            await get_goal_document_store().update(goal.tracking_document_id, content="<p>New constraint.</p>")
        else:
            source.feedback = "Corrected work result during decision."
        await db.commit()
        return StructuredInferenceResult(output=decision("STOP"), cost=0.01, messages=[])

    monkeypatch.setattr(runner, "evaluate_goal", evaluate)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.ACTIVE and cycle.verdict is None
    assert cycle.judge_cost == pytest.approx(0.01)
    model(monkeypatch, decision())
    await runner.process_terminal_cycle()
    assert cycle.verdict == GoalVerdict.CONTINUE and cycle.judge_cost == pytest.approx(0.02)


@pytest.mark.parametrize("reason", ["MANUAL", "REFERRER_NO_RESPONSE"])
async def test_existing_human_pause_cannot_be_completed_by_judgement(db, monkeypatch, reason):
    goal, cycle, _ = await setup_cycle(db)
    goal.status = GoalStatus.PAUSED
    goal.pause_reason = reason
    await db.commit()
    model(monkeypatch, decision("STOP"))
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.PAUSED and goal.pause_reason == reason
    assert cycle.verdict == GoalVerdict.CONTINUE


async def test_expired_judge_lease_recovers_once_without_new_tasks(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    cycle.lease_token = uuid4()
    cycle.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    inference = model(monkeypatch, decision("STOP"))
    assert await runner.process_terminal_cycle()
    assert not await runner.process_terminal_cycle()
    assert cycle.verdict == GoalVerdict.STOP and goal.status == GoalStatus.COMPLETED
    assert inference.await_count == 1


async def test_concurrent_judges_apply_only_one_decision(committed_database, monkeypatch):
    from core.database import get_db_session
    async with get_db_session() as session:
        goal, cycle, _ = await setup_cycle(session)
        cycle.status = GoalCycleStatus.JUDGING
        token = uuid4()
        cycle.lease_token = token
        goal_revision, cycle_id, goal_id = goal.revision, cycle.id, goal.id
        await session.commit()

    async def finish():
        async with get_db_session():
            await runner._finish_judgement(cycle_id, token, decision("STOP"),
                expected_goal_revision=goal_revision, cost=0.01, llm_id=None)

    await asyncio.wait_for(asyncio.gather(finish(), finish()), timeout=10)
    async with get_db_session() as session:
        cycle = await session.get(GoalCycle, cycle_id)
        assert len(list(await session.scalars(select(Task).where(Task.goal_id == goal_id)))) == 1
        assert cycle.verdict == GoalVerdict.STOP and cycle.judge_cost == pytest.approx(0.01)


async def test_no_decision_model_disables_monitoring_without_blocking_work(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    inference = model(monkeypatch)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.ACTIVE and goal.next_cycle_at is not None
    assert cycle.verdict == GoalVerdict.CONTINUE and cycle.judge_cost == 0
    inference.assert_not_awaited()


@pytest.mark.parametrize("reason", ["BLOCKED", "REVIEW_UNAVAILABLE", "MANUAL", "REFERRER_NO_RESPONSE"])
async def test_recovery_only_resumes_obsolete_automatic_pauses(db, monkeypatch, reason):
    goal, cycle, _ = await setup_cycle(db)
    goal.status = GoalStatus.PAUSED
    goal.pause_reason = reason
    cycle.status = GoalCycleStatus.DECIDED
    cycle.verdict = GoalVerdict.CONTINUE
    cycle.task_finished_at = datetime.now(timezone.utc)
    await db.commit()
    obsolete = reason in {"BLOCKED", "REVIEW_UNAVAILABLE"}
    assert await goal_service.recover_obsolete_supervision_pause() is obsolete
    assert goal.status == (GoalStatus.ACTIVE if obsolete else GoalStatus.PAUSED)
    assert goal.pause_reason == (None if obsolete else reason)
    assert not await goal_service.recover_obsolete_supervision_pause()


async def test_provisional_work_error_does_not_start_judgement(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    source.status = TaskStatus.ERROR
    source.lease_token = uuid4()
    source.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    await db.commit()
    inference = model(monkeypatch, decision())
    assert not await runner.process_terminal_cycle()
    assert cycle.status == GoalCycleStatus.RUNNING
    inference.assert_not_awaited()
    source.lease_token = None
    await db.commit()
    assert await runner.process_terminal_cycle()
    assert cycle.verdict == GoalVerdict.CONTINUE and goal.status == GoalStatus.ACTIVE
