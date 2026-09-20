"""Database projections for bounded revision history, including legacy versions."""

from uuid import UUID

from sqlalchemy import and_, func, or_, select

from core.database import get_db

from .models import MemoryRevision


async def content_revision_page(
    item_id: UUID, *, limit: int, offset: int
) -> tuple[list[MemoryRevision], int]:
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid revision pagination")
    history = (
        select(
            MemoryRevision.id,
            MemoryRevision.revision,
            MemoryRevision.document_content_version,
            MemoryRevision.task_id,
            MemoryRevision.content_hash,
            func.lag(MemoryRevision.content_hash)
            .over(order_by=MemoryRevision.revision)
            .label("previous_hash"),
        )
        .where(MemoryRevision.item_id == item_id)
        .subquery()
    )
    versions = select(history.c.id).where(
        or_(
            history.c.document_content_version.is_(True),
            and_(
                history.c.document_content_version.is_(None),
                or_(
                    history.c.revision == 1,
                    and_(
                        history.c.task_id.is_not(None),
                        history.c.previous_hash.is_not(None),
                        history.c.content_hash != history.c.previous_hash,
                    ),
                ),
            ),
        )
    )
    query = select(MemoryRevision).where(MemoryRevision.id.in_(versions))
    total = int(await get_db().scalar(select(func.count()).select_from(versions.subquery())) or 0)
    rows = list(
        await get_db().scalars(
            query.order_by(MemoryRevision.revision.desc()).offset(offset).limit(limit)
        )
    )
    return rows, total
