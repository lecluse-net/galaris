"""Memory adapter for canonical Chat document metadata."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.conversation import ConversationDocumentMetadata
from core.database import get_db

from .models import MemoryItem
from .access import readable_item_clause
from .document_service import create_document
from . import service


async def authorize_conversation_document_read(document_id: UUID, agent_id: int) -> None:
    """Check document kind and agent read access without reading or changing its content."""
    item = await service.document_record(document_id)
    if item is None:
        raise FileNotFoundError("Document not found.")
    try:
        await service.assert_item_access(item, agent_id)
    except service.MemoryPermissionError as exc:
        raise PermissionError("You do not have read access to this document.") from exc


async def resolve_conversation_document_metadata(
    document_ids: tuple[UUID, ...],
) -> dict[UUID, ConversationDocumentMetadata]:
    """Return display metadata, including tombstones referenced in Chat history."""

    if not document_ids:
        return {}
    items = (
        await get_db().scalars(
            select(MemoryItem).where(
                MemoryItem.id.in_(document_ids),
                MemoryItem.node_kind == "document",
            ).execution_options(include_historized=True)
        )
    ).all()
    return {
        item.id: ConversationDocumentMetadata(
            id=item.id,
            title="" if item.deleted_at is not None and item.title == "Forgotten memory" else item.title,
            revision=item.revision,
            updated_at=item.updated_at,
            deleted=item.deleted_at is not None,
        )
        for item in items
    }


async def resolve_conversation_room_documents(
    room_id: UUID,
    agent_id: int,
) -> tuple[ConversationDocumentMetadata, ...]:
    """List readable documents explicitly created in one Chat room."""

    items = (
        await get_db().scalars(
            MemoryItem.histo_filter(
                select(MemoryItem).where(
                    MemoryItem.node_kind == "document",
                    MemoryItem.metadata_["conversation_room_id"].astext
                    == str(room_id),
                    readable_item_clause(agent_id),
                )
            ).order_by(MemoryItem.created_at, MemoryItem.id)
        )
    ).all()
    return tuple(
        ConversationDocumentMetadata(
            id=item.id,
            title=item.title,
            revision=item.revision,
            updated_at=item.updated_at,
        )
        for item in items
    )


async def create_conversation_room_document(
    room_id: UUID,
    agent_id: int,
    title: str,
) -> ConversationDocumentMetadata:
    """Create a private empty document durably associated with one Chat room."""

    item = await create_document(
        owner_agent_id=agent_id,
        title=title,
        content="",
        task_id=None,
        keywords=[],
        metadata={"conversation_room_id": str(room_id)},
    )
    return ConversationDocumentMetadata(
        id=item.id,
        title=item.title,
        revision=item.revision,
        updated_at=item.updated_at,
    )


__all__ = [
    "authorize_conversation_document_read",
    "create_conversation_room_document",
    "resolve_conversation_document_metadata",
    "resolve_conversation_room_documents",
]
