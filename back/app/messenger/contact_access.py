"""Contact checks at the canonical transport boundary, using persisted identities."""
from uuid import UUID
from sqlalchemy import select

from core.database import get_db
from app.agent import require_agent_contact
from app.connection import Connection
from .models import MessengerUser, RoomUser


async def require_contact_with_identity(agent_id: int, identity: MessengerUser) -> None:
    await require_agent_contact(agent_id, peer_agent_id=identity.agent_id, human_user_id=identity.galaris_user_id)


async def require_outgoing_user(connection_id: int, tool_id: int, external_id: str) -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active:
        raise PermissionError("Messaging connection is unavailable")
    identity = await get_db().scalar(select(MessengerUser).where(MessengerUser.tool_id == tool_id, MessengerUser.external_id == external_id))
    if identity is None:
        raise PermissionError("The recipient needs a verified Galaris identity before contact")
    await require_contact_with_identity(source.agent_id, identity)


async def require_outgoing_room(connection_id: int, room_id: UUID) -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active:
        raise PermissionError("Messaging connection is unavailable")
    members = (await get_db().scalars(select(MessengerUser).join(RoomUser, RoomUser.user_id == MessengerUser.id)
                                    .where(RoomUser.room_id == room_id))).all()
    others = [member for member in members if member.agent_id != source.agent_id]
    if not others:
        raise PermissionError("The room needs verified recipients before contact")
    for member in others:
        await require_contact_with_identity(source.agent_id, member)
