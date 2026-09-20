"""Public read-only observations derived from auditable memory usage."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from core.database import get_db

from .contracts import MemoryUsageObservation
from .models import MemoryItem, MemoryUsage


async def list_task_memory_usages(
    task_id: UUID, *, agent_id: int
) -> tuple[MemoryUsageObservation, ...]:
    """Return owner-scoped memories that were actually injected or read for a Task."""

    rows = (
        await get_db().execute(
            select(MemoryUsage, MemoryItem.metadata_)
            .join(MemoryItem, MemoryItem.id == MemoryUsage.item_id)
            .where(
                MemoryUsage.task_id == task_id,
                MemoryUsage.agent_id == agent_id,
                MemoryItem.owner_agent_id == agent_id,
            )
            .order_by(MemoryUsage.created_at, MemoryUsage.id)
        )
    ).all()
    return tuple(
        MemoryUsageObservation(
            memory_id=usage.item_id,
            access_kind=usage.access_kind,
            memory_role=str(metadata.get("memory_role") or "ordinary"),
            created_at=usage.created_at,
        )
        for usage, metadata in rows
    )


__all__ = ["list_task_memory_usages"]
