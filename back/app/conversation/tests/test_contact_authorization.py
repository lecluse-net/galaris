"""External receipt is observable before a manager authorizes any agent response."""
from datetime import datetime, timedelta, timezone
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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
from bridge.whatsapp.messenger import WhatsAppMessenger
from bridge.one_bot.messenger import OneBotMessenger
from core.authorize import Assignment, Privilege, Role
from core.params import runtime_settings
from core.user import UserModel


@pytest.fixture(autouse=True)
def isolated_inbound_deduplication():
    from app.messenger.inbound import _reset_dedup_for_tests

    # Cloned databases can reuse local sequence IDs across scenarios.
    _reset_dedup_for_tests()
    yield
    _reset_dedup_for_tests()


@pytest_asyncio.fixture
async def onebot_stack():
    async with AsyncExitStack() as stack:
        yield stack


@pytest_asyncio.fixture
async def contact_db(committed_database):
    from core.database import get_db_session

    async with get_db_session() as session:
        yield session


@pytest_asyncio.fixture
async def contact_client(contact_db, committed_database, monkeypatch):
    from core.database import middleware
    from main import app

    # Webhook, journal and admission use independent transactions in the same
    # cloned DB, so closing the HTTP read session cannot undo durable admission.
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        yield client


async def _scope(db, monkeypatch, platform="telegram", *, onebot_stack=None):
    monkeypatch.setattr(runtime_settings, "MESSENGER_ENABLED_CHANNELS", '["internal","telegram","whatsapp","one_bot"]')
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
    # The remote provider transport is the only replaced boundary. Notifications
    # use the real native Chat and canonical permission/interaction services.
    monkeypatch.setattr(service, "messenger_for_agent", AsyncMock(return_value=None))
    if platform == "one_bot":
        from app.tools import ConnectionParamDef, ConnectionSchema, MessengerConfig, ToolUpdate, tool_service
        from app.connection import connection_service
        from bridge.one_bot.tests.adapter import connected_adapter

        await tool_service.update_tool(tool.id, ToolUpdate(
            messenger_config=MessengerConfig(service="one_bot", settings={"platform": "qq"},
                param_map={"user_id": "adapter_bot", "token": "token"}),
            connection_schema=ConnectionSchema(params={
                "token": ConnectionParamDef(type="password"), "adapter_bot": ConnectionParamDef(),
            }),
        ))
        await connection_service.set_param(connection.id, "adapter_bot", "700")
        messenger = await OneBotMessenger.from_connection_id(connection.id)
        messenger._test_adapter = await onebot_stack.enter_async_context(connected_adapter())
        assert await messenger.check_connection() == "700"
        from websockets import connect
        from websockets.exceptions import InvalidStatus

        with pytest.raises(InvalidStatus):
            async with connect(messenger._test_adapter.uri, additional_headers={"Authorization": "Bearer wrong-token"}):
                pass
        before = len(messenger._test_adapter.actions)
        await connection_service.set_param(connection.id, "token", "synthetic-rotated-token")
        with pytest.raises(ValueError):
            await messenger.check_connection()
        assert len(messenger._test_adapter.actions) == before
        await connection_service.set_param(connection.id, "token", "synthetic-token")
        return agent, manager, outsider, connection, messenger
    if platform == "whatsapp":
        from app.tools import ConnectionParamDef, ConnectionSchema, MessengerConfig, ToolUpdate, tool_service
        from app.connection import connection_service

        await tool_service.update_tool(tool.id, ToolUpdate(
            messenger_config=MessengerConfig(service="whatsapp",
                settings={"app_secret": "synthetic-meta-secret", "verify_token": "synthetic-verify-token"},
                param_map={"access_token": "token", "phone_number_id": "meta_phone"}),
            connection_schema=ConnectionSchema(params={
                "token": ConnectionParamDef(type="password"), "meta_phone": ConnectionParamDef(),
            }),
        ))
        await connection_service.set_param(connection.id, "meta_phone", "700")
        provider = SimpleNamespace(validate=AsyncMock(return_value={"id": "700"}),
            aclose=AsyncMock(), send_text=AsyncMock(return_value={"messages": [{"id": "wamid.reply"}]}))
        monkeypatch.setattr("bridge.whatsapp.messenger.WhatsAppClient", lambda **_kwargs: provider)
        messenger = await WhatsAppMessenger.from_connection_id(connection.id)
        return agent, manager, outsider, connection, messenger
    bot = User(id=700, first_name="Synthetic Bot", is_bot=True, username="synthetic_contact_bot")
    sent = TelegramMessage.de_json({"message_id": 99, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": 420, "type": "private", "first_name": "Synthetic Contact"},
        "text": "Synthetic approved reply"}, None)
    provider = SimpleNamespace(initialize=AsyncMock(return_value=bot), aclose=AsyncMock(), send_text=AsyncMock(return_value=sent))
    monkeypatch.setattr("bridge.telegram.messenger.TelegramClient", lambda _token: provider)
    messenger = TelegramMessenger(provider, TelegramConnectionConfig(bot_token="synthetic"), bot,
        tool_id=tool.id, connection_id=connection.id, agent_id=agent.id)
    return agent, manager, outsider, connection, messenger


async def _receive(messenger, number=1, sender_id=420, *, client=None):
    if messenger.kind == "one_bot":
        import asyncio
        import json
        from app.messenger import journal

        await messenger._test_adapter.socket.send(json.dumps({
            "time": int(datetime.now(timezone.utc).timestamp()), "self_id": 700,
            "post_type": "message", "message_type": "private", "sub_type": "friend",
            "message_id": -number, "user_id": sender_id, "sender": {"user_id": sender_id, "nickname": "Synthetic Contact"},
            "raw_message": f"Synthetic contact message {number}",
            "message": [{"type": "text", "data": {"text": f"Synthetic contact message {number}"}}],
        }))
        async with asyncio.timeout(3):
            while True:
                stored = await journal.stored_message(connection_id=messenger.connection_id,
                    remote_message_id=str(-number), direction="inbound")
                if stored is not None and stored.status == "admitted":
                    return
                await asyncio.sleep(0.01)
    if messenger.kind == "whatsapp":
        import hashlib
        import hmac
        import json

        payload = {"object": "whatsapp_business_account", "entry": [{"id": "synthetic-waba", "changes": [{
            "field": "messages", "value": {
                "metadata": {"phone_number_id": "700"},
                "contacts": [{"wa_id": str(sender_id), "profile": {"name": "Synthetic Contact"}}],
                "messages": [{"id": f"wamid.{number}", "from": str(sender_id),
                    "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                    "type": "text", "text": {"body": f"Synthetic contact message {number}"}}],
            },
        }]}]}
        raw = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"synthetic-meta-secret", raw, hashlib.sha256).hexdigest()
        response = await client.post(f"/api/whatsapp/webhook/{messenger.tool_id}", content=raw,
            headers={"X-Hub-Signature-256": signature})
        assert response.status_code == 200, response.text
        return
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
@pytest.mark.parametrize("platform", ["telegram", "whatsapp", "one_bot"])
async def test_received_contact_waits_in_activity_and_manager_decides_once(contact_db, monkeypatch, contact_client, onebot_stack, allow, platform):
    db = contact_db
    agent, manager, outsider, connection, messenger = await _scope(db, monkeypatch, platform, onebot_stack=onebot_stack)
    if platform == "whatsapp":
        webhook = f"/api/whatsapp/webhook/{messenger.tool_id}"
        verification = {"hub.mode": "subscribe", "hub.verify_token": "synthetic-verify-token", "hub.challenge": "synthetic-challenge"}
        verified = await contact_client.get(webhook, params=verification)
        assert verified.status_code == 200 and verified.text == "synthetic-challenge"
        denied = await contact_client.get(webhook, params={**verification, "hub.verify_token": "mauvais-é"})
        assert denied.status_code == 403
        unsigned = await contact_client.post(webhook, content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad"})
        assert unsigned.status_code == 401
    await _receive(messenger, client=contact_client)
    await _receive(messenger, client=contact_client)  # Provider redelivery.
    await _receive(messenger, 2, client=contact_client)
    round_ = await db.scalar(select(ConversationRound).join(Room).where(Room.connection_id == connection.id))
    assert round_.status == "PAUSED" and round_.attempt_count == 0 and not round_.effect_started
    assert await db.scalar(select(func.count()).select_from(ConversationRoundMessage).where(ConversationRoundMessage.round_id == round_.id)) == 2
    if platform == "one_bot":
        from app.messenger import facade

        messenger_facade = await facade.get_messenger(connection.id)
        page = await messenger_facade.history_page(round_.room_id, limit=1)
        assert len(page.messages) == 1 and page.has_more and page.next_cursor
        older = await messenger_facade.history_page(round_.room_id, limit=1, cursor=page.next_cursor)
        assert len(older.messages) == 1
        assert page.messages[0].remote_message_id != older.messages[0].remote_message_id
        assert "get_friend_msg_history" not in messenger._test_adapter.actions
    assert await claim_next_round("synthetic-worker") is None
    with pytest.raises(ConversationControlConflict):
        await control_round(round_.room_id, round_.id, "resume", expected_attempt=0)
    activity = await monitoring_service.list_messages(page=1, page_size=50, agent_id=agent.id, status="PAUSED")
    assert activity.total == 2
    # End the simulated failed control request before an independent reconciler
    # acquires the same room lock, as the HTTP middleware would do in the app.
    await db.commit()
    await reconcile_contact_authorizations()
    pending = await list_decisions(managed_agent_ids=frozenset({agent.id}), agent_id=agent.id, allowed=None,
        offset=0, limit=50, pending=True, user_id=manager.id)
    assert pending.total == 1 and pending.items[0].can_answer
    permission = pending.items[0]
    assert "420" in permission.question
    assert ("synthetic_contact" if platform == "telegram" else "Synthetic Contact") in permission.question
    record = await db.get(PermissionDecision, permission.id)
    interaction = await db.get(Interaction, record.interaction_id)
    assert interaction.user_id == f"user:{manager.id}"
    assert interaction.prompt_message_id  # The manager actually received the native notification.
    assert not await answer_permission(permission.id, user_id=outsider.id, option_id="allow")
    detail = await monitoring_service.get_round(round_.id)
    assert detail.contact_authorization.external_id == "420"
    if platform == "telegram":
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
        assert own_identity.agent_id == agent.id and own_identity.is_ai
        own_identity.agent_id = None
        await db.commit()
        await build_turn(claimed.id, lease_token=claimed.lease_token)
        assert await complete_round(claimed.id, ConversationOutcome(text="Synthetic approved reply"), lease_token=claimed.lease_token) == "SUCCEEDED"
        if platform == "one_bot":
            messenger._test_adapter.send_text.assert_awaited_once()
        else:
            messenger.client.send_text.assert_awaited_once()
        outputs = list(await db.scalars(select(Message).where(Message.connection_id == connection.id, Message.direction == "outbound")))
        assert len(outputs) == 1 and outputs[0].text == "Synthetic approved reply"
        if platform == "one_bot":
            assert outputs[0].user_id == "420" and outputs[0].messenger_user_id is not None
        assert await db.scalar(select(func.count()).select_from(MessengerUser).where(
            MessengerUser.tool_id == connection.tool_id, MessengerUser.galaris_user_id.is_not(None))) == 0
        await delete_decision(permission.id, managed_agent_ids=frozenset({agent.id}))
        with pytest.raises(PermissionError):
            await require_outgoing_room(connection.id, round_.room_id)
    else:
        assert round_.status == "CANCELLED" and round_.delivery_state == "SKIPPED"
        assert await claim_next_round("synthetic-worker") is None
        await _receive(messenger, 3, client=contact_client)
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
