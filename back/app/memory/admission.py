"""Final SQL admission of detached search results, including lexical fallback."""

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db

from .access import readable_item_clause
from .models import MemoryItem, MemoryLink, MemorySource
from .schemas import MemorySearchHit


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
    conditions: list[ColumnElement[bool]] = []
    for hit in hits:
        item = hit.item
        path_checks = [exists(select(MemoryLink.id).where(
            MemoryLink.source_item_id == step.source_item_id,
            MemoryLink.target_item_id == step.target_item_id,
            MemoryLink.relation_type == step.relation_type,
            MemoryLink.suggested.is_(False),
            MemoryLink.source_item_id.in_(visible),
            MemoryLink.target_item_id.in_(visible),
        )) for step in hit.structural_path]
        conditions.append(and_(
            MemoryItem.id == item.id,
            MemoryItem.revision == item.revision,
            MemoryItem.lock_version == item.lock_version,
            MemoryItem.content_hash == item.content_hash,
            *([MemoryItem.semantic_fingerprint == item.semantic_fingerprint] if item.semantic_fingerprint is not None else []),
            *path_checks,
        ))
    refs = select(func.array_agg(MemorySource.source_ref)).where(
        MemorySource.item_id == MemoryItem.id,
    ).correlate(MemoryItem).scalar_subquery()
    rows = (await db.execute(select(MemoryItem.id, refs).where(
        MemoryItem.id.in_(visible), or_(*conditions), *scope_filters,
    ))).all()
    admitted = {row[0]: list(row[1] or []) for row in rows}
    return [hit.model_copy(update={"source_refs": admitted[hit.item.id]})
            for hit in hits if hit.item.id in admitted and hit.item.access.can_read]
