"""Read-only calendar occurrences of private memories; never schedules work."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from heapq import heapify, heappop, heappush
from typing import cast
from uuid import UUID, NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import DateTime, bindparam, func, literal, or_, select

from core.database import get_db
from core.util import local_timezone_name

from . import retrieval
from .admission import current_document_summary_clause
from .models import MemoryItem
from .query_policy import prepare_memory_read
from .schemas import MemoryRecallRequest
from .source_access import readable_source_ids
from .temporal import COMPONENTS, MemoryTemporalAnchor, next_match


type _AnchorParts = tuple[int | None, ...]
type _Candidate = tuple[datetime, UUID, UUID, int, _AnchorParts]


@lru_cache(maxsize=32_768)
def _occurrence_id(identity: UUID, lower: datetime) -> UUID:
    """Cache only a pure identity calculation, never content or authorization."""
    return uuid5(NAMESPACE_URL, f"memory://{identity}/occurrences/{lower.isoformat()}")


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
    limit: int = 10_000, include_excerpt: bool = True,
) -> MemoryAgendaWindow:
    """Expand accessible anchors over a bounded window, ordered before truncation.

    Access, current validity and contact admission are owned by Memory. A calendar
    view is a projection of current data, not an historical reconstruction.
    """
    if start.utcoffset() is None or end.utcoffset() is None or not timedelta(0) < end - start <= timedelta(days=32):
        raise ValueError("Use an ordered timezone-aware window of at most 32 days")
    if not 1 <= limit <= 10_000:
        raise ValueError("Use a limit between 1 and 10000")
    # Agenda is an independent read entry point, with the same extensive live
    # permission predicates as search. Apply its interactive planner policy
    # before the first query, even when this window contains no memories.
    await prepare_memory_read()
    connection = await get_db().connection()
    if await connection.get_isolation_level() != "READ COMMITTED":
        return MemoryAgendaWindow(items=[])
    request = MemoryRecallRequest(agent_id=agent_id, contact_item_id=contact_item_id,
        strict_contact_scope=strict_contact_scope, exclude_agent_projections=True)
    global_request, _ = retrieval._branch_requests(request, limit=min(limit, 500))  # pyright: ignore[reportPrivateUsage]
    # Build the expensive structural/source SQL once. Its timestamp is bound
    # anew at each statement, so validity and DB-backed permissions remain live.
    live_filters = retrieval._item_filters(global_request,  # pyright: ignore[reportPrivateUsage]
        now=bindparam("memory_agenda_as_of", type_=DateTime(timezone=True)))
    live_filters.append(current_document_summary_clause())
    filters = [*live_filters]
    selected: list[MemoryAgendaOccurrence] = []
    zone = local_timezone_name()
    first_day = start.astimezone(ZoneInfo(zone)).date()
    last_day = end.astimezone(ZoneInfo(zone)).date()
    dates = [first_day + timedelta(days=offset) for offset in range((last_day - first_day).days + 1)]
    # Only reject impossible candidates here. Missing components remain wildcards;
    # next_match still owns exact dates, precision, weekdays and DST behavior.
    year = MemoryItem.temporal["year"].as_integer()
    month = MemoryItem.temporal["month"].as_integer()
    day = MemoryItem.temporal["day"].as_integer()
    weekday = MemoryItem.temporal["weekday"].as_integer()
    filters.extend((or_(year.is_(None), year.between(first_day.year, last_day.year)),
        or_(month.is_(None), month.in_({value.month for value in dates})),
        or_(day.is_(None), day.in_({value.day for value in dates})),
        or_(weekday.is_(None), weekday.in_({value.isoweekday() for value in dates}))))

    @lru_cache(maxsize=128)
    def periods(parts: _AnchorParts) -> tuple[MemoryTemporalAnchor, list[tuple[datetime, datetime]]]:
        anchor = MemoryTemporalAnchor.model_validate(dict(zip(COMPONENTS, parts, strict=True)))
        result: list[tuple[datetime, datetime]] = []
        position = start
        for _ in range(limit + 1):
            match = next_match(anchor, position, end)
            if match is None or match >= end:
                break
            lower, upper = _period(anchor, match)
            result.append((lower, upper))
            position = upper
            if position >= end:
                break
        return anchor, result

    def candidate(identity: UUID, parts: _AnchorParts, index: int = 0) -> _Candidate | None:
        _anchor, matches = periods(parts)
        if index >= len(matches):
            return None
        lower, _upper = matches[index]
        occurrence_id = _occurrence_id(identity, lower)
        return lower, occurrence_id, identity, index, parts

    # Rank only identities and anchors. One pending occurrence per memory is
    # enough for a lazy chronological merge, even for dense wildcard anchors.
    # The contextual SQL session stays on this task; pure date/UUID work yields
    # the event loop to other conversations instead of blocking their requests.
    candidates: list[_Candidate] = []

    def enqueue(rows: Sequence[tuple[dict[str, object] | None, Sequence[UUID]]]) -> None:
        for temporal, identities in rows:
            if temporal is None:
                continue
            parts = cast(_AnchorParts, tuple(temporal.get(field) for field in COMPONENTS))
            _anchor, matches = periods(parts)
            if matches:
                lower, _upper = matches[0]
                candidates.extend((lower, _occurrence_id(identity, lower), identity, 0, parts) for identity in identities)

    # Repeated anchors travel once, rather than decoding the same JSON for
    # thousands of memories on every conversation round.
    statement = select(MemoryItem.temporal, func.array_agg(MemoryItem.id)).where(
        *filters, MemoryItem.temporal.is_not(None)).group_by(MemoryItem.temporal)
    stream = await get_db().stream(statement, {"memory_agenda_as_of": datetime.now(timezone.utc)})
    try:
        async for rows in stream.partitions(1000):
            await asyncio.to_thread(enqueue, [(row[0], row[1]) for row in rows])
    finally:
        await stream.close()
    await asyncio.to_thread(heapify, candidates)
    metadata: dict[UUID, tuple[str, int, _AnchorParts, str] | None] = {}
    batch_size = min(1000, max(32, limit + 1))

    def take_next_candidates(count: int) -> list[_Candidate]:
        # Consume the heap frontier instead of rescanning all remaining seeds
        # for every admission batch, including large revoked prefixes.
        return [heappop(candidates) for _ in range(min(count, len(candidates)))]

    async def admit(identities: set[UUID]) -> None:
        readable = await readable_source_ids(identities, agent_id)
        # Return current values from one fresh SQL snapshot after source-owned
        # admission. Do not hydrate ORM entities, content, URLs or search hits.
        # Reapply scope/validity so a concurrent edit or revocation cannot expose
        # a stale candidate, including an obsolete documentary summary.
        excerpt_column = func.substr(MemoryItem.search_text, 1, 1200) if include_excerpt else literal("")
        rows = (await get_db().execute(select(MemoryItem.id, MemoryItem.title, MemoryItem.revision,
            MemoryItem.temporal, excerpt_column).where(
                MemoryItem.id.in_(readable), *live_filters,
                MemoryItem.temporal.is_not(None),
            ), {"memory_agenda_as_of": datetime.now(timezone.utc)})).all()
        metadata.update(dict.fromkeys(identities))
        for identity, title, revision, temporal, excerpt in rows:
            if temporal is not None:
                metadata[identity] = title, revision, tuple(temporal.get(field) for field in COMPONENTS), excerpt

    while candidates and len(selected) <= limit:
        entry = heappop(candidates)
        _lower, occurrence_id, identity, index, parts = entry
        if identity not in metadata:
            upcoming = await asyncio.to_thread(take_next_candidates, batch_size - 1)
            pending = {row[2]: row[4] for row in [entry, *upcoming] if row[2] not in metadata}
            await admit(set(pending))
            if any(metadata[identity] is None for identity in pending):
                # A revoked/obsolete prefix must not turn into one tiny SQL
                # batch per rejected candidate. Healthy reads stay small.
                batch_size = min(1000, batch_size * 2)
            for changed_id, former_parts in pending.items():
                current = metadata[changed_id]
                if current is not None and former_parts != current[2]:
                    replacement = candidate(changed_id, current[2])
                    if replacement is not None:
                        heappush(candidates, replacement)
            # Fresh dates from the whole admission batch must take their place
            # before any occurrence is exposed, including moves into the past.
            for previous in [entry, *upcoming]:
                current = metadata[previous[2]]
                if current is not None and current[2] == previous[4]:
                    heappush(candidates, previous)
            continue
        record = metadata[identity]
        if record is None:
            continue
        title, revision, current_parts, excerpt = record
        if parts != current_parts:
            # Admission already enqueued the current anchor; discard this seed.
            continue
        anchor, matches = periods(parts)
        lower, upper = matches[index]
        selected.append(MemoryAgendaOccurrence(id=occurrence_id, memory_id=identity, uri=f"memory://{identity}",
            title=title, excerpt=excerpt, revision=revision, start=lower, end=upper,
            all_day=anchor.hour is None and anchor.minute is None, timezone=zone, temporal=anchor))
        following = candidate(identity, parts, index + 1)
        if following is not None:
            heappush(candidates, following)
    selected.sort(key=lambda item: (item.start, item.id))
    return MemoryAgendaWindow(items=selected[:limit], complete=len(selected) <= limit)
