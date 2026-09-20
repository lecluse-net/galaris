"""Opt-in, durable admission budgets shared by a causal task tree.

Reservations belong to active Task leases, so crashes cannot strand them forever.
These are admission limits, not provider billing caps: a running phase can exceed
its estimate. All already recorded calls are charged before admitting another phase.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from core.params import runtime_settings
from core.i18n import default_language, render_prompt, t
from .models import Task
from .schemas import TaskBudget


def enabled() -> bool:
    return bool(
        runtime_settings.TASK_ROOT_MAX_TOKENS
        or runtime_settings.TASK_ROOT_MAX_COST
        or runtime_settings.TASK_ROOT_MAX_SECONDS
    )


def _message(task: Task, reason: str) -> str:
    language = str((task.data or {}).get("language") or default_language())
    return render_prompt(
        t("task_scheduler.budget_exhausted", language),
        reason=t(f"task_scheduler.budget_{reason}", language),
    )


async def _user_capacity(db: AsyncSession, task: Task, now: datetime, agent_id: int | None) -> bool:
    limit = runtime_settings.TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER
    if not limit or agent_id is None:
        return True
    from app.agent import Agent

    owner = await db.scalar(
        select(Agent.user_id).where(Agent.id == agent_id).execution_options(include_historized=True)
    )
    if owner is None:
        return False
    if not await db.scalar(select(func.pg_try_advisory_xact_lock(0x55534552, owner))):
        return False
    active = await db.scalar(
        select(func.count(Task.id))
        .join(Agent, Agent.id == Task.agent_id)
        .where(
            Agent.user_id == owner,
            Task.id != task.id,
            Task.lease_token.is_not(None),
            or_(Task.lease_expires_at.is_(None), Task.lease_expires_at > now),
        )
        .execution_options(include_historized=True)
    )
    if (active or 0) >= limit:
        task.last_error = _message(task, "user_capacity")
        task.next_attempt_at = now + timedelta(seconds=5)
        return False
    return True


async def admit(
    db: AsyncSession, task: Task, now: datetime, *, agent_id: int | None = None
) -> bool:
    """Reserve a phase under the caller's transaction; never fail existing work."""
    if not await _user_capacity(db, task, now, agent_id if agent_id is not None else task.agent_id):
        return False
    if task.last_error == _message(task, "user_capacity"):
        task.last_error = None
    if not enabled():
        return True
    try:
        root = await _root(db, task)
    except ValueError:
        task.last_error = _message(task, "cycle")
        task.next_attempt_at = now + timedelta(seconds=60)
        return False

    # Non-blocking transaction lock avoids child-row/root-row lock inversion.
    goal_id = (root.goal_id or task.goal_id) if runtime_settings.TASK_BUDGET_SHARE_GOAL else None
    lock_key = ((goal_id or root.id).int & ((1 << 63) - 1)) ^ 0x425544474554
    if not await db.scalar(select(func.pg_try_advisory_xact_lock(lock_key))):
        return False
    ids = await _lineage(db, root, goal_id)
    started_at = await _started_at(db, root, goal_id, ids)
    from app.llm.facade import aggregate_task_lineage_usage

    tokens, cost = await aggregate_task_lineage_usage(ids)
    active = await _active_leases(db, ids, now, excluding=task.id)
    limits = runtime_settings
    token_reserve = min(limits.TASK_ROOT_RESERVE_TOKENS, limits.TASK_ROOT_MAX_TOKENS)
    cost_reserve = min(limits.TASK_ROOT_RESERVE_COST, limits.TASK_ROOT_MAX_COST)
    reason = ""
    if (
        limits.TASK_ROOT_MAX_SECONDS
        and (now - started_at).total_seconds() >= limits.TASK_ROOT_MAX_SECONDS
    ):
        reason = "time"
    elif (
        limits.TASK_ROOT_MAX_TOKENS
        and tokens + (active + 1) * token_reserve > limits.TASK_ROOT_MAX_TOKENS
    ):
        reason = "tokens"
    elif (
        limits.TASK_ROOT_MAX_COST and cost + (active + 1) * cost_reserve > limits.TASK_ROOT_MAX_COST
    ):
        reason = "cost"
    if reason:
        task.last_error = _message(task, reason)
        task.next_attempt_at = now + timedelta(seconds=60)
        return False
    if task.last_error in {
        _message(task, reason) for reason in ("time", "tokens", "cost", "cycle")
    }:
        task.last_error = None
    return True


async def _root(db: AsyncSession, task: Task) -> Task:
    root = task
    seen: set[UUID] = set()
    while (parent_id := root.parent_id or root.source_task_id) is not None:
        if root.id in seen:
            raise ValueError("Cyclic task lineage")
        seen.add(root.id)
        parent = await db.get(Task, parent_id, execution_options={"include_historized": True})
        if parent is None:
            break
        root = parent

    return root


async def _lineage(db: AsyncSession, root: Task, goal_id: UUID | None) -> tuple[UUID, ...]:
    lineage = (
        select(Task.id)
        .where(Task.goal_id == goal_id if goal_id is not None else Task.id == root.id)
        .cte("budget_lineage", recursive=True)
    )
    lineage = lineage.union(
        select(Task.id).join(
            lineage,
            func.coalesce(Task.parent_id, Task.source_task_id) == lineage.c.id,
        )
    )
    return tuple(
        (await db.scalars(select(lineage.c.id).execution_options(include_historized=True))).all()
    )


async def _started_at(
    db: AsyncSession,
    root: Task,
    goal_id: UUID | None,
    ids: tuple[UUID, ...],
) -> datetime:
    started_at = root.created_at
    if goal_id is not None:
        started_at = (
            await db.scalar(
                select(func.min(Task.created_at))
                .where(Task.id.in_(ids))
                .execution_options(include_historized=True)
            )
            or started_at
        )
    return started_at


async def _active_leases(
    db: AsyncSession,
    ids: tuple[UUID, ...],
    now: datetime,
    *,
    excluding: UUID | None = None,
) -> int:
    return int(
        await db.scalar(
            select(func.count(Task.id))
            .where(
                Task.id.in_(ids),
                Task.id != excluding if excluding is not None else true(),
                Task.lease_token.is_not(None),
                or_(Task.lease_expires_at.is_(None), Task.lease_expires_at > now),
            )
            .execution_options(include_historized=True)
        )
        or 0
    )


async def inspect_budget(db: AsyncSession, task: Task) -> TaskBudget:
    """Read accounting without reserving capacity or changing the task's state."""
    from app.llm.facade import aggregate_task_lineage_usage

    root = await _root(db, task)
    limits = runtime_settings
    goal_id = (root.goal_id or task.goal_id) if limits.TASK_BUDGET_SHARE_GOAL else None
    ids = await _lineage(db, root, goal_id)
    now = datetime.now(timezone.utc)
    tokens, cost = await aggregate_task_lineage_usage(ids)
    active = await _active_leases(db, ids, now)
    reserved_tokens = active * min(limits.TASK_ROOT_RESERVE_TOKENS, limits.TASK_ROOT_MAX_TOKENS)
    reserved_cost = active * min(limits.TASK_ROOT_RESERVE_COST, limits.TASK_ROOT_MAX_COST)
    elapsed = max(0.0, (now - await _started_at(db, root, goal_id, ids)).total_seconds())
    return TaskBudget(
        enabled=enabled(),
        scope="goal" if goal_id is not None else "task_tree",
        recorded_tokens=tokens,
        recorded_cost=cost,
        active_phases=active,
        reserved_tokens=reserved_tokens,
        reserved_cost=reserved_cost,
        elapsed_seconds=elapsed,
        max_tokens=limits.TASK_ROOT_MAX_TOKENS or None,
        max_cost=limits.TASK_ROOT_MAX_COST or None,
        max_seconds=limits.TASK_ROOT_MAX_SECONDS or None,
        remaining_tokens=max(0, limits.TASK_ROOT_MAX_TOKENS - tokens - reserved_tokens)
        if limits.TASK_ROOT_MAX_TOKENS
        else None,
        remaining_cost=max(0.0, limits.TASK_ROOT_MAX_COST - cost - reserved_cost)
        if limits.TASK_ROOT_MAX_COST
        else None,
        remaining_seconds=max(0.0, limits.TASK_ROOT_MAX_SECONDS - elapsed)
        if limits.TASK_ROOT_MAX_SECONDS
        else None,
        observed_at=now,
    )
