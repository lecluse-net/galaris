"""Conversation-owned scope and transport port for document presentation."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from .contracts import ConversationTurn
from .preparation import ConversationSuperseded

DocumentDisplayPublisher = Callable[[UUID, UUID], Awaitable[None]]
DocumentReadAuthorizer = Callable[[UUID, int], Awaitable[None]]
_publisher: DocumentDisplayPublisher | None = None
_authorize_read: DocumentReadAuthorizer | None = None


def register_document_read_authorizer(authorizer: DocumentReadAuthorizer) -> None:
    """Register the document domain's access check without depending on its storage."""
    global _authorize_read
    _authorize_read = authorizer


def register_document_display_publisher(publisher: DocumentDisplayPublisher) -> None:
    global _publisher
    _publisher = publisher


async def can_display_conversation_document(turn: object, agent_id: int) -> bool:
    """Require an actual internal text room belonging to this conversation's agent."""
    from app.messenger import get_agent_chat_room

    if not isinstance(turn, ConversationTurn) or turn.origin != "text" or turn.agent_id != agent_id:
        return False
    room = await get_agent_chat_room(agent_id, turn.room_id)
    return bool(room is not None and room.source is None and room.agent_id == agent_id
                and room.messenger_active and _publisher is not None and _authorize_read is not None)


async def display_conversation_document(turn: ConversationTurn, document_id: UUID) -> None:
    if not await can_display_conversation_document(turn, turn.agent_id) or _publisher is None:
        raise PermissionError("Document presentation requires an internal Chat conversation.")
    if _authorize_read is None:
        raise RuntimeError("The document provider is unavailable.")
    await _authorize_read(document_id, turn.agent_id)
    if turn.assert_fresh_before_effect is not None and not await turn.assert_fresh_before_effect():
        raise ConversationSuperseded("A newer message superseded this document presentation request.")
    await _publisher(turn.room_id, document_id)
