"""Pause received external conversations until their agent's manager consents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from loguru import logger
from sqlalchemy import and_, or_, select

from app.agent import Agent, get_agent_record
from app.connection import Connection
from app.messenger import (
    Interaction, Message, PermissionDecision, Room, can_request_external_contact,
    external_contact_permission_key, get_permission_decision, hydrate_messages,
    request_permission, require_incoming_contact,
)
from core.database import get_db, get_db_session
from core.i18n import current_language, render_prompt, t

from .models import ConversationRound, ConversationRoundMessage
from .schemas import ContactAuthorizationDetails


def _profile(message: Message | None) -> dict[str, str | bool]:
    raw: object = message.metadata_.get("sender_profile", {}) if message else {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in cast(dict[str, object], raw).items()
            if isinstance(value, (str, bool))}


async def pause_for_contact_authorization(message: Message, *, agent_id: int, connection_id: int) -> bool:
    """Persist the input before requesting consent; no model or external reply runs."""
    sender = message.sender
    if (sender is None or message.direction != "inbound" or message.messenger_room_id is None
            or not await can_request_external_contact(agent_id, connection_id, sender)):
        return False
    # Authority comes from the stored journal, never from a caller's hydrated payload.
    stored = await get_db().get(Message, message.id, populate_existing=True)
    if (stored is None or stored.connection_id != connection_id
            or stored.messenger_user_id != sender.id or stored.tool_id != sender.tool_id):
        return False
    from .service import admit_message
    from .facade import wake

    await admit_message(message, agent_id=agent_id, connection_id=connection_id,
        contact_permission_key=external_contact_permission_key(connection_id, sender.id), awaiting_contact=True)
    wake()
    return True


async def _inputs(round_: ConversationRound) -> list[Message]:
    rows = list(await get_db().scalars(select(Message).join(
        ConversationRoundMessage, ConversationRoundMessage.message_id == Message.id,
    ).where(ConversationRoundMessage.round_id == round_.id,
            ConversationRoundMessage.role == "input").order_by(ConversationRoundMessage.sequence)))
    return await hydrate_messages(rows)


async def contact_round_authorized(round_: ConversationRound) -> bool:
    room = await get_db().get(Room, round_.room_id)
    connection = await get_db().get(Connection, room.connection_id, populate_existing=True) if room else None
    if connection is None or not connection.active:
        return False
    messages = await _inputs(round_)
    if not messages:
        return False
    for message in messages:
        try:
            await require_incoming_contact(connection.agent_id, message, connection_id=connection.id)
        except PermissionError:
            return False
    return True


async def _request(round_: ConversationRound) -> None:
    room = await get_db().get(Room, round_.room_id)
    connection = await get_db().get(Connection, room.connection_id, populate_existing=True) if room else None
    if connection is None or not connection.active:
        return
    agent = await get_agent_record(connection.agent_id)
    if agent is None:
        return
    messages = await _inputs(round_)
    if not messages or messages[-1].sender is None:
        return
    message, sender = messages[-1], messages[-1].sender
    if not await can_request_external_contact(connection.agent_id, connection.id, sender):
        return
    key = external_contact_permission_key(connection.id, sender.id)
    if key != round_.contact_permission_key:
        return
    language = await current_language(user_id=agent.user_id)
    profile = _profile(message)
    details = "\n".join(
        f"{name}: {str(value)[:500]}"
        for name, value in profile.items()
    )
    question = render_prompt(t("messenger_contact_approval.question", language),
        name=sender.display_name or sender.external_id, identifier=sender.external_id,
        channel=message.platform, agent=f"{agent.first_name} {agent.last_name}".strip(), details=details)
    await request_permission(connection.agent_id, key, question)


async def reconcile_contact_authorizations() -> None:
    """Recover notifications and resume approved rounds after commits or a restart."""
    async with get_db_session() as db:
        now = datetime.now(timezone.utc)
        identifiers = list(await db.scalars(select(ConversationRound.id)
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Agent, Agent.id == Connection.agent_id)
        .outerjoin(PermissionDecision, and_(
            PermissionDecision.agent_id == Agent.id,
            PermissionDecision.permission_key == ConversationRound.contact_permission_key,
            PermissionDecision.approver_user_id == Agent.user_id,
            PermissionDecision.deleted_at.is_(None),
        )).outerjoin(Interaction, Interaction.id == PermissionDecision.interaction_id).where(
            ConversationRound.contact_permission_key.is_not(None), ConversationRound.status == "PAUSED",
            ConversationRound.contact_authorization_pending.is_(True),
            Connection.active.is_(True),
            or_(PermissionDecision.id.is_(None), PermissionDecision.allowed.is_not(None),
                Interaction.expires_at <= now,
                and_(PermissionDecision.interaction_id.is_(None), or_(
                    PermissionDecision.notification_after.is_(None), PermissionDecision.notification_after <= now,
                ))),
        ).order_by(ConversationRound.created_at).limit(50)))
    for identifier in identifiers:
        try:
            async with get_db_session() as db:
                round_ = await db.get(ConversationRound, identifier)
                if round_ is None or round_.status != "PAUSED" or not round_.contact_authorization_pending:
                    continue
                await _request(round_)
                # Admission locks Room before Round. Use the same order here.
                await db.scalar(select(Room.id).where(Room.id == round_.room_id).with_for_update())
                round_ = await db.scalar(select(ConversationRound).where(ConversationRound.id == identifier)
                    .with_for_update().execution_options(populate_existing=True))
                if (round_ is None or round_.status != "PAUSED" or not round_.contact_permission_key
                        or not round_.contact_authorization_pending):
                    continue
                room = await db.get(Room, round_.room_id)
                connection = await db.get(Connection, room.connection_id) if room else None
                if connection is None or not connection.active:
                    continue
                decision = await get_permission_decision(connection.agent_id, round_.contact_permission_key)
                if decision is None or decision.allowed is None:
                    continue
                if not decision.allowed:
                    round_.status, round_.delivery_state = "CANCELLED", "SKIPPED"
                    round_.finished_at = datetime.now(timezone.utc)
                elif await contact_round_authorized(round_):
                    if await db.scalar(select(ConversationRound.id).where(
                        ConversationRound.room_id == round_.room_id, ConversationRound.status == "FROZEN",
                    )) is None:
                        round_.status = "FROZEN"
                        round_.contact_authorization_pending = False
                await db.commit()
            from .facade import publish_round_activity
            await publish_round_activity(identifier)
        except Exception:
            logger.exception("Contact authorization reconciliation failed round={}", identifier)


async def contact_authorization_details(round_: ConversationRound) -> ContactAuthorizationDetails | None:
    if not round_.contact_permission_key:
        return None
    room = await get_db().get(Room, round_.room_id)
    connection = await get_db().get(Connection, room.connection_id) if room else None
    if connection is None:
        return None
    messages = await _inputs(round_)
    newest = messages[-1] if messages else None
    sender = newest.sender if newest else None
    agent = await get_agent_record(connection.agent_id)
    decision = await get_permission_decision(connection.agent_id, round_.contact_permission_key) if agent and agent.user_id else None
    return ContactAuthorizationDetails(
        permission_id=decision.id if decision else None, allowed=decision.allowed if decision else None,
        manager_user_id=agent.user_id if agent else None,
        external_id=sender.external_id if sender else "", display_name=sender.display_name if sender else "",
        profile=_profile(newest),
    )
