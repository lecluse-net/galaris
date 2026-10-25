"""Contact checks at the canonical transport boundary, using persisted identities."""
from uuid import UUID
from collections.abc import Awaitable, Callable
from sqlalchemy import select

from core.database import get_db
from app.agent import require_agent_contact
from app.connection import Connection
from .models import Message, MessengerUser, RoomUser


InboundContactAuthorizer = Callable[[int, Message], Awaitable[bool]]
_inbound_authorizers: dict[str, InboundContactAuthorizer] = {}


def register_inbound_contact_authorizer(platform: str, authorizer: InboundContactAuthorizer) -> None:
    """Let a bridge prove durable, message-specific human consent for external senders."""
    _inbound_authorizers[platform] = authorizer


async def require_incoming_contact(agent_id: int, message: Message, *, connection_id: int | None = None) -> None:
    if message.sender is not None and message.sender.agent_id is not None:
        await require_contact_with_identity(agent_id, message.sender, connection_id=connection_id)
        return
    if authorizer := _inbound_authorizers.get(message.platform or ""):
        if await authorizer(agent_id, message):
            return
        raise PermissionError("The incoming message has no valid contact authorization")
    if message.sender is None:
        raise PermissionError("The incoming message has no sender")
    await require_contact_with_identity(agent_id, message.sender, connection_id=connection_id)


async def require_peer_contact(agent_id: int, peer_agent_id: int, *, connection_id: int | None = None) -> None:
    """Check the exact channel's local policy, defaulting to native Chat for peer Tasks."""
    from app.connection.facade import get_management_scope

    scope = await get_management_scope(
        agent_id, "chat" if connection_id is None else None,
        connection_id=connection_id, default="team",
    )
    await require_agent_contact(agent_id, peer_agent_id=peer_agent_id, peer_scope=scope)


async def require_contact_with_identity(
    agent_id: int, identity: MessengerUser, *, connection_id: int | None = None,
) -> None:
    if identity.agent_id is not None:
        await require_peer_contact(agent_id, identity.agent_id, connection_id=connection_id)
    else:
        try:
            await require_agent_contact(agent_id, human_user_id=identity.galaris_user_id)
        except PermissionError:
            if connection_id is None or not await has_external_contact_permission(agent_id, connection_id, identity):
                raise


def external_contact_permission_key(connection_id: int, identity_id: UUID) -> str:
    """A manager's decision authorizes exactly one identity on one agent connection."""
    return f"messenger-contact:{connection_id}:{identity_id}"


async def can_request_external_contact(agent_id: int, connection_id: int, identity: MessengerUser) -> bool:
    from app.tools import tool_service
    from . import facade

    if identity.agent_id is not None or identity.is_ai or not identity.external_id:
        return False
    source = await get_db().get(Connection, connection_id, populate_existing=True)
    if source is None or not source.active or source.agent_id != agent_id or source.tool_id != identity.tool_id:
        return False
    tool = await tool_service.get_tool_by_id(source.tool_id)
    kind = facade.kind_for_tool(tool) if tool is not None else None
    spec = facade.get_spec(kind) if kind else None
    return bool(kind and kind != "internal" and facade.is_kind_enabled(kind)
                and spec and spec.inbound_admission == "conversation")


async def has_external_contact_permission(agent_id: int, connection_id: int, identity: MessengerUser) -> bool:
    from .permissions import get_permission_decision

    if not await can_request_external_contact(agent_id, connection_id, identity):
        return False
    try:
        decision = await get_permission_decision(agent_id, external_contact_permission_key(connection_id, identity.id))
    except PermissionError:
        return False
    return decision is not None and decision.allowed is True


async def require_outgoing_user(connection_id: int, tool_id: int, external_id: str) -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active:
        raise PermissionError("Messaging connection is unavailable")
    identity = await get_db().scalar(select(MessengerUser).where(MessengerUser.tool_id == tool_id, MessengerUser.external_id == external_id))
    if identity is None:
        raise PermissionError("The recipient needs a verified Galaris identity before contact")
    await require_contact_with_identity(source.agent_id, identity, connection_id=connection_id)


async def require_outgoing_room(connection_id: int, room_id: UUID, *, self_external_id: str = "") -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active:
        raise PermissionError("Messaging connection is unavailable")
    members = (await get_db().scalars(select(MessengerUser).join(RoomUser, RoomUser.user_id == MessengerUser.id)
                                    .where(RoomUser.room_id == room_id))).all()
    others = [member for member in members if member.agent_id != source.agent_id
              and not (member.tool_id == source.tool_id and member.external_id == self_external_id)]
    if not others:
        raise PermissionError("The room needs verified recipients before contact")
    for member in others:
        await require_contact_with_identity(source.agent_id, member, connection_id=connection_id)
