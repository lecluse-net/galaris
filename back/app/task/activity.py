"""Public foreground-activity query consumed by opportunistic workers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, exists, or_, select

from core.database import get_db, get_db_session

from .models import Task, TaskStatus


async def has_active_task_work() -> bool:
    """Return whether runnable or currently leased agentic work takes priority."""

    now = datetime.now(timezone.utc)
    active_phases = (
        TaskStatus.CREATE,
        TaskStatus.DISPATCH,
        TaskStatus.BRIEFING,
        TaskStatus.EXEC,
        TaskStatus.PLAN,
    )
    async with get_db_session():
        return bool(
            await get_db().scalar(
                select(
                    exists().where(
                        Task.deleted_at.is_(None),
                        Task.status.in_(active_phases),
                        Task.paused.is_(False),
                        or_(
                            and_(
                                Task.lease_token.is_not(None),
                                Task.lease_expires_at > now,
                            ),
                            Task.next_attempt_at.is_(None),
                            Task.next_attempt_at <= now,
                        ),
                    )
                )
            )
        )


__all__ = ["has_active_task_work"]
