"""Bounded retention after all durable consumers have released a Process result."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import ColumnElement, Select, and_, delete, false, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from core.database import get_db
from core.params import runtime_settings
from .models import ProcessRun, ProcessRunEvent

RetentionGuard = Callable[[], Select[tuple[UUID]]]
_guards: dict[str, RetentionGuard] = {}


def register_retention_guard(key: str, guard: RetentionGuard) -> None:
    """Register a consumer at application composition, without a reverse import."""
    _guards[key] = guard


def released_trace_ids() -> Select[tuple[UUID]]:
    """Positive proof that accounting can outlive verbose provider traces."""
    from app.task import protected_task_ids

    return select(ProcessRun.id).where(
        true() if _guards else false(),
        ProcessRun.status.in_(("success", "error", "cancelled")),
        ProcessRun.finished_at.is_not(None),
        or_(ProcessRun.await_task_id.is_(None), ProcessRun.await_resolved_at.is_not(None)),
        or_(ProcessRun.task_id.is_(None), ProcessRun.task_id.not_in(protected_task_ids())),
        *(ProcessRun.id.not_in(guard()) for guard in _guards.values()),
    )


async def purge_retention(*, preview: bool = False, batch_size: int = 100) -> dict[str, int]:
    from app.task import protected_task_ids

    counts = {"raw_snapshot": 0, "events": 0, "output": 0, "runs": 0}
    # Maintenance outside the composed application must not infer that absent
    # consumers have consumed everything. It can safely wait for bootstrap.
    if not _guards:
        return counts
    policies = {
        "raw_snapshot": runtime_settings.PROCESS_RETENTION_RAW_SNAPSHOT_DAYS,
        "events": runtime_settings.PROCESS_RETENTION_EVENTS_DAYS,
        "output": runtime_settings.PROCESS_RETENTION_OUTPUT_DAYS,
        "runs": runtime_settings.PROCESS_RETENTION_RUN_DAYS,
    }
    active_policies = [days for days in policies.values() if days > 0]
    if not active_policies:
        return counts
    now = datetime.now(timezone.utc)
    db = get_db()
    active_tasks = protected_task_ids()
    eligible: list[ColumnElement[bool]] = []
    for field in ("raw_snapshot", "output"):
        if policies[field]:
            eligible.append(
                and_(
                    ProcessRun.finished_at < now - timedelta(days=policies[field]),
                    getattr(ProcessRun, field).is_not(None),
                    getattr(ProcessRun, field) != JSONB.NULL,
                )
            )
    if policies["events"]:
        eligible.append(
            select(ProcessRunEvent.id)
            .where(
                ProcessRunEvent.run_id == ProcessRun.id,
                ProcessRunEvent.created_at < now - timedelta(days=policies["events"]),
            )
            .exists()
        )
    if policies["runs"]:
        eligible.append(ProcessRun.finished_at < now - timedelta(days=policies["runs"]))
    statement = (
        select(ProcessRun)
        .where(
            ProcessRun.status.in_(("success", "error", "cancelled")),
            ProcessRun.finished_at < now - timedelta(days=min(active_policies)),
            or_(ProcessRun.await_task_id.is_(None), ProcessRun.await_resolved_at.is_not(None)),
            or_(ProcessRun.task_id.is_(None), ProcessRun.task_id.not_in(active_tasks)),
            or_(*eligible),
            *(ProcessRun.id.not_in(guard()) for guard in _guards.values()),
        )
        .order_by(ProcessRun.finished_at, ProcessRun.id)
        .limit(max(1, min(batch_size, 500)))
    )
    if not preview:
        statement = statement.with_for_update(skip_locked=True)
    rows = list(await db.scalars(statement))
    for run in rows:
        if run.finished_at is None:
            continue
        for field in ("raw_snapshot", "output"):
            days = policies[field]
            if (
                days
                and run.finished_at < now - timedelta(days=days)
                and getattr(run, field) is not None
            ):
                counts[field] += 1
                if not preview:
                    setattr(run, field, None)
        remove_run = bool(
            policies["runs"] and run.finished_at < now - timedelta(days=policies["runs"])
        )
        events_remaining = False
        if policies["events"] or remove_run:
            events = select(ProcessRunEvent.id).where(ProcessRunEvent.run_id == run.id)
            if not remove_run:
                events = events.where(
                    ProcessRunEvent.created_at < now - timedelta(days=policies["events"])
                )
            event_ids = list(await db.scalars(events.order_by(ProcessRunEvent.id).limit(501)))
            events_remaining = len(event_ids) > 500
            event_ids = event_ids[:500]
            counts["events"] += len(event_ids)
            if event_ids and not preview:
                await db.execute(delete(ProcessRunEvent).where(ProcessRunEvent.id.in_(event_ids)))
        if remove_run and not events_remaining:
            counts["runs"] += 1
            if not preview:
                await db.delete(run)
    if not preview:
        await db.commit()
        if any(counts.values()):
            logger.info("Process retention purged {}", counts)
    return counts
