"""Durable active-Task lookup for stateless runtime callbacks."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select

from core.database import get_db

from .models import Task


async def unique_leased_task_for_agent(agent_id: int) -> UUID | None:
    """Return the sole unexpired leased Task, failing closed when ambiguous."""

    now = datetime.now(timezone.utc)
    query = (
        select(Task.id)
        .where(
            Task.agent_id == agent_id,
            Task.lease_token.is_not(None),
            or_(Task.lease_expires_at.is_(None), Task.lease_expires_at > now),
        )
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(2)
    )
    task_ids = list((await get_db().scalars(Task.histo_filter(query))).all())
    return task_ids[0] if len(task_ids) == 1 else None


__all__ = ["unique_leased_task_for_agent"]
