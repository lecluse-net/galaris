"""System maintenance of empty attachment companions; never grants access to callers.

These functions are internal worker ports, not agent tools or HTTP endpoints. The
document manifest remains authoritative, including for attachments owned by humans.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import aliased

from core.database import get_db
from core.util import visible_text

from .attachment_description import write_attachment_description
from .document_attachment_service import attachments_from_item
from .models import DocumentAttachment, MemoryItem
from .storage import NativeFileStorage, get_storage


@dataclass(frozen=True)
class AttachmentAnalysisSource:
    item_id: UUID
    attachment_id: UUID
    document_id: UUID
    revision: int
    owner_agent_id: int | None
    owner_user_id: int | None
    name: str
    media_type: str
    size_bytes: int


def empty_attachment_items() -> Select[tuple[MemoryItem]]:
    """Live, empty companions only; the manifest is rechecked before every effect."""
    document = aliased(MemoryItem)
    return select(MemoryItem).join(
        DocumentAttachment, DocumentAttachment.memory_item_id == MemoryItem.id,
    ).join(document, document.id == DocumentAttachment.document_id).where(
        MemoryItem.node_kind == "attachment", MemoryItem.size_bytes == 0,
        MemoryItem.deleted_at.is_(None), DocumentAttachment.active.is_(True),
        document.deleted_at.is_(None),
    )


async def attachment_analysis_source(item_id: UUID) -> AttachmentAnalysisSource | None:
    db = get_db()
    item = await db.get(MemoryItem, item_id, populate_existing=True)
    if item is None or item.deleted_at is not None or item.node_kind != "attachment" or item.size_bytes != 0:
        return None
    record = await db.scalar(select(DocumentAttachment).where(
        DocumentAttachment.memory_item_id == item_id, DocumentAttachment.active.is_(True),
    ))
    if record is None:
        return None
    document = await db.get(MemoryItem, record.document_id, populate_existing=True)
    if document is None or document.deleted_at is not None:
        return None
    attachment = next((value for value in attachments_from_item(document) if value.id == record.id), None)
    if attachment is None:
        return None
    return AttachmentAnalysisSource(
        item.id, record.id, document.id, item.revision, document.owner_agent_id,
        document.owner_user_id, attachment.name, attachment.media_type, attachment.size_bytes,
    )


async def attachment_analysis_path(source: AttachmentAnalysisSource, *, max_bytes: int) -> Path:
    """Resolve only the validated native attachment, never a caller-supplied path."""
    if await attachment_analysis_source(source.item_id) != source:
        raise ValueError("Attachment is no longer eligible for analysis")
    storage = get_storage("native")
    if not isinstance(storage, NativeFileStorage):
        raise ValueError("Attachment analysis requires native storage")
    path = await storage.path_for_read(str(source.attachment_id))
    if source.size_bytes > max_bytes or path.stat().st_size > max_bytes:
        raise ValueError("Attachment exceeds the analysis size limit")
    return path


async def fill_attachment_description(source: AttachmentAnalysisSource, description: str) -> bool:
    """Compare and fill atomically; removal, ownership changes and prior text win."""
    db = get_db()
    document = await db.scalar(select(MemoryItem).where(
        MemoryItem.id == source.document_id,
    ).with_for_update().execution_options(populate_existing=True))
    if document is None:
        return False
    item = await db.scalar(select(MemoryItem).where(
        MemoryItem.id == source.item_id,
    ).with_for_update().execution_options(populate_existing=True))
    if item is None or await attachment_analysis_source(source.item_id) != source:
        return False
    content = await get_storage(item.provider_code).read(item.resource_id)
    if content.strip() or not visible_text(description).strip():
        return False
    await write_attachment_description(item, description, agent_id=None)
    return True
