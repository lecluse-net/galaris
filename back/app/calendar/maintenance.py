"""Bound disposable recurrence caches without deleting events or executions."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from loguru import logger
from core.database import get_db
from .models import CalendarEvent, CalendarOccurrence, CalendarProjectionWindow


async def prune_calendar_cache() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    removed = 0
    while True:
        candidates = select(CalendarProjectionWindow.event_id).where(CalendarProjectionWindow.built_at < cutoff).distinct().limit(100)
        events = list((await get_db().scalars(select(CalendarEvent.id).where(CalendarEvent.id.in_(candidates))
            .execution_options(include_historized=True).with_for_update(skip_locked=True))).all())
        if not events:
            break
        await get_db().execute(delete(CalendarProjectionWindow).where(CalendarProjectionWindow.event_id.in_(events),
            CalendarProjectionWindow.built_at < cutoff))
        covered = select(CalendarProjectionWindow.id).where(CalendarProjectionWindow.event_id == CalendarOccurrence.event_id,
            CalendarProjectionWindow.event_revision == CalendarOccurrence.event_revision,
            CalendarProjectionWindow.start_at <= CalendarOccurrence.end_at, CalendarProjectionWindow.end_at > CalendarOccurrence.start_at).exists()
        result = await get_db().execute(delete(CalendarOccurrence).where(CalendarOccurrence.event_id.in_(events), ~covered)
            .returning(CalendarOccurrence.id))
        removed += len(result.all())
        await get_db().commit()
    logger.info("Calendar recurrence cache pruned removed_occurrences={}", removed)
    return removed
