"""Read-only Goal projections for the canonical Galaris resource namespace."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, or_, select

from app.connection import connection_service
from app.task import Task, TaskStatus
from core.database import get_db

from . import goal_service
from .models import Goal, GoalCycle
from .schemas import GoalCycleRead


async def _owner_scope(actor_agent_id: int) -> int | None:
    allowed = await connection_service.has_active_tool_connection(
        agent_id=actor_agent_id,
        tool_code="goal_management",
    )
    return None if allowed else actor_agent_id


async def read_goal_resource(
    goal_id: UUID,
    *,
    actor_agent_id: int,
) -> dict[str, Any] | None:
    goal = await goal_service.get_detail(
        goal_id,
        owner_agent_id=await _owner_scope(actor_agent_id),
    )
    if goal is None:
        return None
    payload = dict(goal.model_dump(mode="json"))
    payload["resource_uri"] = f"galaris://goal/{goal.id}"
    return payload


async def list_goal_resources(
    *,
    actor_agent_id: int,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    page = await goal_service.list_page(
        skip=max(0, offset),
        # The resource provider requests one look-ahead row after its public page of 500.
        limit=max(1, min(limit, 501)),
        agent_id=await _owner_scope(actor_agent_id),
        search=query.strip() or None,
    )
    return [
        {
            **dict(item.model_dump(mode="json")),
            "resource_uri": f"galaris://goal/{item.id}",
        }
        for item in page.items
    ]


def _cycle_payload(
    cycle: GoalCycle,
    task_label: str | None,
    task_status: TaskStatus | str | None,
    current_task_cost: float | None,
) -> dict[str, Any]:
    item = GoalCycleRead.model_validate(cycle).model_copy(
        update={
            "task_label": task_label,
            "task_status": (
                task_status.value
                if isinstance(task_status, TaskStatus)
                else str(task_status) if task_status is not None else None
            ),
            "task_cost": (
                float(current_task_cost or 0.0)
                if cycle.task_finished_at is None and current_task_cost is not None
                else float(cycle.task_cost or 0.0)
            ),
        }
    )
    payload = dict(item.model_dump(mode="json"))
    payload["resource_uri"] = f"galaris://goal_cycle/{cycle.id}"
    return payload


async def read_goal_cycle_resource(
    cycle_id: UUID,
    *,
    actor_agent_id: int,
) -> dict[str, Any] | None:
    statement = (
        select(GoalCycle, Task.label, Task.status, Task.cost)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .outerjoin(Task, Task.id == GoalCycle.task_id)
        .where(GoalCycle.id == cycle_id)
    )
    owner_agent_id = await _owner_scope(actor_agent_id)
    if owner_agent_id is not None:
        statement = statement.where(Goal.agent_id == owner_agent_id)
    row = (await get_db().execute(statement)).one_or_none()
    return _cycle_payload(*row) if row is not None else None


async def list_goal_cycle_resources(
    *,
    actor_agent_id: int,
    goal_id: UUID | None = None,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = (
        select(GoalCycle, Task.label, Task.status, Task.cost)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .outerjoin(Task, Task.id == GoalCycle.task_id)
    )
    owner_agent_id = await _owner_scope(actor_agent_id)
    if owner_agent_id is not None:
        statement = statement.where(Goal.agent_id == owner_agent_id)
    if goal_id is not None:
        statement = statement.where(GoalCycle.goal_id == goal_id)
    normalized_query = query.strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                Goal.title.ilike(pattern),
                GoalCycle.reason.ilike(pattern),
                GoalCycle.progress_summary.ilike(pattern),
                Task.label.ilike(pattern),
                cast(GoalCycle.id, String).ilike(pattern),
            )
        )
    rows = (
        await get_db().execute(
            statement
            .order_by(GoalCycle.created_at.desc(), GoalCycle.id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 501)))
        )
    ).all()
    return [_cycle_payload(*row) for row in rows]


__all__ = [
    "list_goal_cycle_resources",
    "list_goal_resources",
    "read_goal_cycle_resource",
    "read_goal_resource",
]
