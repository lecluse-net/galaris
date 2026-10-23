"""Recent private memories, independently of the document library."""
from collections.abc import Collection
from datetime import datetime, timezone
from sqlalchemy import or_, select
from sqlalchemy.orm import defer
from core.database import get_db
from .access import readable_item_for_agents_clause
from .models import MemoryItem
from .schemas import RecentMemoryItem

async def list_recent_memories(
    *,
    managed_agent_ids: Collection[int] | None,
    limit: int,
) -> list[RecentMemoryItem]:
    """Return recent readable memories without loading their governed payloads."""

    now = datetime.now(timezone.utc)
    rows = list(
        (
            await get_db().scalars(
                select(MemoryItem)
                .options(defer(MemoryItem.memory_content))
                .where(
                    readable_item_for_agents_clause(managed_agent_ids),
                    MemoryItem.node_kind == "memory",
                    or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
                    or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
                )
                .order_by(MemoryItem.created_at.desc(), MemoryItem.id.desc())
                .limit(limit)
            )
        ).all()
    )
    return [
        RecentMemoryItem(
            id=item.id,
            title=item.title,
            created_at=item.created_at,
        )
        for item in rows
    ]
