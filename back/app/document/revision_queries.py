"""Database projections for bounded revision history, including legacy versions."""

from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import defer

from core.database import get_db

from .models import DocumentRevision


def _content_version_ids(item_id: UUID) -> Select[tuple[UUID]]:
    history = (
        select(
            DocumentRevision.id,
            DocumentRevision.revision,
            DocumentRevision.document_content_version,
            DocumentRevision.task_id,
            DocumentRevision.content_hash,
            func.lag(DocumentRevision.content_hash)
            .over(order_by=DocumentRevision.revision)
            .label("previous_hash"),
        )
        .where(DocumentRevision.document_id == item_id)
        .subquery()
    )
    return select(history.c.id).where(
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


async def content_revision(item_id: UUID, revision: int) -> DocumentRevision | None:
    """Read one restorable version while retaining legacy predecessor semantics."""
    entry = await get_db().scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_id == item_id,
            DocumentRevision.revision == revision,
        )
    )
    if entry is None or entry.document_content_version is False:
        return None
    if entry.document_content_version is True or entry.revision == 1:
        return entry
    if entry.task_id is None:
        return None
    # The existing (item_id, revision) index also bounds this legacy lookup.
    previous_hash = await get_db().scalar(
        select(DocumentRevision.content_hash)
        .where(DocumentRevision.document_id == item_id, DocumentRevision.revision < revision)
        .order_by(DocumentRevision.revision.desc())
        .limit(1)
    )
    return entry if previous_hash is not None and entry.content_hash != previous_hash else None


async def content_revision_page(
    item_id: UUID, *, limit: int, offset: int, before_revision: int | None = None,
) -> tuple[list[DocumentRevision], int]:
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid revision pagination")
    versions = _content_version_ids(item_id)
    if before_revision is not None:
        versions = select(DocumentRevision.id).where(DocumentRevision.id.in_(versions), DocumentRevision.revision < before_revision)
    query = select(DocumentRevision).options(defer(DocumentRevision.content)).where(DocumentRevision.id.in_(versions))
    total = int(await get_db().scalar(select(func.count()).select_from(versions.subquery())) or 0)
    rows = list(
        await get_db().scalars(
            query.order_by(DocumentRevision.revision.desc()).offset(offset).limit(limit)
        )
    )
    return rows, total
