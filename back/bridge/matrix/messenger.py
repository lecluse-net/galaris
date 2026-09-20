"""
Matrix implementation of ``app.messenger.Messenger``.

It wraps the low-level ``Matrix`` client and converts Matrix events to and from
canonical messages. Galaris receives messages as a homeserver client through
the ``/sync`` long poll.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, List, Literal, Optional

from loguru import logger

from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger import journal
from app.messenger.inbound import dispatch_incoming
from app.messenger.interface import HistoryPage, Messenger
from app.messenger.media import normalized_voice_note
from app.messenger.models import Capability, kind_from_mime
from core.params import runtime_settings
from core.util import as_dict, as_list

from .client import Matrix, MatrixMessageEvent
from .events import MatrixRoomEvent, matrix_event_bus

_KIND = "matrix"
_CAPABILITIES = {
    Capability.SEND,
    Capability.HISTORY,
    Capability.FILES,
    Capability.SEARCH_USERS,
    Capability.VOICE_NOTES,
}
# Maximum exponential backoff after /sync errors, in seconds.
_SYNC_ERROR_BACKOFF_MAX = 120.0
_MEDIA_MSGTYPES = frozenset({"m.image", "m.file", "m.audio", "m.video"})
_SUPPORTED_MSGTYPES = frozenset(
    {"", "m.text", "m.emote", "m.image", "m.file", "m.audio", "m.video"}
)
_MEDIA_DEFAULT_MIME = {
    "m.image": "image/jpeg",
    "m.file": "application/octet-stream",
    "m.audio": "audio/ogg",
    "m.video": "video/mp4",
}


def _safe_filename(value: str, fallback: str = "file") -> str:
    """Return a bounded display filename without path components."""

    normalized = value.replace("\\", "/").split("/")[-1].replace("\x00", "").strip()
    return (normalized or fallback)[:255]


def _optional_size(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        size = int(value) if isinstance(value, (int, str)) else None
    except ValueError:
        return None
    return size if size is not None and size >= 0 else None


def _reply_to(event: MatrixMessageEvent) -> str | None:
    reply = as_dict(event.content.relates_to.get("m.in_reply_to"))
    event_id = str(reply.get("event_id") or "")
    return event_id or None


def _is_replacement(event: MatrixMessageEvent) -> bool:
    return str(event.content.relates_to.get("rel_type") or "") == "m.replace"


def _strip_reply_fallback(body: str) -> str:
    """Strip Matrix's plain-text rich-reply fallback when one is present."""

    lines = body.splitlines()
    if not lines or not lines[0].startswith("> "):
        return body
    for index, line in enumerate(lines):
        if not line.strip():
            return "\n".join(lines[index + 1 :]).strip()
        if not line.startswith("> "):
            return body
    return body


def _matrix_attachment(event: MatrixMessageEvent) -> ObservedMessengerFile | None:
    content = event.content
    if content.msgtype not in _MEDIA_MSGTYPES or not content.url:
        return None
    info = content.info
    mime = str(
        info.get("mimetype")
        or _MEDIA_DEFAULT_MIME.get(content.msgtype or "", "application/octet-stream")
    )
    filename = _safe_filename(
        content.filename or content.body,
        fallback=f"matrix-{event.event_id.removeprefix('$') or 'media'}",
    )
    return ObservedMessengerFile(
        id=content.url,
        name=filename,
        mime=mime,
        url=content.url,
        size=_optional_size(info.get("size")),
        kind=kind_from_mime(mime),
    )


def _canonical_text(event: MatrixMessageEvent, attachment: ObservedMessengerFile | None) -> str:
    body = _strip_reply_fallback(event.content.body)
    if attachment is not None and (
        not event.content.filename or event.content.filename == event.content.body
    ):
        return ""
    return body


def matrix_to_message(
    event: MatrixMessageEvent,
    room_id: str,
    self_id: str,
    tool_id: int = 0,
    connection_id: int | None = None,
    room_kind: Literal["direct", "group"] = "group",
) -> ObservedMessengerMessage:
    """Convert a Matrix ``m.room.message`` event to a canonical message.

    ``recipient`` is the receiving bot so inbound routing can resolve the target agent.
    """
    attachment = _matrix_attachment(event)
    return ObservedMessengerMessage(
        id=event.event_id,
        platform=_KIND,
        tool_id=tool_id,
        sender=ObservedMessengerUser(id=event.sender, connection_id=connection_id, tool_id=tool_id),
        recipient=(
            ObservedMessengerUser(id=self_id, connection_id=connection_id, tool_id=tool_id)
            if event.sender != self_id
            else None
        ),
        room=ObservedMessengerRoom(
            id=room_id or (event.room_id or ""),
            kind=room_kind,
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        # Matrix timestamps are milliseconds; canonical messages use seconds.
        text=_canonical_text(event, attachment),
        attachments=[attachment] if attachment is not None else [],
        reply_to=_reply_to(event),
        time=int(event.origin_server_ts // 1000),
    )


class MatrixMessenger(Messenger):
    """Internal Matrix messaging backend with Galaris as homeserver client."""

    kind = _KIND
    capabilities = _CAPABILITIES

    def __init__(self, matrix: Matrix, connection_id: Optional[int] = None) -> None:
        self._matrix = matrix
        self.tool_id = matrix.tool_id
        self.self_id = matrix.user_id
        self.connection_id = connection_id
        self._direct_room_ids: frozenset[str] = frozenset()

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "MatrixMessenger":
        return cls(await Matrix.from_connection_id(connection_id), connection_id)

    async def check_connection(self) -> str:
        self.self_id = await self._matrix.whoami()
        return self.self_id

    async def close(self) -> None:
        await self._matrix.aclose()

    # -- Sending ---------------------------------------------------------------

    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        # A Matrix room ID represents either a group or a direct conversation.
        await self._require_unencrypted_room(room_id)
        res = await self._matrix.send_message(room_id, text, reply_to=reply_to)
        event_id = str(res.get("event_id") or "")
        if not event_id:
            raise ValueError("Matrix send response has no event_id")
        return ObservedMessengerMessage(
            id=event_id,
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=room_id,
                kind="direct" if room_id in self._direct_room_ids else "group",
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
            reply_to=reply_to,
        )

    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        room = await self.ensure_direct_room(user_id)
        return await self.send_to_room(room.id, text)

    # -- Reading ---------------------------------------------------------------

    async def history(self, room_id: str, limit: int = 20) -> List[ObservedMessengerMessage]:
        safe_limit = max(1, min(int(limit or 20), 200))
        page = await self.history_page(room_id, safe_limit)
        return page.messages

    async def history_page(
        self,
        room_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[ObservedMessengerMessage]:
        if not 1 <= limit <= 500:
            raise ValueError("Matrix room history limit must be between 1 and 500.")
        direct_rooms = await self._matrix.direct_room_ids()
        chunk, next_cursor = await self._matrix.get_room_messages_page(
            room_id,
            limit=limit,
            from_token=cursor,
        )
        messages: List[ObservedMessengerMessage] = []
        # ``dir=b`` returns newest first; restore chronological order.
        for raw in reversed(chunk):
            if raw.get("type") != "m.room.message":
                continue
            try:
                event = MatrixMessageEvent.model_validate(raw)
            except ValueError:
                continue
            if not self._is_supported_message(event):
                continue
            messages.append(
                matrix_to_message(
                    event,
                    room_id,
                    self.self_id,
                    self.tool_id,
                    self.connection_id,
                    "direct" if room_id in direct_rooms else "group",
                )
            )
        return HistoryPage(
            messages=messages,
            has_more=next_cursor is not None,
            next_cursor=next_cursor,
        )

    async def search_users(self, query: str) -> List[ObservedMessengerUser]:
        return [
            ObservedMessengerUser(
                id=str(item.get("user_id") or ""),
                display_name=str(item.get("display_name") or item.get("user_id") or ""),
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            )
            for item in await self._matrix.search_users(query)
            if item.get("user_id")
        ]

    # ── Rooms ──────────────────────────────────────────────────────────────────

    async def ensure_direct_room(self, user_id: str) -> ObservedMessengerRoom:
        room_id = await self._matrix.ensure_direct_room(user_id)
        self._direct_room_ids = self._direct_room_ids | {room_id}
        return ObservedMessengerRoom(
            id=room_id,
            kind="direct",
            connection_id=self.connection_id,
            tool_id=self.tool_id,
        )

    # -- Attachments -----------------------------------------------------------

    async def _require_unencrypted_room(self, room_id: str) -> None:
        if await self._matrix.room_is_encrypted(room_id):
            raise ValueError(
                "Encrypted Matrix rooms are not supported; refusing a plaintext send"
            )

    @staticmethod
    def _media_msgtype(mime: str) -> str:
        kind = kind_from_mime(mime)
        return {
            "image": "m.image",
            "audio": "m.audio",
            "video": "m.video",
        }.get(kind, "m.file")

    def _outbound_media_message(
        self,
        *,
        event_id: str,
        room_id: str,
        content_uri: str,
        filename: str,
        mime: str,
        size: int,
        caption: str = "",
        reply_to: str | None = None,
    ) -> ObservedMessengerMessage:
        if not event_id:
            raise ValueError("Matrix media send response has no event_id")
        attachment = ObservedMessengerFile(
            id=content_uri,
            name=filename,
            mime=mime,
            url=content_uri,
            size=size,
            kind=kind_from_mime(mime),
        )
        return ObservedMessengerMessage(
            id=event_id,
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=room_id,
                kind="direct" if room_id in self._direct_room_ids else "group",
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=caption,
            attachments=[attachment],
            reply_to=reply_to,
        )

    async def _send_uploaded_media(
        self,
        *,
        room_id: str,
        content_uri: str,
        filename: str,
        mime: str,
        size: int,
        caption: str = "",
        reply_to: str | None = None,
        voice: bool = False,
    ) -> ObservedMessengerMessage:
        body = caption or filename
        content: dict[str, Any] = {
            "msgtype": self._media_msgtype(mime),
            "body": body,
            "filename": filename,
            "url": content_uri,
            "info": {
                "mimetype": mime,
                "size": size,
            },
        }
        if reply_to:
            content["m.relates_to"] = {
                "m.in_reply_to": {"event_id": reply_to}
            }
        if voice:
            # MSC3245 is understood by Element-family clients while ``m.audio``
            # remains the stable interoperable fallback.
            content["org.matrix.msc3245.voice"] = {}
        response = await self._matrix.send_room_event(
            room_id,
            "m.room.message",
            content,
        )
        return self._outbound_media_message(
            event_id=str(response.get("event_id") or ""),
            room_id=room_id,
            content_uri=content_uri,
            filename=filename,
            mime=mime,
            size=size,
            caption=caption,
            reply_to=reply_to,
        )

    async def upload_file(
        self,
        room_id: str,
        path_or_bytes: str | bytes,
        name: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        if isinstance(path_or_bytes, str):
            return await self.upload_file_path(
                room_id,
                Path(path_or_bytes),
                name=name,
            )
        await self._require_unencrypted_room(room_id)
        filename = _safe_filename(name or "file")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        content_uri = await self._matrix.upload_media(
            path_or_bytes,
            filename,
            mime,
        )
        return await self._send_uploaded_media(
            room_id=room_id,
            content_uri=content_uri,
            filename=filename,
            mime=mime,
            size=len(path_or_bytes),
        )

    async def upload_file_path(
        self,
        room_id: str,
        path: Path,
        name: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        await self._require_unencrypted_room(room_id)
        filename = _safe_filename(name or path.name)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        size = path.stat().st_size
        content_uri = await self._matrix.upload_media_path(
            path,
            filename,
            mime,
        )
        return await self._send_uploaded_media(
            room_id=room_id,
            content_uri=content_uri,
            filename=filename,
            mime=mime,
            size=size,
        )

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        content_uri = attachment.url or attachment.id
        if not content_uri:
            raise ValueError("Matrix attachment has no content URI")
        if (
            attachment.size is not None
            and attachment.size > self._matrix.media_max_bytes
        ):
            raise ValueError("Matrix media exceeds the configured size limit")
        return await self._matrix.download_media(content_uri)

    async def fetch_attachment_to_file(
        self,
        attachment: ObservedMessengerFile,
        dest: Path,
        *, max_bytes: int = 512 * 1024 * 1024,
    ) -> int:
        content_uri = attachment.url or attachment.id
        if not content_uri:
            raise ValueError("Matrix attachment has no content URI")
        if (
            attachment.size is not None
            and attachment.size > self._matrix.media_max_bytes
        ):
            raise ValueError("Matrix media exceeds the configured size limit")
        return await self._matrix.download_media_to_file(content_uri, dest, max_bytes=max_bytes)

    async def send_voice_note(
        self,
        room_id: str,
        path: Path,
        *,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        await self._require_unencrypted_room(room_id)
        async with normalized_voice_note(
            path,
            max_input_bytes=self._matrix.media_max_bytes,
            max_output_bytes=self._matrix.media_max_bytes,
            max_duration_seconds=runtime_settings.messenger_voice_max_duration_seconds,
        ) as normalized:
            filename = _safe_filename(normalized.name, "voice.ogg")
            size = normalized.stat().st_size
            content_uri = await self._matrix.upload_media_path(
                normalized,
                filename,
                "audio/ogg",
            )
            return await self._send_uploaded_media(
                room_id=room_id,
                content_uri=content_uri,
                filename=filename,
                mime="audio/ogg",
                size=size,
                caption=caption or "",
                reply_to=reply_to,
                voice=True,
            )

    # -- Inbound reception through /sync long polling --------------------------

    def _sync_direct_room_ids(self, data: dict[str, Any]) -> None:
        events = as_list(as_dict(data.get("account_data")).get("events"))
        for raw in events:
            event = as_dict(raw)
            if event.get("type") != "m.direct":
                continue
            direct = as_dict(event.get("content"))
            self._direct_room_ids = frozenset(
                str(room_id)
                for room_ids in direct.values()
                for room_id in as_list(room_ids)
                if room_id
            )

    def _base_authorized(self, room_id: str, sender: str) -> bool:
        if (
            self._matrix.allowed_room_ids
            and room_id not in self._matrix.allowed_room_ids
        ):
            return False
        return not (
            self._matrix.allowed_user_ids
            and sender not in self._matrix.allowed_user_ids
        )

    def _authorized_message(
        self,
        event: MatrixMessageEvent,
        room_id: str,
    ) -> bool:
        if not self._base_authorized(room_id, event.sender):
            return False
        if (
            not self._matrix.require_group_mention
            or room_id in self._direct_room_ids
        ):
            return True
        mentioned = {
            str(user_id)
            for user_id in as_list(event.content.mentions.get("user_ids"))
        }
        return (
            self.self_id in mentioned
            or self.self_id.casefold() in event.content.body.casefold()
        )

    @staticmethod
    def _is_supported_message(event: MatrixMessageEvent) -> bool:
        if not event.event_id or not event.sender or _is_replacement(event):
            return False
        msgtype = event.content.msgtype or ""
        if msgtype == "m.notice" or msgtype not in _SUPPORTED_MSGTYPES:
            return False
        if msgtype in _MEDIA_MSGTYPES:
            # Encrypted attachments require Megolm/file-key handling that this
            # bridge intentionally does not claim.
            return bool(event.content.url and not event.content.encrypted_file)
        return bool(event.content.body)

    async def _join_invited_rooms(self, data: dict[str, Any]) -> bool:
        if not self._matrix.auto_join_invites:
            return False
        if not (
            self._matrix.allowed_room_ids or self._matrix.allowed_user_ids
        ):
            logger.warning(
                "Matrix auto-join disabled at runtime connection={} reason=no_allowlist",
                self.connection_id,
            )
            return False

        joined = False
        invited = as_dict(as_dict(data.get("rooms")).get("invite"))
        for room_id, raw_room in invited.items():
            room = as_dict(raw_room)
            invite_events = as_list(
                as_dict(room.get("invite_state")).get("events")
            )
            if any(
                as_dict(item).get("type") == "m.room.encryption"
                for item in invite_events
            ):
                continue
            membership: dict[str, Any] | None = None
            for item in invite_events:
                event = as_dict(item)
                if (
                    event.get("type") == "m.room.member"
                    and str(event.get("state_key") or "") == self.self_id
                    and as_dict(event.get("content")).get("membership") == "invite"
                ):
                    membership = event
                    break
            if membership is None:
                continue
            inviter = str(membership.get("sender") or "")
            if not self._base_authorized(str(room_id), inviter):
                continue
            await self._matrix.join_room(str(room_id))
            if as_dict(membership.get("content")).get("is_direct") is True:
                self._direct_room_ids = self._direct_room_ids | {str(room_id)}
            joined = True
            logger.info(
                "Matrix invitation accepted connection={}",
                self.connection_id,
            )
        return joined

    async def _dispatch_sync(
        self,
        data: dict[str, Any],
        *,
        process_timeline: bool = True,
    ) -> bool:
        """Admit every relevant event from one sync response.

        Returning only after the full response has been processed lets ``listen``
        persist ``next_batch`` as the acknowledgement boundary. A failure leaves
        the previous cursor intact so Matrix can redeliver the whole response.
        """
        self._sync_direct_room_ids(data)
        event_received = await self._join_invited_rooms(data)
        if not process_timeline:
            return event_received

        joined = as_dict(as_dict(data.get("rooms")).get("join"))
        for raw_room_id, raw_room in joined.items():
            room_id = str(raw_room_id)
            room = as_dict(raw_room)
            events = as_list(as_dict(room.get("timeline")).get("events"))
            for raw_event in events:
                raw = as_dict(raw_event)
                event_type = str(raw.get("type") or "")
                event_id = str(raw.get("event_id") or "")
                sender = str(raw.get("sender") or "")
                if (
                    event_type.startswith("m.call.")
                    and self.connection_id is not None
                    and event_id
                    and sender
                    and self._base_authorized(room_id, sender)
                ):
                    await matrix_event_bus.publish(
                        MatrixRoomEvent(
                            connection_id=self.connection_id,
                            room_id=room_id,
                            event_id=event_id,
                            sender=sender,
                            type=event_type,
                            content=as_dict(raw.get("content")),
                            origin_server_ts=int(raw.get("origin_server_ts") or 0),
                            raw=raw,
                        )
                    )
                    event_received = True
                if raw.get("type") != "m.room.message":
                    continue
                if raw.get("sender") == self.self_id:
                    continue  # Prevent echoing our own messages.
                try:
                    event = MatrixMessageEvent.model_validate(raw)
                except ValueError:
                    logger.warning(
                        "Matrix ignored malformed room message connection={}",
                        self.connection_id,
                    )
                    continue
                if (
                    not self._is_supported_message(event)
                    or not self._authorized_message(event, room_id)
                ):
                    continue
                msg = matrix_to_message(
                    event,
                    room_id,
                    self.self_id,
                    self.tool_id,
                    self.connection_id,
                    "direct" if room_id in self._direct_room_ids else "group",
                )
                await dispatch_incoming(msg)
                event_received = True
        return event_received

    async def listen(self) -> None:
        """Deliver every inbound ``/sync`` message to ``dispatch_incoming``.

        The Matrix ``next_batch`` token is persisted per connection only after
        every event in the response has reached its durable canonical admission
        point. Replaying a response is safe because message and call event IDs are
        deduplicated independently.
        """
        if self.connection_id is None:
            raise RuntimeError("A Matrix listener requires a connection ID")

        try:
            self.self_id = await self._matrix.whoami()
            self._direct_room_ids = await self._matrix.direct_room_ids()
            since = await journal.listener_cursor(self.connection_id)
            logger.info(
                "Matrix listener started connection={} resumed={}",
                self.connection_id,
                since is not None,
            )

            backoff = 1.0
            while True:
                try:
                    data = await self._matrix.sync(
                        since=since,
                        timeout_ms=0 if since is None else None,
                    )
                    next_cursor = data.get("next_batch")
                    if not isinstance(next_cursor, str) or not next_cursor:
                        raise ValueError("Matrix sync response has no next_batch cursor")
                    event_received = await self._dispatch_sync(
                        data,
                        process_timeline=True,
                    )
                    await journal.update_listener_state(
                        self.connection_id,
                        self.kind,
                        cursor=next_cursor,
                        available=True,
                        event_received=event_received,
                    )
                    since = next_cursor
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    try:
                        await journal.update_listener_state(
                            self.connection_id,
                            self.kind,
                            cursor=since,
                            available=False,
                            error=type(exc).__name__,
                            reconnect=True,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as state_exc:
                        logger.warning(
                            "Matrix listener health update failed connection={} type={}",
                            self.connection_id,
                            type(state_exc).__name__,
                        )
                    logger.warning(
                        "Matrix listener error connection={} cursor_preserved={} "
                        "retry_in={}s type={}",
                        self.connection_id,
                        since is not None,
                        backoff,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _SYNC_ERROR_BACKOFF_MAX)
        finally:
            try:
                await self._matrix.aclose()
            except Exception as exc:
                logger.debug(
                    "Matrix listener cleanup failed connection={} type={}",
                    self.connection_id,
                    type(exc).__name__,
                )
