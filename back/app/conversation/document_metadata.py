"""Provider-neutral metadata lookup for working documents projected in Chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConversationDocumentMetadata:
    """Canonical display metadata for one referenced working document."""

    id: UUID
    title: str
    revision: int
    updated_at: datetime | None
    deleted: bool = False


ConversationDocumentMetadataResolver = Callable[
    [tuple[UUID, ...]],
    Awaitable[Mapping[UUID, ConversationDocumentMetadata]],
]
ConversationRoomDocumentResolver = Callable[
    [UUID, int],
    Awaitable[tuple[ConversationDocumentMetadata, ...]],
]
ConversationRoomDocumentCreator = Callable[
    [UUID, int, str],
    Awaitable[ConversationDocumentMetadata],
]

_resolver: ConversationDocumentMetadataResolver | None = None
_room_resolver: ConversationRoomDocumentResolver | None = None
_room_creator: ConversationRoomDocumentCreator | None = None


def register_conversation_document_metadata_resolver(
    resolver: ConversationDocumentMetadataResolver,
) -> None:
    """Register the storage-owned metadata resolver at application bootstrap."""

    global _resolver
    _resolver = resolver


async def resolve_conversation_document_metadata(
    document_ids: tuple[UUID, ...],
) -> Mapping[UUID, ConversationDocumentMetadata]:
    """Resolve canonical metadata, or fail open when no provider is active."""

    if _resolver is None or not document_ids:
        return {}
    return await _resolver(document_ids)


def register_conversation_room_document_resolver(
    resolver: ConversationRoomDocumentResolver,
) -> None:
    global _room_resolver
    _room_resolver = resolver


def register_conversation_room_document_creator(
    creator: ConversationRoomDocumentCreator,
) -> None:
    global _room_creator
    _room_creator = creator


async def resolve_conversation_room_documents(
    room_id: UUID,
    agent_id: int,
) -> tuple[ConversationDocumentMetadata, ...]:
    if _room_resolver is None:
        return ()
    return await _room_resolver(room_id, agent_id)


async def create_conversation_room_document(
    room_id: UUID,
    agent_id: int,
    title: str,
) -> ConversationDocumentMetadata:
    if _room_creator is None:
        raise RuntimeError("The document provider is unavailable.")
    return await _room_creator(room_id, agent_id, title)


__all__ = [
    "ConversationDocumentMetadata",
    "ConversationDocumentMetadataResolver",
    "ConversationRoomDocumentCreator",
    "ConversationRoomDocumentResolver",
    "create_conversation_room_document",
    "register_conversation_document_metadata_resolver",
    "register_conversation_room_document_creator",
    "register_conversation_room_document_resolver",
    "resolve_conversation_room_documents",
    "resolve_conversation_document_metadata",
]
