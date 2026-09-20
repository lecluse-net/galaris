"""Durable Web Push subscriptions and message notification delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from loguru import logger
from pywebpush import WebPushException, webpush
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core import websocket
from core.params import runtime_settings, web_push_keys
from core.database import get_db, get_db_session
from core.util import decrypt_value, encrypt_value
from app.messenger import (
    Message,
    MessengerUser,
    Room,
    RoomUser,
    count_chat_unread,
)

from .models import ChatPushDelivery, ChatPushSubscription
from .schemas import (
    PushConfiguration,
    PushSubscriptionCreate,
    PushSubscriptionRead,
)


_BATCH_SIZE = 20
_MAX_ATTEMPTS = 8
_LOCK_TIMEOUT = timedelta(minutes=5)
_MAX_ERROR_LENGTH = 1_000


def _endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def _push_available() -> bool:
    return web_push_keys() is not None


def push_configuration() -> PushConfiguration:
    keys = web_push_keys()
    return PushConfiguration(
        available=keys is not None,
        public_key=keys.public_key if keys else "",
    )


def _validate_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("A Web Push endpoint must be an HTTPS URL without credentials.")
    return normalized


async def upsert_push_subscription(
    user_id: int,
    data: PushSubscriptionCreate,
) -> PushSubscriptionRead:
    if not _push_available():
        raise RuntimeError("Web Push is not configured on this Galaris instance.")
    endpoint = _validate_endpoint(data.endpoint)
    expiration_time = (
        datetime.fromtimestamp(data.expiration_time / 1_000, tz=timezone.utc)
        if data.expiration_time is not None
        else None
    )
    subscription_id = await get_db().scalar(
        pg_insert(ChatPushSubscription)
        .values(
            user_id=user_id,
            endpoint_hash=_endpoint_hash(endpoint),
            endpoint_encrypted=encrypt_value(endpoint),
            p256dh_encrypted=encrypt_value(data.keys.p256dh),
            auth_encrypted=encrypt_value(data.keys.auth),
            expiration_time=expiration_time,
            enabled=True,
            failure_count=0,
            last_failure_at=None,
        )
        .on_conflict_do_update(
            index_elements=[ChatPushSubscription.endpoint_hash],
            set_={
                "user_id": user_id,
                "endpoint_encrypted": encrypt_value(endpoint),
                "p256dh_encrypted": encrypt_value(data.keys.p256dh),
                "auth_encrypted": encrypt_value(data.keys.auth),
                "expiration_time": expiration_time,
                "enabled": True,
                "failure_count": 0,
                "last_failure_at": None,
                "updated_at": func.now(),
            },
        )
        .returning(ChatPushSubscription.id)
    )
    if subscription_id is None:
        raise RuntimeError("The Web Push subscription could not be persisted.")
    await get_db().commit()
    return PushSubscriptionRead(id=subscription_id, enabled=True)


async def delete_push_subscription(user_id: int, endpoint: str) -> bool:
    normalized = _validate_endpoint(endpoint)
    result = await get_db().execute(
        update(ChatPushSubscription)
        .where(
            ChatPushSubscription.user_id == user_id,
            ChatPushSubscription.endpoint_hash == _endpoint_hash(normalized),
        )
        .values(enabled=False, updated_at=func.now())
        .returning(ChatPushSubscription.id)
    )
    deleted = result.scalar_one_or_none() is not None
    await get_db().commit()
    return deleted


async def enqueue_message_push(message: Message) -> None:
    """Signal receiver: enqueue current subscribed recipients after persistence."""

    if (
        not _push_available()
        or message.messenger_room_id is None
        or not message.counts_as_unread
    ):
        return
    async with get_db_session():
        persisted = await get_db().get(Message, message.id)
        if (
            persisted is None
            or persisted.messenger_room_id is None
            or not persisted.counts_as_unread
        ):
            return
        recipient_filters = [
            RoomUser.room_id == persisted.messenger_room_id,
            RoomUser.muted.is_(False),
            MessengerUser.galaris_user_id.is_not(None),
        ]
        if persisted.sender_messenger_user_id is not None:
            recipient_filters.append(
                RoomUser.user_id != persisted.sender_messenger_user_id
            )
        user_ids = list(
            (
                await get_db().scalars(
                    select(MessengerUser.galaris_user_id)
                    .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                    .where(*recipient_filters)
                    .distinct()
                )
            ).all()
        )
        if not user_ids:
            return
        now = datetime.now(timezone.utc)
        subscriptions = list(
            (
                await get_db().scalars(
                    select(ChatPushSubscription).where(
                        ChatPushSubscription.user_id.in_(user_ids),
                        ChatPushSubscription.enabled.is_(True),
                        or_(
                            ChatPushSubscription.expiration_time.is_(None),
                            ChatPushSubscription.expiration_time > now,
                        ),
                    )
                )
            ).all()
        )
        if not subscriptions:
            return
        available_at = now + timedelta(seconds=runtime_settings.WEB_PUSH_DELAY_SECONDS)
        await get_db().execute(
            pg_insert(ChatPushDelivery)
            .values(
                [
                    {
                        "subscription_id": subscription.id,
                        "user_id": subscription.user_id,
                        "message_id": persisted.id,
                        "room_id": persisted.messenger_room_id,
                        "available_at": available_at,
                    }
                    for subscription in subscriptions
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ChatPushDelivery.subscription_id,
                    ChatPushDelivery.message_id,
                ]
            )
        )
        await get_db().commit()


def _send_web_push(subscription: ChatPushSubscription, payload: dict[str, object]) -> None:
    keys = web_push_keys()
    if keys is None:
        raise RuntimeError("Web Push identity has not been loaded")
    sender = cast(Callable[..., object], webpush)
    sender(
        subscription_info={
            "endpoint": decrypt_value(subscription.endpoint_encrypted),
            "keys": {
                "p256dh": decrypt_value(subscription.p256dh_encrypted),
                "auth": decrypt_value(subscription.auth_encrypted),
            },
        },
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        vapid_private_key=keys.private_key,
        vapid_claims={"sub": runtime_settings.WEB_PUSH_VAPID_SUBJECT},
        ttl=86_400,
        timeout=15,
    )


def _http_status(error: WebPushException) -> int | None:
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return int(value) if isinstance(value, int) else None


async def _cancel_delivery(delivery: ChatPushDelivery) -> None:
    delivery.status = "cancelled"
    delivery.locked_at = None
    await get_db().commit()


async def _process_delivery(delivery_id: UUID) -> None:
    row = (
        await get_db().execute(
            select(ChatPushDelivery, ChatPushSubscription, Message, Room)
            .join(
                ChatPushSubscription,
                ChatPushSubscription.id == ChatPushDelivery.subscription_id,
            )
            .join(Message, Message.id == ChatPushDelivery.message_id)
            .join(Room, Room.id == ChatPushDelivery.room_id)
            .where(ChatPushDelivery.id == delivery_id)
        )
    ).one_or_none()
    if row is None:
        return
    delivery, subscription, message, room = row
    from .events import can_access_live_room
    if not await can_access_live_room(delivery.user_id, str(room.id)):
        await _cancel_delivery(delivery)
        return
    if not subscription.enabled or not message.counts_as_unread:
        await _cancel_delivery(delivery)
        return
    membership_rows = (
        await get_db().execute(
            select(RoomUser, MessengerUser)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(
                RoomUser.room_id == room.id,
                MessengerUser.galaris_user_id == delivery.user_id,
            )
        )
    ).all()
    if not membership_rows:
        await _cancel_delivery(delivery)
        return
    viewer_identity_ids = {identity.id for _membership, identity in membership_rows}
    active_memberships = [
        membership for membership, _identity in membership_rows if not membership.muted
    ]
    if (
        not active_memberships
        or any(
            membership.read_through_position is not None
            and membership.read_through_position >= message.journal_position
            for membership in active_memberships
        )
        or message.sender_messenger_user_id in viewer_identity_ids
        or websocket.is_room_displayed_by_user(
            delivery.user_id,
            f"ChatRoom:{room.id}",
        )
    ):
        await _cancel_delivery(delivery)
        return

    sender_name = await get_db().scalar(
        select(MessengerUser.display_name).where(
            MessengerUser.id == message.sender_messenger_user_id
        )
    )
    text = message.text.strip().replace("\n", " ")
    show_last_message = all(
        membership.show_last_message for membership in active_memberships
    )
    if show_last_message and text:
        preview = text[:180]
        body = f"{sender_name}: {preview}" if sender_name else preview
    elif sender_name:
        body = sender_name
    else:
        body = room.label or "Galaris"
    payload: dict[str, object] = {
        "title": room.label or "Galaris",
        "body": body,
        "icon": "/pwa/icon-192.png",
        "badge": "/pwa/icon-192.png",
        "tag": f"chat-message-{message.id}",
        "data": {
            "url": f"/chat?room={room.id}",
            "roomId": str(room.id),
            "messageId": str(message.id),
        },
        "unreadCount": await count_chat_unread(delivery.user_id),
    }
    now = datetime.now(timezone.utc)
    try:
        await asyncio.to_thread(_send_web_push, subscription, payload)
    except WebPushException as exc:
        status = _http_status(exc)
        subscription.failure_count += 1
        subscription.last_failure_at = now
        delivery.locked_at = None
        delivery.last_error = (
            f"Web Push failed with HTTP {status}"
            if status is not None
            else f"Web Push failed: {type(exc).__name__}"
        )[:_MAX_ERROR_LENGTH]
        if status in {404, 410}:
            subscription.enabled = False
            delivery.status = "cancelled"
        elif delivery.attempts >= _MAX_ATTEMPTS or (
            status is not None and 400 <= status < 500 and status != 429
        ):
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.available_at = now + timedelta(
                seconds=min(900, 2 ** max(1, delivery.attempts))
            )
        await get_db().commit()
        return
    except Exception as exc:
        subscription.failure_count += 1
        subscription.last_failure_at = now
        delivery.locked_at = None
        delivery.last_error = f"Web Push failed: {type(exc).__name__}"[:_MAX_ERROR_LENGTH]
        if delivery.attempts >= _MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.available_at = now + timedelta(
                seconds=min(900, 2 ** max(1, delivery.attempts))
            )
        await get_db().commit()
        return

    subscription.failure_count = 0
    subscription.last_success_at = now
    subscription.last_failure_at = None
    delivery.status = "sent"
    delivery.delivered_at = now
    delivery.locked_at = None
    delivery.last_error = None
    await get_db().commit()


async def process_push_deliveries() -> int:
    """Claim and deliver one bounded batch; safe across restarts and replicas."""

    if not _push_available():
        return 0
    now = datetime.now(timezone.utc)
    await get_db().execute(
        update(ChatPushDelivery)
        .where(
            ChatPushDelivery.status == "sending",
            ChatPushDelivery.locked_at < now - _LOCK_TIMEOUT,
        )
        .values(status="pending", locked_at=None)
    )
    deliveries = list(
        (
            await get_db().scalars(
                select(ChatPushDelivery)
                .where(
                    ChatPushDelivery.status == "pending",
                    ChatPushDelivery.available_at <= now,
                )
                .order_by(ChatPushDelivery.available_at, ChatPushDelivery.created_at)
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for delivery in deliveries:
        delivery.status = "sending"
        delivery.locked_at = now
        delivery.attempts += 1
    await get_db().commit()
    for delivery in deliveries:
        await _process_delivery(delivery.id)
    if deliveries:
        logger.debug("Processed {} Chat Web Push deliveries", len(deliveries))
    return len(deliveries)


__all__ = [
    "delete_push_subscription",
    "enqueue_message_push",
    "process_push_deliveries",
    "push_configuration",
    "upsert_push_subscription",
]
