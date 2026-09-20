"""Public Goal operations used by other application domains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from core.database import get_db

from .models import (
    Goal,
    GoalCycle,
    GoalCycleStatus,
    GoalCycleTriggerKind,
    GoalStatus,
    GoalVerdict,
)


@dataclass(frozen=True, slots=True)
class GoalOutcomeObservation:
    cycle_id: UUID
    verdict: str
    reason: str
    progress_changed: bool | None
    progress_summary: str
    evidence: tuple[str, ...]
    updated_at: datetime


async def get_goal_outcome_for_task(task_id: UUID) -> GoalOutcomeObservation | None:
    """Expose one terminal Goal judgement without leaking Goal persistence internals."""

    cycle = await get_db().scalar(
        select(GoalCycle).where(
            GoalCycle.task_id == task_id,
            GoalCycle.status == GoalCycleStatus.DECIDED,
        )
    )
    if cycle is None or cycle.verdict is None:
        return None
    return GoalOutcomeObservation(
        cycle_id=cycle.id,
        verdict=cycle.verdict.value,
        reason=cycle.reason or "",
        progress_changed=cycle.progress_changed,
        progress_summary=cycle.progress_summary or "",
        evidence=tuple(cycle.evidence),
        updated_at=cycle.updated_at,
    )


@dataclass(frozen=True)
class ForcedTaskCycle:
    """Opaque locked Goal context for one force-terminated Task."""

    goal: Goal
    cycle: GoalCycle


async def lock_cycle_for_forced_task(task_id: UUID) -> ForcedTaskCycle | None:
    """Lock an unfinished cycle and its Goal before the owning Task is locked.

    Goal judgement normally locks Goal → cycle → Task. Keeping that order here avoids
    deadlocks with a judgement that is finishing while an administrator intervenes.
    """

    db = get_db()
    row = (
        await db.execute(
            select(GoalCycle.id, GoalCycle.goal_id).where(
                GoalCycle.task_id == task_id,
                GoalCycle.verdict.is_(None),
                GoalCycle.status != GoalCycleStatus.DECIDED,
            )
        )
    ).one_or_none()
    if row is None:
        return None

    cycle_id, goal_id = row
    goal = await db.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
    if goal is None:
        return None
    cycle = await db.scalar(
        select(GoalCycle)
        .where(
            GoalCycle.id == cycle_id,
            GoalCycle.task_id == task_id,
            GoalCycle.verdict.is_(None),
            GoalCycle.status != GoalCycleStatus.DECIDED,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if cycle is None:
        return None
    return ForcedTaskCycle(goal=goal, cycle=cycle)


def close_cycle_for_forced_task(
    context: ForcedTaskCycle,
    *,
    task_cost: float,
    finished_at: datetime,
) -> UUID:
    """Close a blocked Goal cycle and preserve future Goal supervision."""

    goal = context.goal
    cycle = context.cycle
    completed_goal = goal.status == GoalStatus.COMPLETED

    cycle.status = GoalCycleStatus.DECIDED
    cycle.verdict = GoalVerdict.STOP if completed_goal else GoalVerdict.CONTINUE
    cycle.reason = (
        "The Goal was already completed when its Task was force-terminated."
        if completed_goal
        else "The cycle was skipped because its Task was force-terminated by a user."
    )
    cycle.progress_changed = False
    cycle.progress_summary = (
        "No progress was inferred from the force-terminated Task."
    )
    cycle.evidence = []
    cycle.continuation_context = None
    cycle.task_finished_at = finished_at
    cycle.task_cost = max(0.0, float(task_cost))
    cycle.judge_finished_at = finished_at
    cycle.error = None
    cycle.clear_lease()

    if not completed_goal:
        if goal.status == GoalStatus.ERROR:
            goal.status = GoalStatus.ACTIVE
            goal.pause_reason = None
        goal.completed_at = None
        goal.last_error = None
        goal.manual_run_requested_at = None
        if cycle.trigger_kind != GoalCycleTriggerKind.RELATIONAL:
            goal.next_cycle_at = (
                finished_at + timedelta(seconds=max(0, goal.cycle_delay_seconds))
                if goal.cycle_delay_seconds is not None
                else None
            )
    return goal.id


async def enqueue_children_for_forced_task(context: ForcedTaskCycle) -> None:
    """Fan out the relational trigger of a force-terminated Goal cycle."""

    from .goal_service import enqueue_child_triggers

    await enqueue_child_triggers(context.cycle)


__all__ = [
    "ForcedTaskCycle",
    "GoalOutcomeObservation",
    "close_cycle_for_forced_task",
    "enqueue_children_for_forced_task",
    "get_goal_outcome_for_task",
    "lock_cycle_for_forced_task",
]
