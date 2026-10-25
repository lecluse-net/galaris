"""External receipt is observable before a manager authorizes any agent response."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from telegram import Message as TelegramMessage, Update, User

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionParam
from app.conversation import monitoring_service
from app.conversation.contact_authorization import reconcile_contact_authorizations
from app.conversation.contracts import ConversationControlConflict, ConversationOutcome
from app.conversation.models import ConversationRound, ConversationRoundMessage
from app.conversation.service import build_turn, claim_next_round, complete_round, control_round, mark_effect_if_fresh
from app.messenger import create_internal_room, service
from app.messenger.contact_access import require_outgoing_room
from app.messenger.models import Interaction, Message, MessengerUser, PermissionDecision, Room
from app.messenger.permissions import answer_permission, delete_decision, list_decisions
from app.tools import ToolModel
from bridge.telegram.messenger import TelegramMessenger
from bridge.telegram.schemas import TelegramConnectionConfig
from core.authorize import Assignment, Privilege, Role
from core.params import runtime_settings
from core.user import UserModel


async def _scope(db, monkeypatch):
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", '["internal","telegram"]')
    service.register_messaging()
    suffix = uuid4().hex
    manager = UserModel(email=f"contact-manager-{suffix}@example.test", hashed_password="unused", is_active=True, language="en")
    outsider = UserModel(email=f"contact-outsider-{suffix}@example.test", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic contact consent", gender="X")
    role = Role(code=f"contact-reviewer-{suffix}", privileges=[await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))])
    tool = ToolModel(code=f"contact-channel-{suffix}", label="Synthetic Telegram", description="", connection_schema={},
                     messenger_config={"service": "telegram", "param_map": {"token": "token"}}, conversation_enabled=True)
    db.add_all([manager, outsider, title, role, tool])
    await db.flush()
    db.add_all([Assignment(user_id=u.id, role_id=role.id) for u in (manager, outsider)])
    agent = Agent(user_id=manager.id, title_id=title.id, code=f"contact-agent-{suffix}", first_name="Synthetic", last_name="Agent", agent_driver="internal")
    db.add(agent)
    await db.flush()
    chat = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
    db.add_all([connection, Connection(agent_id=agent.id, tool_id=chat.id, active=True)])
    await db.flush()
    db.add(ConnectionParam(connection_id=connection.id, param_name="token", param_value="synthetic-token"))
    await db.commit()
    await create_internal_room(actor_user_id=manager.id, agent_id=agent.id)
    # The remote Telegram transport is the only replaced boundary. Notifications
    # use the real native Chat and canonical permission/interaction services.
    monkeypatch.setattr(service, "messenger_for_agent", AsyncMock(return_value=None))
    bot = User(id=700, first_name="Synthetic Bot", is_bot=True, username="synthetic_contact_bot")
    sent = TelegramMessage.de_json({"message_id": 99, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": 420, "type": "private", "first_name": "Synthetic Contact"},
        "text": "Synthetic approved reply"}, None)
    provider = SimpleNamespace(initialize=AsyncMock(return_value=bot), aclose=AsyncMock(), send_text=AsyncMock(return_value=sent))
    monkeypatch.setattr("bridge.telegram.messenger.TelegramClient", lambda _token: provider)
    messenger = TelegramMessenger(provider, TelegramConnectionConfig(bot_token="synthetic"), bot,
        tool_id=tool.id, connection_id=connection.id, agent_id=agent.id)
    return agent, manager, outsider, connection, messenger


async def _receive(messenger, number=1, sender_id=420):
    update = Update.de_json({"update_id": number, "message": {
        "message_id": number, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": sender_id, "type": "private", "first_name": "Synthetic Contact"},
        "from": {"id": sender_id, "is_bot": False, "first_name": "Synthetic", "last_name": "Contact",
                 "username": "synthetic_contact", "language_code": "fr", "is_premium": True},
        "text": f"Synthetic contact message {number}",
    }}, None)
    await messenger._process_batch([update])


@pytest.mark.asyncio
@pytest.mark.parametrize("allow", [True, False])
async def test_received_contact_waits_in_activity_and_manager_decides_once(db, monkeypatch, allow):
    agent, manager, outsider, connection, messenger = await _scope(db, monkeypatch)
    await _receive(messenger)
    await _receive(messenger)  # Provider redelivery.
    await _receive(messenger, 2)
    round_ = await db.scalar(select(ConversationRound).join(Room).where(Room.connection_id == connection.id))
    assert round_.status == "PAUSED" and round_.attempt_count == 0 and not round_.effect_started
    assert await db.scalar(select(func.count()).select_from(ConversationRoundMessage).where(ConversationRoundMessage.round_id == round_.id)) == 2
    assert await claim_next_round("synthetic-worker") is None
    with pytest.raises(ConversationControlConflict):
        await control_round(round_.room_id, round_.id, "resume", expected_attempt=0)
    activity = await monitoring_service.list_messages(page=1, page_size=50, agent_id=agent.id, status="PAUSED")
    assert activity.total == 2
    await reconcile_contact_authorizations()
    pending = await list_decisions(managed_agent_ids=frozenset({agent.id}), agent_id=agent.id, allowed=None,
        offset=0, limit=50, pending=True, user_id=manager.id)
    assert pending.total == 1 and pending.items[0].can_answer
    permission = pending.items[0]
    assert "420" in permission.question and "synthetic_contact" in permission.question
    record = await db.get(PermissionDecision, permission.id)
    interaction = await db.get(Interaction, record.interaction_id)
    assert interaction.user_id == f"user:{manager.id}"
    assert interaction.prompt_message_id  # The manager actually received the native notification.
    assert not await answer_permission(permission.id, user_id=outsider.id, option_id="allow")
    detail = await monitoring_service.get_round(round_.id)
    assert detail.contact_authorization.external_id == "420"
    assert detail.contact_authorization.profile["username"] == "synthetic_contact"
    assert detail.contact_authorization.profile["is_premium"] is True
    assert await answer_permission(permission.id, user_id=manager.id, option_id="allow" if allow else "deny")
    assert not await answer_permission(permission.id, user_id=manager.id, option_id="allow" if allow else "deny")
    await reconcile_contact_authorizations()
    await db.refresh(round_)
    if allow:
        assert round_.status == "FROZEN"
        claimed = await claim_next_round("synthetic-worker")
        assert claimed.id == round_.id
        # Consent authorizes an external contact, never impersonation of the manager.
        assert claimed.requester_user_id is None
        await require_outgoing_room(connection.id, round_.room_id)
        # Existing receipts may predate the bridge's canonical agent link. Its
        # authenticated provider identity is not an additional human recipient.
        own_identity = await db.scalar(select(MessengerUser).where(
            MessengerUser.tool_id == connection.tool_id, MessengerUser.external_id == "700"))
        own_identity.agent_id = None
        await db.commit()
        await build_turn(claimed.id, lease_token=claimed.lease_token)
        assert await complete_round(claimed.id, ConversationOutcome(text="Synthetic approved reply"), lease_token=claimed.lease_token) == "SUCCEEDED"
        messenger.client.send_text.assert_awaited_once()
        outputs = list(await db.scalars(select(Message).where(Message.connection_id == connection.id, Message.direction == "outbound")))
        assert len(outputs) == 1 and outputs[0].text == "Synthetic approved reply"
        assert await db.scalar(select(func.count()).select_from(MessengerUser).where(
            MessengerUser.tool_id == connection.tool_id, MessengerUser.galaris_user_id.is_not(None))) == 0
        await delete_decision(permission.id, managed_agent_ids=frozenset({agent.id}))
        with pytest.raises(PermissionError):
            await require_outgoing_room(connection.id, round_.room_id)
    else:
        assert round_.status == "CANCELLED" and round_.delivery_state == "SKIPPED"
        assert await claim_next_round("synthetic-worker") is None
        await _receive(messenger, 3)
        await reconcile_contact_authorizations()
        assert await db.scalar(select(func.count()).select_from(PermissionDecision).where(PermissionDecision.agent_id == agent.id)) == 1
        assert await db.scalar(select(func.count()).select_from(Message).where(Message.connection_id == connection.id, Message.direction == "outbound")) == 0


@pytest.mark.asyncio
async def test_consent_is_exact_and_reassignment_requires_new_manager(db, monkeypatch):
    agent, manager, other_manager, connection, messenger = await _scope(db, monkeypatch)
    await _receive(messenger)
    await reconcile_contact_authorizations()
    record = await db.scalar(select(PermissionDecision).where(PermissionDecision.agent_id == agent.id))
    assert await answer_permission(record.id, user_id=manager.id, option_id="allow")
    await _receive(messenger, 2, sender_id=421)
    await reconcile_contact_authorizations()
    rounds = list(await db.scalars(select(ConversationRound).join(Room).where(Room.connection_id == connection.id)))
    assert sorted(r.status for r in rounds) == ["FROZEN", "PAUSED"]
    connection.active = False
    await db.commit()
    assert await claim_next_round("synthetic-worker") is None
    connection.active = True
    agent.user_id = other_manager.id
    await db.commit()
    await reconcile_contact_authorizations()
    replacement = await db.scalar(select(PermissionDecision).where(PermissionDecision.permission_key == record.permission_key))
    assert replacement.id != record.id and replacement.approver_user_id == other_manager.id
    assert replacement.allowed is None
    assert not await answer_permission(replacement.id, user_id=manager.id, option_id="allow")
    assert await claim_next_round("synthetic-worker") is None


@pytest.mark.asyncio
async def test_new_messages_wait_together_and_consent_does_not_resume_a_manual_pause(db, monkeypatch):
    agent, manager, _, connection, messenger = await _scope(db, monkeypatch)
    await _receive(messenger)
    await reconcile_contact_authorizations()
    permission = await db.scalar(select(PermissionDecision).where(PermissionDecision.agent_id == agent.id))
    assert await answer_permission(permission.id, user_id=manager.id, option_id="allow")
    await _receive(messenger, 2)
    rounds = list(await db.scalars(select(ConversationRound).join(Room).where(Room.connection_id == connection.id)))
    assert len(rounds) == 1 and rounds[0].status == "FROZEN"
    round_ = rounds[0]
    await control_round(round_.room_id, round_.id, "pause", expected_attempt=0)
    await reconcile_contact_authorizations()
    await db.refresh(round_)
    assert round_.status == "PAUSED" and not round_.contact_authorization_pending
    await control_round(round_.room_id, round_.id, "resume", expected_attempt=0)
    claimed = await claim_next_round("synthetic-worker")
    await build_turn(claimed.id, lease_token=claimed.lease_token)
    await delete_decision(permission.id, managed_agent_ids=frozenset({agent.id}))
    assert not await mark_effect_if_fresh(claimed.id, lease_token=claimed.lease_token)
    claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db.commit()
    assert await claim_next_round("synthetic-recovery-worker") is None
    await db.refresh(claimed)
    assert claimed.status == "PAUSED" and claimed.contact_authorization_pending
    assert claimed.attempt_count == 1
