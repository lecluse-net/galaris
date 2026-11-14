"""Read-only calendar occurrences of private memories; never schedules work."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select

from core.database import get_db
from core.util import local_timezone_name

from . import retrieval, service
from .access import effective_access_many
from .models import MemoryItem
from .schemas import MemoryRecallRequest, MemorySearchHit
from .source_access import readable_evidence_ids
from .temporal import MemoryTemporalAnchor, next_match


class MemoryAgendaOccurrence(BaseModel):
    id: UUID
    memory_id: UUID
    uri: str
    title: str
    excerpt: str
    revision: int
    start: datetime
    end: datetime
    all_day: bool
    timezone: str
    temporal: MemoryTemporalAnchor


class MemoryAgendaWindow(BaseModel):
    items: list[MemoryAgendaOccurrence]
    complete: bool = True


def _period(anchor: MemoryTemporalAnchor, instant: datetime) -> tuple[datetime, datetime]:
    """Preserve calendar precision, including local days across DST transitions."""
    local = instant.astimezone(ZoneInfo(local_timezone_name()))
    start = local.replace(second=0, microsecond=0)
    if anchor.minute is not None:
        lower = start.astimezone(timezone.utc)
        return lower, lower + timedelta(minutes=1)
    start = start.replace(minute=0)
    if anchor.hour is not None:
        lower = start.astimezone(timezone.utc)
        return lower, lower + timedelta(hours=1)
    start = start.replace(hour=0, fold=0)
    if anchor.day is not None or anchor.weekday is not None:
        end = start + timedelta(days=1)
    elif anchor.month is not None:
        start = start.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    else:
        start = start.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def memory_agenda(
    agent_id: int, start: datetime, end: datetime, *,
    contact_item_id: UUID | None = None, strict_contact_scope: bool = False,
    limit: int = 10_000,
) -> MemoryAgendaWindow:
    """Expand accessible anchors over a bounded window, ordered before truncation.

    Access, current validity and contact admission are owned by Memory. A calendar
    view is a projection of current data, not an historical reconstruction.
    """
    if start.utcoffset() is None or end.utcoffset() is None or not timedelta(0) < end - start <= timedelta(days=32):
        raise ValueError("Use an ordered timezone-aware window of at most 32 days")
    if not 1 <= limit <= 10_000:
        raise ValueError("Use a limit between 1 and 10000")
    request = MemoryRecallRequest(agent_id=agent_id, contact_item_id=contact_item_id,
        strict_contact_scope=strict_contact_scope, exclude_agent_projections=True)
    global_request, _ = retrieval._branch_requests(request, limit=min(limit, 500))  # pyright: ignore[reportPrivateUsage]
    filters = retrieval._item_filters(global_request)  # pyright: ignore[reportPrivateUsage]
    selected: list[MemoryAgendaOccurrence] = []
    cursor: UUID | None = None
    zone = local_timezone_name()
    while True:
        statement = select(MemoryItem).where(*filters, MemoryItem.temporal.is_not(None))
        if cursor is not None:
            statement = statement.where(MemoryItem.id > cursor)
        items = list(await get_db().scalars(statement.order_by(MemoryItem.id).limit(200)))
        if not items:
            break
        cursor = items[-1].id
        evidence = await readable_evidence_ids({item.id for item in items}, agent_id)
        accesses = await effective_access_many(items, agent_id, evidence_ids=evidence)
        hits = [MemorySearchHit(item=service.item_to_public(item, accesses[item.id]),
            excerpt=item.search_text[:1200], score=1.0) for item in items if item.id in evidence]
        admitted = await retrieval.admit_recall_hits(request, hits)
        for hit in admitted:
            if hit.item.temporal is None:
                continue
            anchor = hit.item.temporal
            position = start
            for _ in range(limit + 1):
                match = next_match(anchor, position, end)
                if match is None or match >= end:
                    break
                lower, upper = _period(anchor, match)
                selected.append(MemoryAgendaOccurrence(
                    id=uuid5(NAMESPACE_URL, f"memory://{hit.item.id}/occurrences/{lower.isoformat()}"),
                    memory_id=hit.item.id, uri=f"memory://{hit.item.id}", title=hit.item.title,
                    excerpt=hit.excerpt, revision=hit.item.revision, start=lower, end=upper,
                    all_day=anchor.hour is None and anchor.minute is None, timezone=zone, temporal=anchor,
                ))
                position = upper
                if position >= end:
                    break
        selected.sort(key=lambda item: (item.start, item.id))
        del selected[limit + 1:]
    return MemoryAgendaWindow(items=selected[:limit], complete=len(selected) <= limit)
