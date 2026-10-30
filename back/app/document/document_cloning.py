"""Prepare independent attachment identities for a document content copy."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4
from loguru import logger

from core.storage import get_attachment_storage
from core.user import HumanActor
from .schemas import DocumentAttachmentPublic


@dataclass(frozen=True)
class DocumentCloneSource:
    identity: UUID
    actor: int | HumanActor


@dataclass(frozen=True)
class PreparedDocumentClone:
    identity: UUID
    content: str
    attachments: tuple[DocumentAttachmentPublic, ...]


@asynccontextmanager
async def prepare_document_clone(source: DocumentCloneSource, content: str) -> AsyncGenerator[PreparedDocumentClone]:
    from . import document_attachment_service as attachments
    from . import resource_service as service
    identity = uuid4()
    storage = get_attachment_storage()
    copied: list[DocumentAttachmentPublic] = []
    try:
        item, _access = await service.get_item_metadata(source.identity, agent_id=source.actor)
        active = {attachment.id for attachment in attachments.attachments_from_item(item)}
        for attachment in attachments.attachments_from_item(item, include_retained=True):
            source_uri = f"document://{source.identity}/attachments/{attachment.id}"
            if attachment.id not in active and source_uri not in content:
                continue
            current, raw = await attachments.read_document_attachment(source.identity, attachment.id, actor_agent_id=source.actor)
            new_id = UUID(await storage.create(raw))
            copied.append(DocumentAttachmentPublic(id=new_id, name=current.name, media_type=current.media_type,
                size_bytes=len(raw), created_at=datetime.now(timezone.utc)))
            content = content.replace(source_uri,
                                      f"document://{identity}/attachments/{new_id}")
        yield PreparedDocumentClone(identity, content, tuple(copied))
    except BaseException:
        # Registered files may already have been committed after an interrupted response;
        # this storage API removes only bytes that have never been published.
        for attachment in copied:
            try:
                await storage.delete(str(attachment.id))
            except Exception:
                logger.exception("Unable to clean up an unpublished document attachment copy")
        raise
