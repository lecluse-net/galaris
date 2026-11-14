"""Versioned keyword replacement for the documents selected in the library."""

from sqlalchemy import select
from sqlalchemy.orm import defer, raiseload

from app.agent import AgentManagementScope
from core import websocket
from core.database import get_db

from .document_sharing import document_actor
from .lifecycle import notify_document
from .models import Document
from .resource_service import DocumentConflictError, DocumentNotFoundError, DocumentPermissionError, assert_item_access, replace_document_keywords
from .schemas import DocumentKeywordChange


async def replace_keywords(data: DocumentKeywordChange, scope: AgentManagementScope) -> None:
    versions = {value.id: value.expected_lock_version for value in data.documents}
    replacements: list[tuple[Document, list[str]]] = []
    source = {value.casefold() for value in data.source_keywords}
    db = get_db()
    # Authorize before taking locks, then lock in the same UUID order as the
    # individual writers. Rights and versions are checked again under those locks.
    actors = {identity: await document_actor(identity, scope, write=True) for identity in sorted(versions)}
    records = {item.id: item for item in await db.scalars(select(Document).options(
        defer(Document.content), defer(Document.summary_content), raiseload("*"),
    ).where(Document.id.in_(versions)).order_by(Document.id).with_for_update().execution_options(populate_existing=True))}
    for identity in sorted(versions):
        item = records.get(identity)
        if item is None:
            raise DocumentNotFoundError("Document not found")
        await assert_item_access(item, actors[identity], write=True)
        if item.read_only or item.source_managed:
            raise DocumentPermissionError("A protected document cannot change keywords")
        if item.lock_version != versions[identity]:
            raise DocumentConflictError("Document changed; reload and retry")
        keywords = [value for value in item.keywords if value.casefold() not in source]
        if data.keyword is not None and data.keyword.casefold() not in {value.casefold() for value in keywords}:
            keywords.append(data.keyword)
        if len(keywords) > 50:
            raise DocumentConflictError("A document cannot have more than 50 keywords")
        replacements.append((item, keywords))
    # Validate the complete batch before changing any record.
    changed: list[Document] = []
    for item, keywords in replacements:
        if keywords == item.keywords:
            continue
        replace_document_keywords(item, keywords)
        item.lock_version += 1
        changed.append(item)
    await db.commit()
    for item in changed:
        await websocket.emit("document", "update", {"id": str(item.id), "node_kind": "document"}, None)
        await notify_document(item.id, "index")
        await notify_document(item.id, "update")
