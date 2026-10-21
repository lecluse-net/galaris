"""Document-owned Topic associations and versioned Dream sources."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.agent import AgentManagementScope
from core.database import get_db
from core.util import visible_text

from .access import readable_workflow_document_clause
from .models import Document, MemoryItem
from .storage import get_storage


async def assignment(identity: UUID, scope: AgentManagementScope) -> tuple[UUID | None, bool]:
    from .document_sharing import document_actor
    from .service import item_record, MemoryNotFoundError

    await document_actor(identity, scope)
    item = await item_record(identity, revisions=False, contents=False)
    if item is None or item.document is None or item.document.document_type != "html":
        raise MemoryNotFoundError("Document not found")
    topic_id = item.document.topic_id
    return topic_id, item.metadata_.get("topic_assignment") == {
        "origin": "manual",
        "topic_id": str(topic_id),
    }


async def change_assignment(
    identity: UUID,
    scope: AgentManagementScope,
    *,
    topic_id: UUID,
    expected_topic_id: UUID | None,
    expected_lock_version: int,
) -> int:
    from .document_sharing import document_actor
    from .service import (
        item_record,
        assert_item_access,
        MemoryConflictError,
        MemoryNotFoundError,
    )

    actor = await document_actor(identity, scope, write=True)
    # Lock in the same order as topic retirement: Topic, then resource.
    await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == identity).with_for_update())
    item = await item_record(identity, revisions=False, contents=False)
    if item is None or item.document is None or item.document.document_type != "html":
        raise MemoryNotFoundError("Document not found")
    await assert_item_access(item, actor, write=True)
    document = await get_db().scalar(
        select(Document)
        .where(Document.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if document is None:
        raise MemoryNotFoundError("Document not found")
    if item.lock_version != expected_lock_version or document.topic_id != expected_topic_id:
        raise MemoryConflictError("Document changed; reload and retry")
    document.topic_id = topic_id
    item.metadata_ = {
        **item.metadata_,
        "topic_assignment": {"origin": "manual", "topic_id": str(topic_id)},
    }
    item.lock_version += 1
    await get_db().flush()
    return item.lock_version


def _identity() -> ColumnElement[str]:
    return func.concat(
        Document.id,
        ":",
        Document.revision,
        ":",
        func.coalesce(Document.updated_at, Document.created_at),
    )


def _pending(handled: Select[tuple[str]]) -> Select[tuple[str]]:
    return (
        select(_identity())
        .join(MemoryItem, MemoryItem.id == Document.memory_item_id)
        .where(
            Document.topic_id.is_(None),
            Document.document_type == "html",
            Document.deleted_at.is_(None),
            MemoryItem.deleted_at.is_(None),
            ~_identity().in_(handled),
        )
    )


async def count_pending(handled: Select[tuple[str]]) -> int:
    return int(
        await get_db().scalar(select(func.count()).select_from(_pending(handled).subquery())) or 0
    )


async def claim_one(handled: Select[tuple[str]]) -> str | None:
    return await get_db().scalar(
        _pending(handled)
        .order_by(Document.created_at, Document.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=Document)
    )


async def source(identity: str) -> tuple[str, int | None, str | None] | None:
    row = (
        await get_db().execute(
            select(
                Document.title,
                func.left(Document.content, 80_000),
                MemoryItem.owner_agent_id,
                MemoryItem.metadata_,
                Document.provider_code,
                Document.resource_id,
            )
            .join(MemoryItem, MemoryItem.id == Document.memory_item_id)
            .where(
                _identity() == identity,
                Document.topic_id.is_(None),
                Document.deleted_at.is_(None),
                MemoryItem.deleted_at.is_(None),
                Document.document_type == "html",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    title, content, agent_id, metadata, provider, resource = row
    if content is None:
        content = (await get_storage(provider).read(resource))[:80_000].decode(
            "utf-8", errors="replace"
        )
    return (
        f"Document: {title}\n\n{visible_text(content or '')[:18_000]}",
        agent_id,
        metadata.get("language"),
    )


async def is_current(identity: str) -> bool:
    return (
        await get_db().scalar(
            select(Document.id)
            .join(MemoryItem, MemoryItem.id == Document.memory_item_id)
            .where(
                _identity() == identity,
                Document.topic_id.is_(None),
                Document.deleted_at.is_(None),
                MemoryItem.deleted_at.is_(None),
                Document.document_type == "html",
            )
        )
        is not None
    )


async def assign(identity: str, topic_id: UUID) -> bool:
    assigned = await get_db().scalar(
        update(Document)
        .where(
            _identity() == identity,
            Document.topic_id.is_(None),
            Document.deleted_at.is_(None),
            Document.document_type == "html",
            Document.memory_item_id.in_(
                select(MemoryItem.id).where(MemoryItem.deleted_at.is_(None))
            ),
        )
        .values(topic_id=topic_id)
        .returning(Document.id)
    )
    return assigned is not None


async def list_related(
    topic_ids: set[UUID],
    *,
    scope: AgentManagementScope | None = None,
    agent_ids: Collection[int] | None = None,
) -> list[tuple[UUID, UUID, str, str | None]]:
    if not topic_ids:
        return []
    query = (
        select(Document.topic_id, Document.id, Document.title, Document.filename)
        .join(
            MemoryItem,
            MemoryItem.id == Document.memory_item_id,
        )
        .where(
            Document.topic_id.in_(topic_ids),
            Document.deleted_at.is_(None),
            MemoryItem.deleted_at.is_(None),
            Document.document_type == "html",
        )
    )
    if scope is not None:
        query = query.where(readable_workflow_document_clause(scope))
    elif agent_ids is not None:
        query = query.where(MemoryItem.owner_agent_id.in_(agent_ids))
    rows = await get_db().execute(query.order_by(Document.title, Document.id))
    return [
        (topic_id, identity, title, filename)
        for topic_id, identity, title, filename in rows
        if topic_id is not None
    ]


async def reassign(source_topic_id: UUID, target_topic_id: UUID | None) -> None:
    # Include deleted resources so restoring one cannot revive a retired Topic.
    await get_db().execute(
        update(Document)
        .where(Document.topic_id == source_topic_id)
        .values(topic_id=target_topic_id)
        .execution_options(include_historized=True)
    )
