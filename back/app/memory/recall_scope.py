"""Server-owned recall scope shared by Memory commands and virtual file searches."""

from uuid import UUID

from app.task.facade import memory_scope_for_task
from .service import projected_topic_item_id


async def resolve_recall_scope(
    *,
    agent_id: int,
    task_id: UUID | None,
    conversation_turn: object | None = None,
) -> tuple[UUID | None, UUID | None]:
    topic_id: UUID | None = None
    contact_item_id: UUID | None = None
    if task_id is not None:
        scope = await memory_scope_for_task(task_id, agent_id=agent_id)
        if scope is not None:
            topic_id, contact_item_id = scope
    elif conversation_turn is not None and getattr(conversation_turn, "agent_id", None) == agent_id:
        from app.conversation.contracts import ConversationTurn
        from app.conversation.facade import current_turn_scope

        if isinstance(conversation_turn, ConversationTurn):
            topic_id, contact_item_id = await current_turn_scope(conversation_turn)
        else:
            raw_topic = getattr(conversation_turn, "topic_id", None)
            raw_contact = getattr(conversation_turn, "contact_memory_item_id", None)
            topic_id = raw_topic if isinstance(raw_topic, UUID) else None
            contact_item_id = raw_contact if isinstance(raw_contact, UUID) else None
    return await projected_topic_item_id(topic_id), contact_item_id
