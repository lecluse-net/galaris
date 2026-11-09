"""Persistent multi-cycle supervision, with only model and scheduler boundaries replaced."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import AIMessage, ExecutionResult
from app.agent.models import Agent, Title
from app.goal import get_goal_document_store
from app.goal import goal_service, runner, reviews
from app.goal.models import Goal, GoalCycle, GoalCycleStatus, GoalStatus, GoalVerdict
from app.goal.schemas import GoalCommand, GoalJudgement
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


def decision(action="CONTINUE", *, changed=True, tracking="<p>Improve the existing result.</p>"):
    return GoalJudgement(action=action, reason="Synthetic decision based on the original outcome.",
        progress={"changed": changed, "summary": "Observed synthetic outcome.",
                  "evidence": ["Synthetic observed resource"]}, tracking_content=tracking)


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
    monkeypatch.setattr(runner, "run_structured", inference)
    return inference


async def finish_review(db, cycle, *, success=True, cost=0.2):
    await db.refresh(cycle)
    review = await db.get(Task, cycle.review_task_id)
    assert review is not None
    review.status = TaskStatus.SUCCESS if success else TaskStatus.ERROR
    review.cost = cost
    review.feedback = "Independent inspection found remaining gaps." if success else "Inspection unavailable."
    if success:
        review.set_execution_result(ExecutionResult(prompt="Review", result=review.feedback,
            success=True, messages=[AIMessage(type="tool", tool_name="file_read",
                content="Synthetic resource revision inspected.", success=True)]))
    review.lease_token = None
    await db.commit()
    return review


async def test_review_success_without_observations_is_not_completion(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("STOP"), decision("STOP"))
    await runner.process_terminal_cycle()
    review = await db.get(Task, cycle.review_task_id)
    review.status = TaskStatus.SUCCESS
    review.feedback = "Everything is complete, without inspection."
    await db.commit()
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.PAUSED and goal.completed_at is None
    assert cycle.verdict == GoalVerdict.CONTINUE
    assert "no recorded successful tool observation" in cycle.reason
    assert "completion is not verified" in (await goal_service.read_markdown(goal)).tracking


async def test_completion_requires_durable_review_and_counts_its_cost(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    inference = model(monkeypatch, decision("STOP"), decision("STOP"))
    assert await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert cycle.status == GoalCycleStatus.JUDGING and cycle.verdict is None
    assert goal.status == GoalStatus.ACTIVE
    review = await db.get(Task, cycle.review_task_id)
    assert review.agent_id == source.agent_id
    assert review.parent_id == source.id and review.goal_id == goal.id
    assert review.requester_user_id == source.requester_user_id
    assert review.data["execution_scope"] == source.data["execution_scope"]
    assert "goal_judgement" in review.data["retention_reasons"]
    for _ in range(3):
        assert not await runner.process_terminal_cycle()
    assert inference.await_count == 1
    await finish_review(db, cycle)
    assert await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert goal.status == GoalStatus.COMPLETED and cycle.verdict == GoalVerdict.STOP
    assert cycle.task_cost == pytest.approx(0.6)
    assert cycle.judge_cost == pytest.approx(0.02)
    assert "INDEPENDENT REVIEW TASK" in inference.await_args.kwargs["prompt"]
    await db.refresh(review)
    assert "goal_judgement" not in review.data.get("retention_reasons", [])


@pytest.mark.parametrize("action", ["STOP", "PAUSE", "REVIEW"])
async def test_failed_review_never_completes_goal(db, monkeypatch, action):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision(action), decision(action))
    await runner.process_terminal_cycle()
    await finish_review(db, cycle, success=False)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.PAUSED and goal.completed_at is None
    assert goal.pause_reason == "REVIEW_UNAVAILABLE" and goal.next_cycle_at is None
    assert cycle.verdict == GoalVerdict.CONTINUE


async def test_critical_review_can_redirect_instead_of_completing(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    revised = "<p>The first approach failed. Improve the existing manual with concrete examples.</p>"
    model(monkeypatch, decision("STOP"), decision("CONTINUE", tracking=revised))
    await runner.process_terminal_cycle()
    await finish_review(db, cycle)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.ACTIVE and cycle.verdict == GoalVerdict.CONTINUE
    assert (await goal_service.read_markdown(goal)).tracking == revised
    assert goal.next_cycle_at is not None
    assert revised in await runner._cycle_task_objective(goal, 2)


@pytest.mark.parametrize("change", ["goal", "tracking", "work"])
async def test_changed_context_invalidates_review_and_preserves_its_cost(db, monkeypatch, change):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("STOP"), decision("STOP"), decision("CONTINUE"))
    await runner.process_terminal_cycle()
    first = await finish_review(db, cycle)
    if change == "goal":
        goal.description = "<p>Make the revised manual usable.</p>"
    elif change == "tracking":
        await get_goal_document_store().update(goal.tracking_document_id, content="<p>New constraints.</p>")
    else:
        work = await db.get(Task, cycle.task_id)
        work.feedback = "A corrected source result after another attempt."
    await db.commit()
    await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert cycle.review_task_id != first.id
    assert goal.status == GoalStatus.ACTIVE and cycle.verdict is None
    await finish_review(db, cycle, cost=0.3)
    await runner.process_terminal_cycle()
    assert cycle.task_cost == pytest.approx(0.9)


async def test_stagnation_triggers_review_but_improvement_does_not_require_news(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db, sequence=3)
    db.add_all([GoalCycle(goal_id=goal.id, sequence=n, status=GoalCycleStatus.DECIDED,
        verdict=GoalVerdict.CONTINUE, progress_changed=False) for n in (1, 2)])
    await db.commit()
    model(monkeypatch, decision(changed=False), decision(changed=True))
    await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert cycle.review_task_id is not None
    await finish_review(db, cycle)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.ACTIVE and cycle.progress_changed is True
    assert await reviews.stagnant(cycle, decision(changed=True)) is False


async def test_unknown_method_requests_review_without_recursive_reviews(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("REVIEW"), decision("REVIEW"))
    await runner.process_terminal_cycle()
    review = await finish_review(db, cycle)
    await runner.process_terminal_cycle()
    assert cycle.review_task_id == review.id
    assert goal.status == GoalStatus.ACTIVE and cycle.verdict == GoalVerdict.CONTINUE


async def test_blocker_pauses_after_review_and_explicit_resume_preserves_history(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("PAUSE"), decision("PAUSE"))
    await runner.process_terminal_cycle()
    await finish_review(db, cycle)
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.PAUSED and goal.pause_reason == "BLOCKED"
    assert goal.completed_at is None and goal.next_cycle_at is None
    monkeypatch.setattr(goal_service, "assert_referrer_available", AsyncMock())
    await goal_service.resume(goal.id, GoalCommand(expected_revision=goal.revision))
    assert goal.status == GoalStatus.ACTIVE and cycle.verdict == GoalVerdict.CONTINUE
    assert goal.next_cycle_at is not None


async def test_manual_completion_during_review_closes_without_waiting_for_it(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    inference = model(monkeypatch, decision("STOP"))
    await runner.process_terminal_cycle()
    await goal_service.complete(goal.id, GoalCommand(expected_revision=goal.revision))
    review = await db.get(Task, cycle.review_task_id)
    assert review.status == TaskStatus.ERROR
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.COMPLETED and cycle.verdict == GoalVerdict.STOP
    assert inference.await_count == 1


async def test_expired_judge_lease_recovers_without_duplicating_review(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("STOP"), decision("CONTINUE"))
    await runner.process_terminal_cycle()
    review = await finish_review(db, cycle)
    cycle.lease_token = uuid4()
    cycle.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await runner.process_terminal_cycle()
    assert cycle.review_task_id == review.id and cycle.verdict == GoalVerdict.CONTINUE
    assert goal.status == GoalStatus.ACTIVE


async def test_manual_pause_during_review_remains_authoritative(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    model(monkeypatch, decision("STOP"), decision("STOP"))
    await runner.process_terminal_cycle()
    review = await finish_review(db, cycle)
    await goal_service.pause(goal.id, GoalCommand(expected_revision=goal.revision))
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.PAUSED and goal.pause_reason == "MANUAL"
    assert goal.completed_at is None and cycle.verdict == GoalVerdict.CONTINUE
    await db.refresh(review)
    assert "goal_judgement" not in review.data.get("retention_reasons", [])


async def test_review_link_survives_notification_failure_without_duplicates(db, monkeypatch):
    goal, cycle, _ = await setup_cycle(db)
    inference = model(monkeypatch, decision("STOP"))
    monkeypatch.setattr(task_service, "publish_created", AsyncMock(side_effect=RuntimeError("Synthetic delivery outage")))
    await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert cycle.review_task_id is not None and cycle.lease_token is None
    assert cycle.status == GoalCycleStatus.JUDGING and goal.status == GoalStatus.ACTIVE
    assert not await runner.process_terminal_cycle()
    assert inference.await_count == 1


async def test_concurrent_judges_create_only_one_review(committed_database, monkeypatch):
    from core.database import get_db_session
    async with get_db_session() as session:
        goal, cycle, _ = await setup_cycle(session)
        cycle.status = GoalCycleStatus.JUDGING
        token = uuid4()
        cycle.lease_token = token
        goal_revision, cycle_id = goal.revision, cycle.id
        await session.commit()

    async def finish():
        async with get_db_session():
            await runner._finish_judgement(cycle_id, token, decision("STOP"),
                expected_goal_revision=goal_revision, cost=0.01, llm_id=None)

    await asyncio.wait_for(asyncio.gather(finish(), finish()), timeout=10)
    async with get_db_session() as session:
        cycle = await session.get(GoalCycle, cycle_id)
        tasks = list((await session.scalars(select(Task).where(Task.goal_id == goal.id))).all())
        assert len(tasks) == 2 and cycle.review_task_id in {task.id for task in tasks}
        assert cycle.judge_cost == pytest.approx(0.01)


async def test_accounting_updates_do_not_invalidate_unchanged_work(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    model(monkeypatch, decision("STOP"), decision("STOP"))
    await runner.process_terminal_cycle()
    review = await finish_review(db, cycle)
    source.cost += 0.1
    source.data = {**source.data, "synthetic_trace_accounting": True}
    await db.commit()
    await runner.process_terminal_cycle()
    assert goal.status == GoalStatus.COMPLETED and cycle.review_task_id == review.id
    assert cycle.task_cost == pytest.approx(0.7)


async def test_force_terminating_work_cancels_review_and_preserves_goal(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    model(monkeypatch, decision("STOP"))
    await runner.process_terminal_cycle()
    await task_service.force_terminate(source.id, notify_terminal=False)
    await db.refresh(cycle)
    review = await db.get(Task, cycle.review_task_id)
    assert review.status == TaskStatus.ERROR
    assert cycle.verdict == GoalVerdict.CONTINUE and goal.status == GoalStatus.ACTIVE
    assert "goal_judgement" not in review.data.get("retention_reasons", [])


async def test_provisional_work_error_does_not_start_judgement(db, monkeypatch):
    goal, cycle, source = await setup_cycle(db)
    source.status = TaskStatus.ERROR
    source.lease_token = uuid4()
    source.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    await db.commit()
    inference = model(monkeypatch, decision("CONTINUE"))
    assert not await runner.process_terminal_cycle()
    assert cycle.status == GoalCycleStatus.RUNNING and cycle.review_task_id is None
    inference.assert_not_awaited()
    source.lease_token = None
    await db.commit()
    assert await runner.process_terminal_cycle()
    assert cycle.verdict == GoalVerdict.CONTINUE and goal.status == GoalStatus.ACTIVE
