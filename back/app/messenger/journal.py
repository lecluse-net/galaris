"""Persistent messaging journal, delivery status, and listener cursors."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_db, get_db_session

from ._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
)
from .interface import HistoryPage
from .models import (
    ListenerState,
    File,
    Attachment,
    ConversationType,
    Message,
    Room,
    MessengerUser,
)
from .room_service import resolve_messenger_room
from .user_service import (
    enrich_messenger_users,
    reconcile_room_users,
    resolve_observed_user,
)

Direction = Literal["inbound", "outbound"]
_MAX_ATTACHMENTS = 20
_MAX_METADATA_TEXT = 2_000
_MAX_HISTORY_PAGE_SIZE = 500


def connection_id_for(message: ObservedMessengerMessage) -> int | None:
    """Return the connection pinned on a canonical message, if any."""
    identities = (message.recipient, message.sender)
    for identity in identities:
        if identity is not None and identity.connection_id is not None:
            return int(identity.connection_id)
    return None


def _bounded(value: str | None, limit: int = _MAX_METADATA_TEXT) -> str:
    return (value or "")[:limit]


def _attachment_rows(message: ObservedMessengerMessage) -> list[dict[str, Any]]:
    return [
        {
            "id": _bounded(item.id, 512),
            "name": _bounded(item.name, 512),
            "mime": _bounded(item.mime, 255),
            "url": _bounded(item.url, 2_000) or None,
            "size": item.size,
            "kind": item.kind,
        }
        for item in message.attachments[:_MAX_ATTACHMENTS]
    ]


async def _synchronize_files(
    message_id: UUID,
    connection_id: int,
    attachments: list[ObservedMessengerFile],
) -> list[File]:
    """Upsert attachment metadata without ever persisting file content."""

    for position, attachment in enumerate(attachments[:_MAX_ATTACHMENTS]):
        external_identifier = _bounded(attachment.id, 512) or None
        values: dict[str, Any] = {
            "name": _bounded(attachment.name, 512),
            "mime_type": _bounded(attachment.mime, 255),
            "size_bytes": attachment.size,
            "kind": attachment.kind,
            "remote_url": _bounded(attachment.url, 2_000) or None,
            "deleted_at": None,
            "deleted_by": None,
        }
        existing_file_id = await get_db().scalar(
            select(Attachment.file_id).where(
                Attachment.message_id == message_id,
                Attachment.position == position,
            )
        )
        if external_identifier is not None:
            file_id = await get_db().scalar(
                pg_insert(File)
                .values(
                    id=attachment.local_id or uuid4(),
                    connection_id=connection_id,
                    external_identifier=external_identifier,
                    **values,
                )
                .on_conflict_do_update(
                    constraint="uq_messenger_file_connection_external",
                    set_=values,
                )
                .returning(File.id)
            )
        elif existing_file_id is not None:
            file_id = existing_file_id
            await get_db().execute(
                update(File)
                .where(File.id == file_id)
                .values(**values)
            )
        else:
            file_id = attachment.local_id or uuid4()
            get_db().add(
                File(
                    id=file_id,
                    connection_id=connection_id,
                    external_identifier=None,
                    **values,
                )
            )
            await get_db().flush()
        if file_id is None:
            raise RuntimeError("The Messenger file disappeared while being synchronized.")
        await get_db().execute(
            pg_insert(Attachment)
            .values(message_id=message_id, position=position, file_id=file_id)
            .on_conflict_do_update(
                index_elements=[
                    Attachment.message_id,
                    Attachment.position,
                ],
                set_={"file_id": file_id},
            )
        )
    return list(
        (
            await get_db().scalars(
                select(File)
                .join(
                    Attachment,
                    Attachment.file_id == File.id,
                )
                .where(Attachment.message_id == message_id)
                .order_by(Attachment.position)
            )
        ).all()
    )


def _remote_datetime(timestamp: int) -> datetime | None:
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


async def record(
    message: ObservedMessengerMessage,
    *,
    connection_id: int,
    platform: str,
    direction: Direction,
    status: str,
    metadata: dict[str, Any] | None = None,
    counts_as_unread: bool = True,
) -> bool:
    """Insert a journal entry atomically and return ``False`` for a duplicate."""
    if not message.id:
        return True
    room_id = message.room.id if message.room is not None else None
    messenger_room_id = (
        await resolve_messenger_room(
            connection_id=connection_id,
            external_id=room_id,
            label=message.room.label if message.room is not None else None,
            kind=message.room.kind if message.room is not None else "group",
            conversation_type=(
                ConversationType(message.room.conversation_type)
                if message.room is not None
                else ConversationType.TEXT
            ),
        )
        if room_id
        else None
    )
    user = message.sender if direction == "inbound" else message.recipient
    sender = message.sender
    recipient = message.recipient
    tool_id = message.tool_id or next(
        (
            identity.tool_id
            for identity in (sender, recipient)
            if identity is not None and identity.tool_id is not None
        ),
        None,
    )
    # Concurrent room catch-ups often observe the same pair in opposite
    # sender/recipient directions. Resolve identities in a stable order so two
    # transactions cannot acquire their unique-key locks in reverse order.
    identities = sorted(
        (
            identity
            for identity in (sender, recipient)
            if identity is not None and identity.id.strip()
        ),
        key=lambda identity: identity.id,
    )
    if identities and tool_id is None:
        raise ValueError("A Messenger message with identities requires a local Tool.")
    identity_ids: dict[str, UUID] = {}
    if tool_id is not None:
        for identity in identities:
            if identity.id in identity_ids:
                continue
            identity_ids[identity.id] = await resolve_observed_user(
                tool_id=tool_id,
                user=identity,
            )
    messenger_user_id = identity_ids.get(user.id) if user is not None else None
    sender_messenger_user_id = (
        identity_ids.get(sender.id) if sender is not None else None
    )
    requester_user_id = (
        await get_db().scalar(
            select(MessengerUser.galaris_user_id).where(
                MessengerUser.id == messenger_user_id
            )
        )
        if direction == "inbound" and messenger_user_id is not None
        else None
    )
    if messenger_room_id is not None and identity_ids:
        await reconcile_room_users(
            room_id=messenger_room_id,
            user_ids=list(identity_ids.values()),
            authoritative=False,
        )
    canonical_metadata: dict[str, Any] = {
        "sender_id": sender.id if sender is not None else "",
        "sender_display_name": sender.display_name if sender is not None else "",
        "sender_agent_id": sender.agent_id if sender is not None else None,
        "sender_is_ai": sender.is_ai if sender is not None else False,
        "recipient_id": recipient.id if recipient is not None else "",
        "recipient_display_name": recipient.display_name if recipient is not None else "",
        "recipient_agent_id": recipient.agent_id if recipient is not None else None,
        "recipient_is_ai": recipient.is_ai if recipient is not None else False,
    }
    canonical_metadata.update(metadata or {})
    created_at = _remote_datetime(message.time) or datetime.now(timezone.utc)
    statement = (
        pg_insert(Message)
        .values(
            connection_id=connection_id,
            tool_id=tool_id,
            platform=platform,
            remote_message_id=_bounded(message.id, 512),
            direction=direction,
            messenger_room_id=messenger_room_id,
            messenger_user_id=messenger_user_id,
            sender_messenger_user_id=sender_messenger_user_id,
            counts_as_unread=counts_as_unread,
            requester_user_id=requester_user_id,
            room_id=_bounded(room_id, 512) or None,
            user_id=_bounded(user.id if user is not None else None, 512) or None,
            topic_id=message.topic_id,
            topic_overridden=message.topic_overridden,
            text=message.text,
            attachments=_attachment_rows(message),
            reply_to=_bounded(message.reply_to, 512) or None,
            created_at=created_at,
            status=_bounded(status, 50),
            metadata_=canonical_metadata,
        )
        .on_conflict_do_nothing(
            index_elements=[
                Message.connection_id,
                Message.remote_message_id,
                Message.direction,
            ]
        )
        .returning(Message.id)
    )
    inserted_id = (await get_db().execute(statement)).scalar_one_or_none()
    if inserted_id is not None:
        await _synchronize_files(inserted_id, connection_id, message.attachments)
        return True
    existing = (
        await get_db().execute(
            select(Message.id, Message.metadata_)
            .where(
                Message.connection_id == connection_id,
                Message.remote_message_id == _bounded(message.id, 512),
                Message.direction == direction,
            )
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if existing is None:
        raise RuntimeError("The Messenger message disappeared while being synchronized.")
    existing_id, existing_metadata = existing
    merged_metadata = {**dict(existing_metadata or {}), **canonical_metadata}
    await get_db().execute(
        update(Message)
        .where(
            Message.id == existing_id,
        )
        .values(
            tool_id=tool_id,
            platform=platform,
            messenger_room_id=messenger_room_id,
            messenger_user_id=messenger_user_id,
            sender_messenger_user_id=sender_messenger_user_id,
            # A live/unread observation can promote an earlier passive history import,
            # but scrolling old provider history must never demote a live message.
            counts_as_unread=(
                True if counts_as_unread else Message.counts_as_unread
            ),
            room_id=_bounded(room_id, 512) or None,
            user_id=_bounded(user.id if user is not None else None, 512) or None,
            text=message.text,
            attachments=_attachment_rows(message),
            reply_to=_bounded(message.reply_to, 512) or None,
            created_at=created_at,
            metadata_=merged_metadata,
            deleted_at=None,
            deleted_by=None,
        )
    )
    await _synchronize_files(existing_id, connection_id, message.attachments)
    return False


async def persist_inbound(
    message: ObservedMessengerMessage,
    *,
    connection_id: int,
    platform: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Persist an inbound message in an independent committed transaction."""
    async with get_db_session():
        return await record(
            message,
            connection_id=connection_id,
            platform=platform,
            direction="inbound",
            status="received",
            metadata=metadata,
        )


async def persist_outbound(
    message: ObservedMessengerMessage,
    *,
    connection_id: int,
    platform: str,
    status: str = "accepted",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Persist an outbound platform response in an independent transaction."""
    async with get_db_session():
        return await record(
            message,
            connection_id=connection_id,
            platform=platform,
            direction="outbound",
            status=status,
            metadata=metadata,
        )


def _message_from_record(
    row: Message,
    users_by_key: dict[tuple[int, str], MessengerUser],
    rooms_by_id: dict[UUID, Room],
    files: list[File],
    tool_codes: dict[int, str],
) -> Message:
    metadata = row.metadata_
    sender_id = (
        row.user_id
        if row.direction == "inbound"
        else str(metadata.get("sender_id") or "")
    )
    recipient_id = (
        str(metadata.get("recipient_id") or "")
        if row.direction == "inbound"
        else row.user_id
    )
    def local_user(external_id: str | None) -> MessengerUser | None:
        if not external_id:
            return None
        if row.tool_id is None:
            raise RuntimeError("A stored Messenger identity has no local Tool scope.")
        stored = users_by_key.get((row.tool_id, external_id))
        if stored is None:
            raise RuntimeError(
                "A stored Messenger message references an identity absent from messenger_users."
            )
        return stored

    if row.room_id and row.messenger_room_id is None:
        raise RuntimeError(
            "A stored Messenger message references a room without a local UUID."
        )
    row.sender = local_user(sender_id)
    row.recipient = local_user(recipient_id)
    row.room = (
        rooms_by_id.get(row.messenger_room_id)
        if row.messenger_room_id is not None
        else None
    )
    row.files = files
    row.tool_code = tool_codes.get(int(row.tool_id or 0), "")
    return row


async def _messages_from_records(
    rows: list[Message],
) -> list[Message]:
    """Build public messages only from journal and Messenger-user rows."""

    tool_ids = {row.tool_id for row in rows if row.tool_id is not None}
    from app.tools import get_tool_codes

    tool_codes = await get_tool_codes(tool_ids)
    external_ids: set[str] = set()
    for row in rows:
        metadata = row.metadata_
        values = (
            row.user_id if row.direction == "inbound" else metadata.get("sender_id"),
            metadata.get("recipient_id") if row.direction == "inbound" else row.user_id,
        )
        external_ids.update(str(value) for value in values if value)
    users = (
        list(
            (
                await get_db().scalars(
                    select(MessengerUser)
                    .where(
                        MessengerUser.tool_id.in_(tool_ids),
                        MessengerUser.external_id.in_(external_ids),
                    )
                    .execution_options(include_historized=True)
                )
            ).all()
        )
        if tool_ids and external_ids
        else []
    )
    await enrich_messenger_users(users)
    users_by_key = {(user.tool_id, user.external_id): user for user in users}
    room_ids = {
        row.messenger_room_id
        for row in rows
        if row.messenger_room_id is not None
    }
    rooms = (
        list(
            (
                await get_db().scalars(
                    select(Room)
                    .where(Room.id.in_(room_ids))
                    .execution_options(include_historized=True)
                )
            ).all()
        )
        if room_ids
        else []
    )
    rooms_by_id = {room.id: room for room in rooms}
    message_ids = [row.id for row in rows]
    files = (
        list(
            (
                await get_db().execute(
                    select(Attachment.message_id, File)
                    .join(
                        File,
                        File.id == Attachment.file_id,
                    )
                    .where(Attachment.message_id.in_(message_ids))
                    .order_by(
                        Attachment.message_id,
                        Attachment.position,
                    )
                )
            ).all()
        )
        if message_ids
        else []
    )
    files_by_message: dict[UUID, list[File]] = {}
    for message_id, file in files:
        files_by_message.setdefault(message_id, []).append(file)
    return [
        _message_from_record(
            row,
            users_by_key,
            rooms_by_id,
            files_by_message.get(row.id, []),
            tool_codes,
        )
        for row in rows
    ]


async def hydrate_messages(rows: list[Message]) -> list[Message]:
    """Return canonical messages with their local room, identities, and files loaded."""

    return await _messages_from_records(rows)


async def stored_message(
    *, connection_id: int, remote_message_id: str, direction: Direction
) -> Message | None:
    """Return one canonical message reconstructed exclusively from its local row."""

    async with get_db_session():
        row = await get_db().scalar(
            select(Message).where(
                Message.connection_id == connection_id,
                Message.remote_message_id == remote_message_id,
                Message.direction == direction,
            )
        )
        if row is None:
            return None
        return (await _messages_from_records([row]))[0]


async def synchronize_messages(
    *,
    connection_id: int,
    tool_id: int,
    self_id: str,
    messages: list[ObservedMessengerMessage],
    counts_as_unread: bool = False,
) -> list[Message]:
    """Idempotently import a remote batch and return only local reconstructions."""

    keys: list[tuple[str, Direction]] = []
    async with get_db_session():
        for source in messages:
            if not source.id:
                continue
            message = source.model_copy(deep=True)
            message.tool_id = tool_id
            if message.room is not None:
                message.room.connection_id = connection_id
                message.room.tool_id = tool_id
            for identity in (message.sender, message.recipient):
                if identity is not None:
                    identity.connection_id = connection_id
                    identity.tool_id = tool_id
            direction: Direction = (
                "outbound"
                if message.sender is not None and message.sender.id == self_id
                else "inbound"
            )
            await record(
                message,
                connection_id=connection_id,
                platform=message.platform or "messenger",
                direction=direction,
                status="sent" if direction == "outbound" else "received",
                counts_as_unread=counts_as_unread,
            )
            keys.append((message.id, direction))

        if not keys:
            return []
        rows = list(
            (
                await get_db().scalars(
                    select(Message).where(
                        Message.connection_id == connection_id,
                        Message.remote_message_id.in_(
                            [remote_id for remote_id, _direction in keys]
                        ),
                    )
                )
            ).all()
        )
        by_key = {(row.remote_message_id, cast(Direction, row.direction)): row for row in rows}
        messages_by_key = {
            (row.remote_message_id, cast(Direction, row.direction)): message
            for row, message in zip(rows, await _messages_from_records(rows), strict=True)
        }
        return [
            messages_by_key[key]
            for key in keys
            if key in by_key
        ]


def _history_scope(connection_id: int, room_id: str) -> str:
    value = f"{connection_id}\0{room_id}".encode()
    return hashlib.sha256(value).hexdigest()[:24]


def _encode_history_cursor(
    *,
    connection_id: int,
    room_id: str,
    created_at: datetime,
    record_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "s": _history_scope(connection_id, room_id),
            "t": created_at.isoformat(),
            "i": str(record_id),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_history_cursor(
    cursor: str,
    *,
    connection_id: int,
    room_id: str,
) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode())
        decoded = cast(object, json.loads(raw))
        if not isinstance(decoded, dict):
            raise ValueError
        payload = cast(dict[str, object], decoded)
        if payload.get("v") != 1 or payload.get("s") != _history_scope(
            connection_id, room_id
        ):
            raise ValueError
        created_at = datetime.fromisoformat(str(payload["t"]))
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(str(payload["i"]))
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid or out-of-scope room history cursor.") from exc


async def history_page(
    connection_id: int,
    room_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> HistoryPage[Message]:
    """Read one stable page from newest to oldest without offset drift.

    Messages inside the returned page remain chronological. Pass ``next_cursor`` back to
    continue with messages older than the current page.
    """
    if not 1 <= limit <= _MAX_HISTORY_PAGE_SIZE:
        raise ValueError(
            f"Room history limit must be between 1 and {_MAX_HISTORY_PAGE_SIZE}."
        )

    statement = select(Message).where(
        Message.connection_id == connection_id,
        Message.room_id == room_id,
    )
    if cursor:
        created_at, record_id = _decode_history_cursor(
            cursor,
            connection_id=connection_id,
            room_id=room_id,
        )
        statement = statement.where(
            or_(
                Message.created_at < created_at,
                and_(
                    Message.created_at == created_at,
                    Message.id < record_id,
                ),
            )
        )

    async with get_db_session():
        rows = list(
            (
                await get_db().scalars(
                    statement.order_by(
                        Message.created_at.desc(),
                        Message.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        messages = await _messages_from_records(rows[:limit])

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        _encode_history_cursor(
            connection_id=connection_id,
            room_id=room_id,
            created_at=page_rows[-1].created_at,
            record_id=page_rows[-1].id,
        )
        if has_more and page_rows
        else None
    )
    return HistoryPage(
        messages=list(reversed(messages)),
        has_more=has_more,
        next_cursor=next_cursor,
    )


async def history(connection_id: int, room_id: str, limit: int = 20) -> list[Message]:
    """Read a conversation from the canonical journal in chronological order."""
    safe_limit = max(1, min(int(limit or 20), 200))
    page = await history_page(connection_id, room_id, limit=safe_limit)
    return page.messages


async def latest_inbound_at(connection_id: int, user_id: str) -> datetime | None:
    """Return the last inbound timestamp used by WhatsApp's service window."""
    async with get_db_session():
        return await get_db().scalar(
                select(func.max(Message.created_at)).where(
                    Message.connection_id == connection_id,
                    Message.direction == "inbound",
                    Message.user_id == user_id,
                )
            )


async def update_delivery_status(
    *,
    connection_id: int,
    remote_message_id: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Advance one outbound delivery status without regressing late receipts."""
    if not remote_message_id:
        return False
    ranks = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}
    async with get_db_session():
        record = await get_db().scalar(
            select(Message)
            .where(
                Message.connection_id == connection_id,
                Message.remote_message_id == remote_message_id,
                Message.direction == "outbound",
            )
            .with_for_update()
        )
        if record is None:
            return False
        normalized = _bounded(status, 50)
        current_rank = ranks.get(record.status)
        next_rank = ranks.get(normalized)
        if current_rank is not None and next_rank is None and normalized != "failed":
            return False
        if current_rank is not None and next_rank is not None and next_rank < current_rank:
            return False
        if record.status in {"failed", "deleted"} and normalized != record.status:
            return False
        if normalized == "failed" and current_rank is not None and current_rank >= 2:
            return False
        record.status = normalized
        record.last_error = _bounded(error) or None
        return True


async def update_inbound_admission_status(
    *,
    connection_id: int,
    remote_message_id: str,
    status: Literal["admitted", "failed"],
    error: str | None = None,
) -> bool:
    """Persist whether an inbound message reached its configured admission policy."""

    if not remote_message_id:
        return False
    async with get_db_session():
        record = await get_db().scalar(
            select(Message).where(
                Message.connection_id == connection_id,
                Message.remote_message_id == remote_message_id,
                Message.direction == "inbound",
            )
        )
        if record is None:
            return False
        record.status = status
        record.last_error = _bounded(error) or None
        return True


async def listener_cursor(connection_id: int) -> str | None:
    async with get_db_session():
        return await get_db().scalar(
            select(ListenerState.cursor).where(
                ListenerState.connection_id == connection_id
            )
        )


async def update_listener_state(
    connection_id: int,
    platform: str,
    *,
    cursor: str | None = None,
    available: bool,
    error: str | None = None,
    event_received: bool = False,
    reconnect: bool = False,
) -> None:
    """Upsert a listener cursor and bounded health metadata."""
    values: dict[str, Any] = {
        "connection_id": connection_id,
        "platform": platform,
        "cursor": cursor,
        "available": available,
        "last_error": _bounded(error) or None,
        "last_event_at": func.now() if event_received else None,
        "reconnect_count": 1 if reconnect else 0,
    }
    updates: dict[str, Any] = {
        "platform": platform,
        "available": available,
        "last_error": _bounded(error) or None,
        "updated_at": func.now(),
    }
    if cursor is not None:
        updates["cursor"] = cursor
    if event_received:
        updates["last_event_at"] = func.now()
    if reconnect:
        updates["reconnect_count"] = ListenerState.reconnect_count + 1
    async with get_db_session():
        await get_db().execute(
            pg_insert(ListenerState)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ListenerState.connection_id],
                set_=updates,
            )
        )
