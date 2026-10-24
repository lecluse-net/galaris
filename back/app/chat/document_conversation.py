"""Personal Document/Chat selection, independent of document content and sharing."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agent import AgentManagementScope
from app.document import item_record
from app.document.interface import document_access, managed_agents
from app.messenger import get_chat_room
from core.database import get_db
from core.user import HumanActor

from .models import ChatDocumentConversation


async def _require_document(document_id: UUID, scope: AgentManagementScope) -> None:
    document = await item_record(document_id, revisions=False, contents=False)
    if document is None or document.node_kind != "document" or document.document_type != "html":
        raise FileNotFoundError("Document not found.")
    human = await document_access(document_id, HumanActor(scope.user_id))
    if human.can_read:
        return
    readable, _ = await managed_agents(document_id, scope.agent_ids)
    if not readable:
        raise PermissionError("Document access denied.")


async def read_document_conversation(document_id: UUID, scope: AgentManagementScope) -> UUID | None:
    await _require_document(document_id, scope)
    room_id = await get_db().scalar(select(ChatDocumentConversation.room_id).where(
        ChatDocumentConversation.document_id == document_id,
        ChatDocumentConversation.user_id == scope.user_id,
    ))
    if room_id is None:
        return None
    room = await get_chat_room(scope.user_id, room_id)
    return room_id if room is not None and room.conversation_type == "text" else None


async def write_document_conversation(
    document_id: UUID, room_id: UUID | None, scope: AgentManagementScope,
) -> UUID | None:
    await _require_document(document_id, scope)
    if room_id is not None:
        room = await get_chat_room(scope.user_id, room_id)
        if room is None or room.conversation_type != "text":
            raise PermissionError("Conversation access denied.")
    await get_db().execute(insert(ChatDocumentConversation).values(
        document_id=document_id, user_id=scope.user_id, room_id=room_id,
    ).on_conflict_do_update(
        constraint="uq_chat_document_conversation_user", set_={"room_id": room_id},
    ))
    await get_db().commit()
    return room_id
