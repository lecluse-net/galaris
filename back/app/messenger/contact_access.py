"""Contact checks at the canonical transport boundary, using persisted identities."""
from uuid import UUID
from collections.abc import Awaitable, Callable
from sqlalchemy import select

from core.database import get_db
from app.agent import AgentScopeDeniedError, require_agent_contact
from app.connection import Connection
from .models import Message, MessengerUser, RoomUser


InboundContactAuthorizer = Callable[[int, Message], Awaitable[bool]]
_inbound_authorizers: dict[str, InboundContactAuthorizer] = {}


def register_inbound_contact_authorizer(platform: str, authorizer: InboundContactAuthorizer) -> None:
    """Let a bridge prove durable, message-specific human consent for external senders."""
    _inbound_authorizers[platform] = authorizer


async def require_incoming_contact(agent_id: int, message: Message, *, connection_id: int | None = None) -> None:
    identity = message.sender
    if identity is not None and identity.agent_id is not None:
        destination = await get_db().get(Connection, connection_id, populate_existing=True) if connection_id is not None else None
        if destination is None or destination.agent_id != agent_id:
            raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")
        source = await _peer_connection(destination, identity)
        await _require_peer_exchange(
            source.agent_id, agent_id, sender_connection_id=source.id, recipient_connection_id=destination.id,
        )
        return
    if authorizer := _inbound_authorizers.get(message.platform or ""):
        if await authorizer(agent_id, message):
            return
        raise PermissionError("The incoming message has no valid contact authorization")
    if identity is None:
        raise PermissionError("The incoming message has no sender")
    await _require_human_contact(agent_id, identity, connection_id=connection_id)


async def _peer_connection(connection: Connection, identity: MessengerUser) -> Connection:
    """Resolve the verified peer on the same Service as this endpoint."""
    from app.connection.facade import get_connection_by_agent_service

    if identity.agent_id is None or identity.service_id != connection.service_id:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")
    try:
        peer = await get_connection_by_agent_service(connection.service_id, identity.agent_id)
    except ValueError as exc:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy") from exc
    if peer is None:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")
    return peer


async def _require_peer_exchange(
    sender_id: int, recipient_id: int, *,
    sender_connection_id: int | None, recipient_connection_id: int | None,
) -> None:
    from app.connection.facade import get_management_scope

    sender_scope = await get_management_scope(
        sender_id, "chat" if sender_connection_id is None else None,
        connection_id=sender_connection_id, default="team",
    )
    await require_agent_contact(sender_id, peer_agent_id=recipient_id, peer_scope=sender_scope)
    recipient_scope = await get_management_scope(
        recipient_id, "chat" if recipient_connection_id is None else None,
        connection_id=recipient_connection_id, default="team",
    )
    if recipient_scope not in {"team", "all"}:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")


async def require_internal_peer_contact(
    agent_id: int, peer_agent_id: int, *, connection_id: int | None = None,
) -> None:
    """Apply the shared peer policy to native Chat's Task-backed delivery."""
    from app.services import ServiceModel
    from .configuration import messenger_connection_active

    active = dict((await get_db().execute(
        select(Connection.agent_id, Connection.id).join(ServiceModel, ServiceModel.id == Connection.service_id)
        .where(ServiceModel.code == "chat", Connection.agent_id.in_((agent_id, peer_agent_id)),
               messenger_connection_active()),
    )).tuples().all())
    sender = active.get(agent_id)
    recipient = active.get(peer_agent_id)
    if sender is None or recipient is None or connection_id not in {None, sender}:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")
    await _require_peer_exchange(
        agent_id, peer_agent_id, sender_connection_id=sender, recipient_connection_id=recipient,
    )


async def _require_outgoing_contact(source: Connection, identity: MessengerUser) -> None:
    if identity.agent_id is not None:
        destination = await _peer_connection(source, identity)
        await _require_peer_exchange(
            source.agent_id, destination.agent_id, sender_connection_id=source.id, recipient_connection_id=destination.id,
        )
    else:
        await _require_human_contact(source.agent_id, identity, connection_id=source.id)


async def _require_human_contact(agent_id: int, identity: MessengerUser, *, connection_id: int | None) -> None:
    try:
        await require_agent_contact(agent_id, human_user_id=identity.galaris_user_id)
    except PermissionError:
        if connection_id is None or not await has_external_contact_permission(agent_id, connection_id, identity):
            raise


def external_contact_permission_key(connection_id: int, identity_id: UUID) -> str:
    """A manager's decision authorizes exactly one identity on one agent connection."""
    return f"messenger-contact:{connection_id}:{identity_id}"


async def can_request_external_contact(agent_id: int, connection_id: int, identity: MessengerUser) -> bool:
    from app.services import service
    from . import facade

    if identity.agent_id is not None or identity.is_ai or not identity.external_id:
        return False
    source = await get_db().get(Connection, connection_id, populate_existing=True)
    if source is None or not source.active or source.agent_id != agent_id or source.service_id != identity.service_id:
        return False
    tool = await service.get_service_by_id(source.service_id)
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


async def require_outgoing_user(connection_id: int, service_id: int, external_id: str) -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active or source.service_id != service_id:
        raise PermissionError("Messaging connection is unavailable")
    identity = await get_db().scalar(select(MessengerUser).where(MessengerUser.service_id == service_id, MessengerUser.external_id == external_id))
    if identity is None:
        raise PermissionError("The recipient needs a verified Galaris identity before contact")
    await _require_outgoing_contact(source, identity)


async def require_outgoing_room(connection_id: int, room_id: UUID, *, self_external_id: str = "") -> None:
    source = await get_db().scalar(select(Connection).where(Connection.id == connection_id))
    if source is None or not source.active:
        raise PermissionError("Messaging connection is unavailable")
    members = (await get_db().scalars(select(MessengerUser).join(RoomUser, RoomUser.user_id == MessengerUser.id)
                                    .where(RoomUser.room_id == room_id))).all()
    others = [member for member in members if member.agent_id != source.agent_id
              and not (member.service_id == source.service_id and member.external_id == self_external_id)]
    if not others:
        raise PermissionError("The room needs verified recipients before contact")
    for member in others:
        await _require_outgoing_contact(source, member)
