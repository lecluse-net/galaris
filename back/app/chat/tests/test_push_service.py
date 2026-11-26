from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.agent.models import Title
from app.chat import push_service
from app.chat.models import ChatPushDelivery, ChatPushSubscription
from app.chat.schemas import PushSubscriptionCreate, PushSubscriptionKeys
from app.connection import Connection
from app.messenger.models import Message, MessengerUser, Room, RoomUser
from app.services import ServiceModel as Service
from core.params import VapidKeyPair, runtime_settings
from core.util import decrypt_value
from core.user import UserModel as User


def _enable_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(push_service, "web_push_keys", lambda: VapidKeyPair("public-key", "private-key"))
    monkeypatch.setattr(runtime_settings, "WEB_PUSH_DELAY_SECONDS", 1.0)


async def _message_scope(
    db: AsyncSession,
) -> tuple[User, RoomUser, Message]:
    suffix = uuid4().hex[:10]
    owner = User(
        email=f"push-owner-{suffix}@example.test",
        display_name="Push owner",
        hashed_password="unused",
        is_active=True,
    )
    recipient = User(
        email=f"push-recipient-{suffix}@example.test",
        display_name="Push recipient",
        hashed_password="unused",
        is_active=True,
    )
    db.add_all([owner, recipient])
    await db.flush()
    title = Title(label=f"Push {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        user_id=recipient.id,
        title_id=title.id,
        first_name="Push",
        last_name="Agent",
        code=f"push-{suffix}",
        agent_driver="internal",
    )
    tool = Service(
        code=f"push-tool-{suffix}",
        label="Push tool",
        description="",
        connection_schema={},
        messenger_config={"service": "internal"},
    )
    db.add_all([agent, tool])
    await db.flush()
    connection = Connection(service_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    sender = MessengerUser(
        service_id=tool.id,
        agent_id=agent.id,
        external_id=f"agent:{agent.id}",
        display_name="Push Agent",
        is_ai=True,
    )
    recipient_identity = MessengerUser(
        service_id=tool.id,
        galaris_user_id=recipient.id,
        external_id=f"user:{recipient.id}",
        display_name="Push recipient",
        is_ai=False,
    )
    db.add_all([sender, recipient_identity])
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"push-room-{suffix}",
        label="Push room",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    recipient_membership = RoomUser(room_id=room.id, user_id=recipient_identity.id)
    db.add_all(
        [
            RoomUser(room_id=room.id, user_id=sender.id),
            recipient_membership,
        ]
    )
    message = Message(
        connection_id=connection.id,
        service_id=tool.id,
        platform="internal",
        remote_message_id=f"push-message-{suffix}",
        direction="outbound",
        messenger_room_id=room.id,
        sender_messenger_user_id=sender.id,
        room_id=room.external_id,
        text="Un nouveau message",
    )
    db.add(message)
    await db.commit()
    # Cancellation tests must reach notification policy, not stop at an ACL denial.
    from app.chat.events import can_access_live_room
    assert await can_access_live_room(recipient.id, str(room.id))
    return recipient, recipient_membership, message


@pytest.mark.asyncio
async def test_message_audience_follows_personal_membership_and_impersonation_grant(db):
    from app.chat.events import _can_receive_event, _personal_candidates
    from app.messenger import personal_scope_changed
    from app.messenger.user_service import reconcile_room_users
    from core.authorize import Assignment
    from core.websocket import AuthorizedEvent
    from tests.authorization_fixtures import grant_privileges
    from tests.sql_reads import measured_reads

    user, membership, message = await _message_scope(db)
    data = {"room_id": str(message.messenger_room_id), "message_id": str(message.id)}
    await grant_privileges(db, user.id, "CHAT_IMPERSONATE")
    candidates = {user.id, *range(10000, 10049)}
    async with measured_reads(db, "50 connected Chat accounts") as audience_reads:
        assert await _personal_candidates(data, candidates) == {user.id}
    assert len(audience_reads) == 1
    async with measured_reads(db, "personal chat message audience") as reads:
        assert await _can_receive_event(user, "message", data) == AuthorizedEvent({**data, "personal_room": True})
    assert all("messenger_messages" not in query for query in reads)
    assert len(reads) <= 4
    room_id = membership.room_id
    sender_ids = list(await db.scalars(select(RoomUser.user_id).where(
        RoomUser.room_id == room_id, RoomUser.user_id != membership.user_id,
    )))
    revoked = asyncio.Event()
    observed = []

    async def scope_changed(user_id):
        observed.append(user_id)
        revoked.set()

    personal_scope_changed.connect(scope_changed)
    try:
        nested = await db.begin_nested()
        await reconcile_room_users(room_id=room_id, user_ids=sender_ids, authoritative=True)
        await nested.rollback()
        await db.commit()
        await asyncio.sleep(0)
        assert not observed
        assert await _personal_candidates(data, candidates) == {user.id}
        await reconcile_room_users(room_id=room_id, user_ids=sender_ids, authoritative=True)
        assert not observed
        await db.commit()
        await asyncio.wait_for(revoked.wait(), 1)
        assert observed == [user.id]
    finally:
        personal_scope_changed.disconnect(scope_changed)
    assert await _can_receive_event(user, "message", data) == AuthorizedEvent({**data, "personal_room": False})
    assert await _personal_candidates(data, candidates) == set()
    assert await _can_receive_event(user, "personal_message", data) is False
    assignment = (await db.scalars(select(Assignment).where(Assignment.user_id == user.id))).one()
    await db.delete(assignment)
    await db.flush()
    assert await _can_receive_event(user, "message", data) is False


@pytest.mark.asyncio
async def test_push_subscription_is_encrypted_and_upserted_per_endpoint(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_push(monkeypatch)
    user = User(
        email=f"push-subscription-{uuid4().hex}@example.test",
        display_name="Push subscription",
        hashed_password="unused",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    data = PushSubscriptionCreate(
        endpoint="https://push.example.test/subscription/secret",
        keys=PushSubscriptionKeys(p256dh="public-device-key", auth="auth-secret"),
    )

    first = await push_service.upsert_push_subscription(user.id, data)
    second = await push_service.upsert_push_subscription(user.id, data)

    assert second.id == first.id
    subscription = await db.get(ChatPushSubscription, first.id)
    assert subscription is not None
    assert subscription.endpoint_encrypted != data.endpoint
    assert decrypt_value(subscription.endpoint_encrypted) == data.endpoint
    assert decrypt_value(subscription.auth_encrypted) == "auth-secret"

    # Once initialized, updates preserve device subscriptions and the signing identity.
    from core.dbadmin import reconcile_dataset
    from core.params import params_service
    from core.params.dbadmin import datasets
    from core.params.web_push import web_push_keys

    encrypted = (subscription.endpoint_encrypted, subscription.p256dh_encrypted, subscription.auth_encrypted)
    persisted = web_push_keys()
    assert persisted is not None
    monkeypatch.setattr(push_service, 'web_push_keys', web_push_keys)
    await reconcile_dataset(db, datasets()[0])
    await params_service.refresh()
    await db.refresh(subscription)
    assert (subscription.endpoint_encrypted, subscription.p256dh_encrypted, subscription.auth_encrypted) == encrypted
    sender = Mock()
    monkeypatch.setattr(push_service, 'webpush', sender)
    push_service._send_web_push(subscription, {'title': 'Preserved subscription'})
    assert sender.call_args.kwargs['vapid_private_key'] == persisted.private_key
    assert sender.call_args.kwargs['subscription_info']['endpoint'] == data.endpoint
    assert push_service.push_configuration().public_key == persisted.public_key


@pytest.mark.asyncio
async def test_visible_message_cancels_queued_push_before_network_delivery(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_push(monkeypatch)
    recipient, membership, message = await _message_scope(db)
    subscription = ChatPushSubscription(
        user_id=recipient.id,
        endpoint_hash="a" * 64,
        endpoint_encrypted="unused",
        p256dh_encrypted="unused",
        auth_encrypted="unused",
    )
    db.add(subscription)
    await db.commit()

    await push_service.enqueue_message_push(message)
    delivery = await db.scalar(select(ChatPushDelivery))
    assert delivery is not None

    membership.read_through_position = message.journal_position
    delivery.status = "sending"
    await db.commit()
    send = Mock(side_effect=AssertionError("Web Push must have been cancelled"))
    monkeypatch.setattr(push_service, "_send_web_push", send)

    await push_service._process_delivery(delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "cancelled"
    send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "eligible", "sender_unknown", "muted", "self", "no_subscription", "disabled", "expired", "history", "unconfigured",
])
async def test_only_eligible_recipients_are_queued_once(db, monkeypatch, condition):
    _enable_push(monkeypatch)
    recipient, membership, message = await _message_scope(db)
    if condition != "no_subscription":
        db.add(ChatPushSubscription(
            user_id=recipient.id, endpoint_hash="c" * 64,
            endpoint_encrypted="unused", p256dh_encrypted="unused", auth_encrypted="unused",
            enabled=condition != "disabled",
            expiration_time=datetime.now(timezone.utc) - timedelta(days=1) if condition == "expired" else None,
        ))
    if condition == "muted":
        membership.muted = True
    elif condition == "self":
        message.sender_messenger_user_id = membership.user_id
    elif condition == "sender_unknown":
        message.sender_messenger_user_id = None
    elif condition == "history":
        message.counts_as_unread = False
    elif condition == "unconfigured":
        monkeypatch.setattr(push_service, "web_push_keys", lambda: None)
    await db.commit()

    await push_service.enqueue_message_push(message)
    await push_service.enqueue_message_push(message)

    deliveries = list((await db.scalars(select(ChatPushDelivery))).all())
    assert len(deliveries) == (1 if condition in {"eligible", "sender_unknown"} else 0)
    if deliveries:
        assert deliveries[0].user_id == recipient.id
        assert deliveries[0].message_id == message.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(None, "sent"), (404, "cancelled"), (410, "cancelled"),
                                          (403, "failed"), (429, "pending"), (503, "pending")])
async def test_push_delivery_persists_receipt_or_retry_without_disabling_healthy_endpoints(db, monkeypatch, status, expected):
    from pywebpush import WebPushException
    from types import SimpleNamespace

    _enable_push(monkeypatch)
    recipient, _membership, message = await _message_scope(db)
    subscription = ChatPushSubscription(
        user_id=recipient.id, endpoint_hash="d" * 64,
        endpoint_encrypted="unused", p256dh_encrypted="unused", auth_encrypted="unused",
    )
    db.add(subscription)
    await db.commit()
    await push_service.enqueue_message_push(message)
    delivery = await db.scalar(select(ChatPushDelivery))
    assert delivery is not None
    delivery.status = "sending"
    delivery.attempts = 1
    await db.commit()
    send = Mock(side_effect=WebPushException("remote refusal", response=SimpleNamespace(status_code=status)) if status else None)
    monkeypatch.setattr(push_service, "_send_web_push", send)

    await push_service._process_delivery(delivery.id)

    send.assert_called_once()
    await db.refresh(delivery)
    await db.refresh(subscription)
    assert delivery.status == expected
    assert subscription.enabled == (status not in {404, 410})
    assert (delivery.delivered_at is not None) == (status is None)
    assert subscription.failure_count == (0 if status is None else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("display_stage", ["enqueue", "delivery", "payload"])
async def test_displayed_room_cancels_queued_push_before_network_delivery(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    display_stage: str,
) -> None:
    _enable_push(monkeypatch)
    recipient, _membership, message = await _message_scope(db)
    subscription = ChatPushSubscription(
        user_id=recipient.id,
        endpoint_hash="b" * 64,
        endpoint_encrypted="unused",
        p256dh_encrypted="unused",
        auth_encrypted="unused",
    )
    db.add(subscription)
    await db.commit()

    displayed = display_stage == "enqueue"

    def room_is_displayed(user_id: int, room_name: str) -> bool:
        return displayed and user_id == recipient.id and room_name == f"ChatRoom:{message.messenger_room_id}"

    monkeypatch.setattr(push_service.websocket, "is_room_displayed_by_user", room_is_displayed)

    await push_service.enqueue_message_push(message)
    delivery = await db.scalar(select(ChatPushDelivery))
    if display_stage == "enqueue":
        assert delivery is None
        return
    assert delivery is not None
    delivery.status = "sending"
    await db.commit()
    send = Mock(side_effect=AssertionError("Web Push must have been cancelled"))
    monkeypatch.setattr(push_service, "_send_web_push", send)

    if display_stage == "delivery":
        displayed = True
    else:
        count_unread = push_service.count_chat_unread

        async def count_after_open(user_id: int) -> int:
            nonlocal displayed
            count = await count_unread(user_id)
            displayed = True
            return count

        monkeypatch.setattr(push_service, "count_chat_unread", count_after_open)

    await push_service._process_delivery(delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "cancelled"
    send.assert_not_called()
