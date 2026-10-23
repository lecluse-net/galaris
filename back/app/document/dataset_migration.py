"""Public export of legacy Dataset sources; this module never writes the target."""

from app.share import ShareGrant

from typing import Any
from uuid import UUID

from sqlalchemy import select
from core.database import get_db


from .models import Document, DocumentAppGrant, DocumentAppWriteBudget, DocumentIcon, DocumentListPosition, DocumentRevision, DocumentTag, DocumentTagAssignment
from core.storage import get_storage


async def legacy_dataset_exists(identity: UUID) -> bool:
    return await get_db().scalar(select(Document.id).where(Document.id == identity, Document.document_type == "dataset")) is not None


async def legacy_dataset_ids(*, after: UUID | None = None, limit: int = 50) -> list[UUID]:
    query = select(Document.id).where(Document.document_type == "dataset").execution_options(include_historized=True)
    if after is not None:
        query = query.where(Document.id > after)
    return list(await get_db().scalars(query.order_by(Document.id).limit(limit)))


async def legacy_dataset_snapshot(identity: UUID) -> dict[str, Any]:
    db = get_db()
    item = await db.scalar(select(Document).where(Document.id == identity).with_for_update()
        .execution_options(include_historized=True, populate_existing=True))
    if item is None or item.document_type != "dataset":
        raise ValueError("Migration requires an existing Dataset source")
    if item.provider_code != "native":
        raise ValueError("Dataset migration never downloads an external resource")
    content = (await get_storage(item.provider_code).read(item.resource_id)).decode("utf-8")
    revisions: list[dict[str, Any]] = []
    rows = await db.scalars(select(DocumentRevision)
        .where(DocumentRevision.document_id == identity).order_by(DocumentRevision.revision))
    for entry in rows:
        if entry.provider_code != "native":
            raise ValueError("Dataset migration never downloads an external revision")
        revisions.append({"id": entry.id, "revision": entry.revision,
            "content": (await get_storage(entry.provider_code).read(entry.resource_id)).decode("utf-8"),
            "author_agent_id": entry.author_agent_id, "created_at": entry.created_at})
    grants: list[dict[str, Any]] = []
    for model, key in ((ShareGrant, "agent_id"), (ShareGrant, "user_id"), (ShareGrant, "team_id")):
        for grant in await db.scalars(select(model).where(ShareGrant.share_id == item.share_id, getattr(ShareGrant, key).is_not(None))):
            grants.append({key: getattr(grant, key), "can_write": grant.can_write})
    from .document_attachment_service import attachments_from_item
    attachments = [entry.model_dump(mode="python") for entry in attachments_from_item(item, include_retained=True)]
    budgets = [{"user_id": entry.user_id, "window_start": entry.window_start, "writes": entry.writes, "bytes_written": entry.bytes_written}
        for entry in await db.scalars(select(DocumentAppWriteBudget).where(DocumentAppWriteBudget.dataset_id == identity))]
    consents = [{"id": entry.id, "document_id": entry.document_id, "user_id": entry.user_id,
        "app_key": entry.app_key, "alias": entry.alias, "document_revision": entry.document_revision, "access": entry.access,
        "created_at": entry.created_at, "created_by": entry.created_by, "deleted_at": entry.deleted_at, "deleted_by": entry.deleted_by}
        for entry in await db.scalars(select(DocumentAppGrant).where(DocumentAppGrant.dataset_id == identity).execution_options(include_historized=True))]
    tag_ids = set(await db.scalars(select(DocumentTagAssignment.tag_id).where(DocumentTagAssignment.document_id == identity)))
    tags: list[dict[str, Any]] = []
    pending = list(tag_ids)
    seen: set[UUID] = set()
    while pending:
        tag_id = pending.pop()
        if tag_id in seen:
            continue
        seen.add(tag_id)
        tag = await db.scalar(select(DocumentTag).where(DocumentTag.id == tag_id).execution_options(include_historized=True))
        if tag is None:
            raise ValueError("Dataset classification source is missing")
        tags.append({"id": tag.id, "user_id": tag.user_id, "parent_id": tag.parent_id, "name": tag.name,
            "icon": tag.icon, "position": tag.position, "deleted_at": tag.deleted_at})
        if tag.parent_id is not None:
            pending.append(tag.parent_id)
    icons = {entry.user_id: entry.icon for entry in await db.scalars(select(DocumentIcon).where(DocumentIcon.document_id == identity))}
    positions = {entry.user_id: entry.position for entry in await db.scalars(select(DocumentListPosition).where(DocumentListPosition.document_id == identity))}
    return {"id": item.id, "title": item.title, "content": content, "revision": item.revision, "lock_version": item.lock_version,
        "owner_agent_id": item.owner_agent_id, "owner_user_id": item.owner_user_id, "global_access": item.global_access,
        "group_access": item.group_access, "read_only": item.read_only, "keywords": item.keywords, "metadata": item.metadata_,
        "created_at": item.created_at, "created_by": item.created_by, "updated_at": item.updated_at, "updated_by": item.updated_by,
        "deleted_at": item.deleted_at, "deleted_by": item.deleted_by,
        "revisions": revisions, "grants": grants, "attachments": attachments, "budgets": budgets, "consents": consents,
        "tags": tags, "tag_ids": tag_ids, "icons": icons, "positions": positions}
