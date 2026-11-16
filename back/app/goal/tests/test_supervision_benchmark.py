"""Current lifecycle measurements on synthetic inputs and a scripted decision boundary.

Historical before/after supervision evidence lives under artifacts/. This benchmark
uses the current closed-choice contract and reports orchestration, not provider speed.
"""

import json
from time import perf_counter
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.goal import goal_service, runner
from app.goal.models import GoalCycle, GoalCycleStatus, GoalVerdict
from app.goal.schemas import GoalDecision
from app.goal.tests.test_autonomous_goal import setup_cycle
from app.llm import StructuredInferenceResult
from app.task import Task, TaskStatus, task_service


@pytest.mark.asyncio
@pytest.mark.parametrize(("scenario", "action"), [
    ("ordinary_progress", "CONTINUE"),
    ("three_stagnant_cycles", "CONTINUE"),
    ("unknown_method", "CONTINUE"),
    ("concrete_blocker", "CONTINUE"),
    ("failed_task", "CONTINUE"),
    ("completion_without_tools", "STOP"),
    ("verified_completion", "STOP"),
])
async def test_supervision_benchmark(db, monkeypatch, scenario, action):
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())
    monkeypatch.setattr(task_service, "publish_created", AsyncMock())
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args: None)
    goal, cycle, task = await setup_cycle(db, sequence=3)
    if scenario == "three_stagnant_cycles":
        db.add_all([GoalCycle(goal_id=goal.id, sequence=n, status=GoalCycleStatus.DECIDED,
            verdict=GoalVerdict.CONTINUE, progress_changed=False) for n in (1, 2)])
    if scenario == "failed_task":
        task.status = TaskStatus.ERROR
    await db.commit()
    inference = AsyncMock(return_value=StructuredInferenceResult(
        output=GoalDecision(action=action), cost=0.01, messages=[]))
    monkeypatch.setattr(runner, "evaluate_goal", inference)
    started = perf_counter()
    assert await runner.process_terminal_cycle()
    assert not await runner.process_terminal_cycle()
    await db.refresh(goal)
    assert cycle.verdict is not None
    tasks = list(await db.scalars(select(Task).where(Task.goal_id == goal.id)))
    print("GOAL_BENCHMARK " + json.dumps({"scenario": scenario, "goal_status": goal.status.value,
        "pause_reason": goal.pause_reason, "verdict": cycle.verdict.value,
        "extra_tasks": len(tasks) - 1, "judge_calls": inference.await_count,
        "next_cycle_scheduled": goal.next_cycle_at is not None,
        "scripted_judge_cost": cycle.judge_cost, "scripted_task_cost": cycle.task_cost,
        "runtime_seconds": perf_counter() - started}, sort_keys=True))
