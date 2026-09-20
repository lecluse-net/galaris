"""Read-only Task projections for the canonical Galaris resource namespace."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, or_, select

from core.database import get_db

from .models import Task, TaskAmendment
from .schemas import Task as TaskSchema
from .access import agent_task_filter


async def read_task_resource(
    task_id: UUID,
    *,
    actor_agent_id: int,
) -> dict[str, Any] | None:
    """Return one complete Task snapshot visible to its owner or requester."""

    task = await get_db().scalar(
        Task.histo_filter(
            select(Task).where(
                Task.id == task_id,
                await agent_task_filter(actor_agent_id),
            )
        )
    )
    if task is None:
        return None
    payload = TaskSchema.model_validate(task).model_dump(mode="json")
    payload["resource_uri"] = f"galaris://task/{task.id}"
    return payload


async def list_task_resources(
    *,
    actor_agent_id: int,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return bounded Task summaries visible to one agent."""

    statement = select(
        Task.id,
        Task.revision,
        Task.label,
        Task.objective,
        Task.status,
        Task.paused,
        Task.agent_id,
        Task.requester_agent_id,
        Task.created_at,
        Task.updated_at,
    ).where(await agent_task_filter(actor_agent_id))
    normalized_query = query.strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                Task.label.ilike(pattern),
                Task.objective.ilike(pattern),
                Task.feedback.ilike(pattern),
                cast(Task.id, String).ilike(pattern),
            )
        )
    statement = Task.histo_filter(
        statement
        .order_by(Task.updated_at.desc(), Task.created_at.desc(), Task.id.desc())
        .offset(max(0, offset))
        # The resource provider requests one look-ahead row after its public page of 500.
        .limit(max(1, min(limit, 501)))
    )
    rows = (await get_db().execute(statement)).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "revision": int(row["revision"] or 1),
            "label": str(row["label"] or ""),
            "objective": str(row["objective"] or ""),
            "status": row["status"].value,
            "paused": bool(row["paused"]),
            "agent_id": row["agent_id"],
            "requester_agent_id": row["requester_agent_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "resource_uri": f"galaris://task/{row['id']}",
        }
        for row in rows
    ]


async def list_task_amendments_by_source(
    source_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Return immutable amendment lineage for exact conversation source identifiers."""

    normalized = tuple(
        dict.fromkeys(value.strip() for value in source_ids if value.strip())
    )
    if not normalized:
        return []
    rows = list(
        (
            await get_db().scalars(
                select(TaskAmendment)
                .where(TaskAmendment.source_id.in_(normalized))
                .order_by(TaskAmendment.created_at, TaskAmendment.id)
            )
        ).all()
    )
    return [
        {
            "id": str(item.id),
            "task_id": str(item.task_id),
            "task_uri": f"galaris://task/{item.task_id}",
            "source_kind": item.source_kind,
            "source_id": item.source_id,
            "disposition": item.disposition,
            "instruction": item.instruction,
            "reason": item.reason,
            "created_at": item.created_at.isoformat(),
            "applied_at": item.applied_at.isoformat(),
        }
        for item in rows
    ]


__all__ = [
    "list_task_amendments_by_source",
    "list_task_resources",
    "read_task_resource",
]
