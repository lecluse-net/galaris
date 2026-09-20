"""Persist explicitly requested image analysis on its unique attachment companion."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.util import attachment_reference, convert_to_html, visible_text

from . import service
from .contracts import SourceMemoryDocument
from .document_structure import sync_document_structure
from .models import DocumentAttachment, MemoryItem, MemoryRevision
from .safety import assert_safe_text
from .semantic_index import stage_embedding_refresh
from .storage import get_storage


async def record_attachment_description(
    uri: str, description: str, *, agent_id: int, task_id: UUID | None = None,
) -> UUID:
    """Store a successful description only while the source is still readable.

    This controlled acquisition may enrich a shared read-only attachment, but
    never grants general write access to its source document or Memory metadata.
    The acquisition commits before the tool can report a successful description.
    """
    reference = attachment_reference(uri)
    if not description.strip():
        raise ValueError("An image description cannot be empty")
    assert_safe_text(description)
    if reference is None:
        # External resources have no documentary attachment object. Preserve the
        # observation privately, with one stable identity per agent and URI.
        identity = f"{agent_id}:{hashlib.sha256(uri.encode()).hexdigest()}"
        from .document_structure import lock_structure
        await lock_structure("image_description", UUID(hashlib.sha256(identity.encode()).hexdigest()[:32]))
        filename = unquote(urlsplit(uri).path.rsplit("/", 1)[-1]) or "Image"
        item = await service.upsert_source_managed_item(SourceMemoryDocument(
            source_kind="image_description", source_ref=identity,
            owner_agent_id=agent_id, memory_item_id=None,
            title=filename[:500], memory_type="working", content=description,
            filename="", keywords=(), metadata={"resource_uri": uri,
                "task_ref": str(task_id) if task_id is not None else None},
        ))
        return item.id
    document_id, attachment_id = reference
    db = get_db()
    # Serialize against removal, ownership changes and the document's ACL edits.
    document = await db.scalar(select(MemoryItem).options(selectinload(MemoryItem.grants)).where(
        MemoryItem.id == document_id, MemoryItem.node_kind == "document",
    ).with_for_update().execution_options(populate_existing=True))
    if document is None:
        raise service.MemoryNotFoundError("Document not found")
    await service.assert_item_access(document, agent_id)
    await sync_document_structure(document)
    record = await db.scalar(select(DocumentAttachment).where(
        DocumentAttachment.id == attachment_id,
        DocumentAttachment.document_id == document_id,
        DocumentAttachment.active.is_(True),
    ))
    if record is None:
        raise service.MemoryNotFoundError("Active attachment not found")
    item = await db.scalar(select(MemoryItem).where(MemoryItem.id == record.memory_item_id).with_for_update())
    if item is None:
        raise service.MemoryNotFoundError("Attachment memory not found")
    if not str(item.metadata_.get("resource_media_type", "")).startswith("image/"):
        raise ValueError("Only image attachments accept an image description")
    return await write_attachment_description(item, description, agent_id=agent_id, task_id=task_id)


async def write_attachment_description(
    item: MemoryItem, description: str, *, agent_id: int | None, task_id: UUID | None = None,
) -> UUID:
    """Write under the caller's document/item locks, preserving the revision history."""
    db = get_db()
    assert_safe_text(description)
    if not description.strip():
        raise ValueError("An attachment description cannot be empty")
    content = convert_to_html(description, "text/markdown").encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if item.content_hash == digest:
        await db.commit()
        return item.id
    storage = get_storage("native")
    resource_id = await storage.create(content)
    try:
        item.provider_code = "native"
        item.resource_id = resource_id
        item.content_hash = digest
        item.size_bytes = len(content)
        item.search_text = visible_text(content.decode("utf-8"))
        item.revision += 1
        item.updated_at = datetime.now(timezone.utc)
        stage_embedding_refresh(item)
        db.add(MemoryRevision(
            item_id=item.id, revision=item.revision, task_id=task_id,
            provider_code=item.provider_code, resource_id=resource_id,
            content_hash=digest, content_type="text", media_type="text/html",
            content_profile_version=1, title=item.title, filename=item.filename,
            keywords=list(item.keywords), metadata_=dict(item.metadata_),
            author_agent_id=agent_id,
        ))
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete(resource_id)
        raise
    await service.invalidate_memory_views()
    return item.id
