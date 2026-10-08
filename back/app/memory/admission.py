"""Final SQL admission of detached search results, including lexical fallback."""

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import Integer, Text, Uuid, bindparam, column, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db

from .access import readable_item_clause
from .models import MemoryItem, MemoryLink, MemorySource
from .schemas import MemorySearchHit
from .source_access import source_is_readable


async def admit_search_hits(
    agent_id: int, hits: Sequence[MemorySearchHit],
    *, scope_filters: Sequence[ColumnElement[bool]] = (),
) -> list[MemorySearchHit]:
    """Admit at a fresh READ COMMITTED statement snapshot, never from ORM state.

    A changed result is omitted, not relabelled with a newer revision. Every
    exposed traversal endpoint and edge must still be visible at that snapshot.
    Revocations committed after this statement apply to subsequent admissions.
    """
    if not hits:
        return []
    hits = [hit for hit in hits if await source_is_readable(
        hit.item.id, hit.item.managed_source_kind, agent_id,
    )]
    if not hits:
        return []
    db = get_db()
    connection = await db.connection()
    if await connection.get_isolation_level() != "READ COMMITTED":
        # A repeatable-read snapshot cannot prove current authorization.
        return []
    now = datetime.now(timezone.utc)
    visible = select(MemoryItem.id).where(
        readable_item_clause(agent_id),
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
    ).correlate(None)
    # Overlapping pages may carry the same UUID with different revisions or
    # paths. A valid occurrence must never authorize another occurrence.
    # Bind the batch as data, keeping the SQL shape and its compilation cache
    # independent of page size. A large OR/VALUES tree makes planning dominate
    # admission even when every candidate is a direct result.
    snapshots = [dict(ordinal=index, item_id=str(hit.item.id), revision=hit.item.revision,
                      lock_version=hit.item.lock_version, content_hash=hit.item.content_hash,
                      semantic_fingerprint=hit.item.semantic_fingerprint)
                 for index, hit in enumerate(hits)]
    candidates = func.jsonb_to_recordset(bindparam("admission_snapshots", snapshots, type_=JSONB)).table_valued(
        column("ordinal", Integer), column("item_id", Uuid(as_uuid=True)),
        column("revision", Integer), column("lock_version", Integer),
        column("content_hash", Text), column("semantic_fingerprint", Text),
    ).render_derived(name="memory_admission_candidates", with_types=True)
    path_filters: list[ColumnElement[bool]] = []
    paths = [dict(ordinal=index, source_item_id=str(step.source_item_id),
                  target_item_id=str(step.target_item_id), relation_type=step.relation_type)
             for index, hit in enumerate(hits) for step in hit.structural_path]
    if paths:
        steps = func.jsonb_to_recordset(bindparam("admission_paths", paths, type_=JSONB)).table_valued(
            column("ordinal", Integer), column("source_item_id", Uuid(as_uuid=True)),
            column("target_item_id", Uuid(as_uuid=True)), column("relation_type", Text),
        ).render_derived(name="memory_admission_steps", with_types=True)
        readable_edge = exists(select(MemoryLink.id).where(
            MemoryLink.source_item_id == steps.c.source_item_id,
            MemoryLink.target_item_id == steps.c.target_item_id,
            MemoryLink.relation_type == steps.c.relation_type,
            MemoryLink.suggested.is_(False),
            MemoryLink.source_item_id.in_(visible),
            MemoryLink.target_item_id.in_(visible),
        ).correlate(steps))
        path_filters.append(~exists(select(steps.c.ordinal).where(
            steps.c.ordinal == candidates.c.ordinal, ~readable_edge,
        ).correlate(candidates)))
    refs = select(func.array_agg(MemorySource.source_ref)).where(
        MemorySource.item_id == MemoryItem.id,
    ).correlate(MemoryItem).scalar_subquery()
    rows = (await db.execute(select(candidates.c.ordinal, refs).select_from(MemoryItem).join(
        candidates, MemoryItem.id == candidates.c.item_id,
    ).where(
        MemoryItem.id.in_(visible),
        MemoryItem.revision == candidates.c.revision,
        MemoryItem.lock_version == candidates.c.lock_version,
        MemoryItem.content_hash == candidates.c.content_hash,
        or_(candidates.c.semantic_fingerprint.is_(None),
            MemoryItem.semantic_fingerprint == candidates.c.semantic_fingerprint),
        *path_filters, *scope_filters,
    ))).all()
    admitted = {row[0]: list(row[1] or []) for row in rows}
    return [hit.model_copy(update={"source_refs": admitted[index]})
            for index, hit in enumerate(hits) if index in admitted and hit.item.access.can_read]
