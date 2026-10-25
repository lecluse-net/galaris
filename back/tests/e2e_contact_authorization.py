"""Synthetic external delivery into the real Conversation and permission workflow."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.connection import Connection
from app.conversation.models import ConversationRound, ConversationRoundMessage
from app.messenger import Room, dispatch_incoming, facade
from app.messenger._observations import ObservedMessengerMessage, ObservedMessengerRoom, ObservedMessengerUser
from app.tools import ToolModel
from core.database import get_db
from core.params import runtime_settings


async def seed_contact_authorization(agent_id: int) -> dict[str, object]:
    # Polling is the replaced external boundary. No fixture token can reach Telegram.
    spec = facade.get_spec("telegram")
    factory = facade.get_factory("telegram")
    assert spec is not None and factory is not None
    facade.register_bridge("telegram", factory, replace(spec, inbound_modes=[]))
    runtime_settings.MESSENGER_ENABLED_CHANNELS = '["internal","telegram"]'
    db = get_db()
    tool = ToolModel(code=f"synthetic-contact-{uuid4().hex}", label="Synthetic external contact",
        description="", connection_schema={}, messenger_config={"service": "telegram"})
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent_id, active=True)
    db.add(connection)
    await db.commit()
    await dispatch_incoming(ObservedMessengerMessage(
        id="synthetic-contact:1", platform="telegram", tool_id=tool.id,
        sender=ObservedMessengerUser(id="424200", display_name="Synthetic External Person", tool_id=tool.id,
            connection_id=connection.id, profile={"first_name": "Synthetic", "last_name": "External Person",
                "username": "synthetic_external_person", "language_code": "fr", "is_bot": False}),
        recipient=ObservedMessengerUser(id="700700", display_name="Synthetic External Bot", tool_id=tool.id,
            connection_id=connection.id, agent_id=agent_id),
        room=ObservedMessengerRoom(id="424200", kind="direct", label="Synthetic External Person",
            tool_id=tool.id, connection_id=connection.id),
        text="Synthetic external message awaiting manager consent", time=int(datetime.now(timezone.utc).timestamp()),
    ))
    round_ = await db.scalar(select(ConversationRound).join(ConversationRoundMessage).join(Room, Room.id == ConversationRound.room_id)
        .where(ConversationRound.contact_authorization_pending.is_(True), Room.connection_id == connection.id)
        .order_by(ConversationRound.created_at.desc()).limit(1))
    assert round_ is not None
    return {"external_round_id": str(round_.id), "external_name": "Synthetic External Person"}
