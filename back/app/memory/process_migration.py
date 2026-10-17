"""One-way export of former BPMN Documents to their owning Process domain."""

from app.share import ShareGrant

from typing import Any
from uuid import UUID

from sqlalchemy import select
from core.database import get_db

from .models import Document, DocumentRevision, MemoryItem, MemoryRevision
from .storage import get_storage


async def legacy_process_snapshot(identity: UUID) -> dict[str, Any]:
    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.id == identity).with_for_update()
        .execution_options(include_historized=True, populate_existing=True))
    if item is None or item.document_type != "process" or item.provider_code != "native":
        raise ValueError("Process transfer requires a native BPMN source")
    revisions: list[dict[str, Any]] = []
    rows = await get_db().scalars(select(MemoryRevision).join(DocumentRevision, DocumentRevision.id == MemoryRevision.id)
        .where(DocumentRevision.document_id == identity).order_by(DocumentRevision.revision))
    for entry in rows:
        if entry.provider_code != "native":
            raise ValueError("Process transfer never downloads external revisions")
        revisions.append({"id": entry.id, "revision": entry.revision,
            "content": (await get_storage(entry.provider_code).read(entry.resource_id)).decode("utf-8"),
            "author_agent_id": entry.author_agent_id, "created_at": entry.created_at})
    grants: list[dict[str, Any]] = []
    for model, key in ((ShareGrant, "agent_id"), (ShareGrant, "user_id"), (ShareGrant, "team_id")):
        for grant in await get_db().scalars(select(model).where(ShareGrant.share_id == item.share_id, getattr(ShareGrant, key).is_not(None))):
            grants.append({key: getattr(grant, key), "can_write": grant.can_write})
    return {"title": item.title, "content": (await get_storage(item.provider_code).read(item.resource_id)).decode("utf-8"),
        "revision": item.revision, "lock_version": item.lock_version, "owner_agent_id": item.owner_agent_id,
        "owner_user_id": item.owner_user_id, "global_access": item.global_access or (1 if item.visibility == "public" else 0),
        "group_access": item.group_access, "revisions": revisions, "grants": grants,
        "deleted_at": item.deleted_at}


async def retire_legacy_process_document(identity: UUID) -> None:
    """Archive the source in the caller's transfer transaction, without destroying it."""
    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.id == identity)
        .execution_options(include_historized=True))
    document = await get_db().scalar(select(Document).where(Document.id == identity)
        .execution_options(include_historized=True))
    if item is None or document is None or document.document_type != "process":
        raise ValueError("BPMN transfer source missing")
    if document.deleted_at is None:
        document.soft_delete()
    if item.deleted_at is None:
        item.soft_delete()
