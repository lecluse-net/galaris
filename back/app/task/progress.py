"""Durable Task queue and lease-pressure telemetry."""

from datetime import datetime, timezone
import logfire
from sqlalchemy import func, or_, select
from core.database import get_db
from .models import Task, TaskStatus

_age = logfire.metric_gauge("task_oldest_ready_seconds", unit="s")
_expired = logfire.metric_gauge("task_expired_leases")


async def record_progress_metrics() -> None:
    now = datetime.now(timezone.utc)
    active = Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR))
    oldest = await get_db().scalar(
        select(func.min(Task.updated_at)).where(
            active,
            Task.paused.is_(False),
            Task.lease_token.is_(None),
            or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now),
        )
    )
    _age.set(max(0, (now - oldest).total_seconds()) if oldest else 0)
    count = await get_db().scalar(
        select(func.count(Task.id)).where(
            active,
            Task.lease_token.is_not(None),
            Task.lease_expires_at < now,
        )
    )
    _expired.set(int(count or 0))
