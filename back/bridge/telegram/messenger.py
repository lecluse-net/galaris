"""Telegram Bot API implementation of the canonical Messenger contract."""

from __future__ import annotations

import asyncio
import mimetypes
import re
import time
from pathlib import Path
from core.util import read_buffered_file, buffered_io_budget
from typing import Iterable, Optional, Sequence

from loguru import logger
from telegram import Message as TelegramMessage, Update, User as TelegramUser

from app.messenger import journal
from app.messenger.inbound import dispatch_incoming
from app.messenger.interface import HistoryPage, Messenger
from app.messenger.media import normalized_voice_note
from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import Capability, kind_from_mime
from core.params import runtime_settings

from .client import TelegramClient
from .schemas import TelegramConnectionConfig

_KIND = "telegram"
_CAPABILITIES = {
    Capability.SEND,
    Capability.HISTORY,
    Capability.FILES,
    Capability.VOICE_NOTES,
}
_MAX_TEXT = 4_096
_SYNC_ERROR_BACKOFF_MAX = 120.0
_ALBUM_SETTLE_SECONDS = 0.35
_ALBUM_SETTLE_ROUNDS = 3
_TELEGRAM_CONTENT_MAX_BYTES = 20_000_000


def _canonical_id(chat_id: int | str, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _reply_message_id(value: str | None) -> int | None:
    if not value:
        return None
    tail = value.rsplit(":", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None


def _chunks(text: str, limit: int = _MAX_TEXT) -> list[str]:
    """Split text without changing order and prefer line/word boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = max(remaining.rfind("\n", 0, limit + 1), remaining.rfind(" ", 0, limit + 1))
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [part for part in chunks if part]


def _telegram_attachments(messages: Iterable[TelegramMessage]) -> list[ObservedMessengerFile]:
    attachments: list[ObservedMessengerFile] = []
    for native in messages:
        if native.photo:
            photo = native.photo[-1]
            attachments.append(
                ObservedMessengerFile(
                    id=photo.file_id,
                    name=f"photo-{photo.file_unique_id}.jpg",
                    mime="image/jpeg",
                    size=photo.file_size,
                    kind="image",
                )
            )
        document = native.document
        if document is not None:
            mime = document.mime_type or "application/octet-stream"
            attachments.append(
                ObservedMessengerFile(
                    id=document.file_id,
                    name=document.file_name or f"document-{document.file_unique_id}",
                    mime=mime,
                    size=document.file_size,
                    kind=kind_from_mime(mime),
                )
            )
        audio = native.audio
        if audio is not None:
            mime = audio.mime_type or "audio/mpeg"
            attachments.append(
                ObservedMessengerFile(
                    id=audio.file_id,
                    name=audio.file_name or f"audio-{audio.file_unique_id}",
                    mime=mime,
                    size=audio.file_size,
                    kind="audio",
                )
            )
        voice = native.voice
        if voice is not None:
            attachments.append(
                ObservedMessengerFile(
                    id=voice.file_id,
                    name=f"voice-{voice.file_unique_id}.ogg",
                    mime=voice.mime_type or "audio/ogg",
                    size=voice.file_size,
                    kind="audio",
                )
            )
        video = native.video
        if video is not None:
            mime = video.mime_type or "video/mp4"
            attachments.append(
                ObservedMessengerFile(
                    id=video.file_id,
                    name=video.file_name or f"video-{video.file_unique_id}.mp4",
                    mime=mime,
                    size=video.file_size,
                    kind="video",
                )
            )
    return attachments


def telegram_to_message(
    messages: Sequence[TelegramMessage],
    *,
    self_user: TelegramUser,
    tool_id: int,
    connection_id: int,
) -> ObservedMessengerMessage:
    """Convert one native message or one media album to a canonical message."""
    if not messages:
        raise ValueError("A Telegram message batch cannot be empty")
    primary = next(
        (item for item in messages if item.text or item.caption),
        messages[0],
    )
    sender = primary.from_user
    chat = primary.chat
    text = primary.text or primary.caption or ""
    reply = primary.reply_to_message
    display_name = sender.full_name if sender is not None else ""
    chat_type = str(chat.type)
    return ObservedMessengerMessage(
        id=_canonical_id(chat.id, primary.message_id),
        platform=_KIND,
        tool_id=tool_id,
        sender=ObservedMessengerUser(
            id=str(sender.id) if sender is not None else "",
            display_name=display_name,
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        recipient=ObservedMessengerUser(
            id=str(self_user.id),
            display_name=self_user.full_name,
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        room=ObservedMessengerRoom(
            id=str(chat.id),
            label=chat.title or chat.full_name or chat.username or str(chat.id),
            kind="direct" if chat_type == "private" else "group",
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        text=text,
        attachments=_telegram_attachments(messages),
        reply_to=(
            _canonical_id(chat.id, reply.message_id) if reply is not None else None
        ),
        time=int(primary.date.timestamp()),
    )


class TelegramMessenger(Messenger):
    kind = _KIND
    capabilities = _CAPABILITIES
    provider_history = False

    def __init__(
        self,
        client: TelegramClient,
        config: TelegramConnectionConfig,
        self_user: TelegramUser,
        *,
        tool_id: int,
        connection_id: int,
    ) -> None:
        self.client = client
        self.config = config
        self.self_user = self_user
        self.self_id = str(self_user.id)
        self.tool_id = tool_id
        self.connection_id = connection_id

    @property
    def _content_max_bytes(self) -> int:
        return min(
            runtime_settings.messenger_content_max_bytes,
            _TELEGRAM_CONTENT_MAX_BYTES,
        )

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "TelegramMessenger":
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            connection_id,
            expected_service="telegram",
        )
        params = resolved.params
        config = TelegramConnectionConfig.model_validate(
            {
                **params,
                "bot_token": params.get("token", ""),
            }
        )
        client = TelegramClient(config.bot_token)
        try:
            self_user = await client.initialize()
        except Exception:
            await client.aclose()
            raise
        return cls(
            client,
            config,
            self_user,
            tool_id=resolved.tool_id,
            connection_id=connection_id,
        )

    async def check_connection(self) -> str:
        username = self.self_user.username or self.self_user.full_name
        return f"@{username}" if self.self_user.username else username

    async def close(self) -> None:
        await self.client.aclose()

    def _outbound_message(
        self,
        native: TelegramMessage,
        room_id: str,
        text: str,
        *,
        reply_to: str | None = None,
        attachment: ObservedMessengerFile | None = None,
    ) -> ObservedMessengerMessage:
        return ObservedMessengerMessage(
            id=_canonical_id(room_id, native.message_id),
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                display_name=self.self_user.full_name,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=room_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
            attachments=[attachment] if attachment is not None else [],
            reply_to=reply_to,
            time=int(native.date.timestamp()),
        )

    async def _record_outbound(self, message: ObservedMessengerMessage) -> None:
        await journal.persist_outbound(
            message,
            connection_id=self.connection_id,
            platform=self.kind,
            status="sent",
        )

    def _require_allowed_target(self, room_id: str) -> None:
        try:
            target = int(room_id)
        except ValueError as exc:
            raise ValueError("Telegram targets must be numeric chat IDs") from exc
        if target not in self.config.users and target not in self.config.chats:
            raise ValueError("Telegram target is not present in an allowlist")

    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        self._require_allowed_target(room_id)
        parts = _chunks(text)
        if not parts:
            raise ValueError("Telegram cannot send an empty text message")
        result: ObservedMessengerMessage | None = None
        for index, part in enumerate(parts):
            native = await self.client.send_text(
                room_id,
                part,
                reply_to=_reply_message_id(reply_to) if index == 0 else None,
            )
            result = self._outbound_message(
                native,
                room_id,
                part,
                reply_to=reply_to if index == 0 else None,
            )
            await self._record_outbound(result)
        if result is None:
            raise RuntimeError("Telegram returned no sent message")
        return result

    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        return await self.send_to_room(user_id, text)

    async def history(self, room_id: str, limit: int = 20) -> list[ObservedMessengerMessage]:
        del room_id, limit
        return []

    async def history_page(
        self,
        room_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[ObservedMessengerMessage]:
        del room_id, limit, cursor
        return HistoryPage(messages=[], has_more=False, next_cursor=None)

    async def ensure_direct_room(self, user_id: str) -> ObservedMessengerRoom:
        return ObservedMessengerRoom(
            id=user_id,
            kind="direct",
            connection_id=self.connection_id,
            tool_id=self.tool_id,
        )

    async def upload_file(
        self,
        room_id: str,
        path_or_bytes: str | bytes,
        name: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        size = Path(path_or_bytes).stat().st_size if isinstance(path_or_bytes, str) else len(path_or_bytes)
        async with buffered_io_budget.reserve(max(1, size * 3), owner=f"telegram:{self.connection_id}:{room_id}"):
            return await self._upload_file(room_id, path_or_bytes, name, max_bytes=min(size, self._content_max_bytes))

    async def _upload_file(
        self,
        room_id: str,
        path_or_bytes: str | bytes,
        name: Optional[str] = None,
        *, max_bytes: int | None = None,
    ) -> ObservedMessengerMessage:
        self._require_allowed_target(room_id)
        if isinstance(path_or_bytes, str):
            source = Path(path_or_bytes)
            if source.stat().st_size > self._content_max_bytes:
                raise ValueError("Telegram media exceeds the configured size limit")
            content = await read_buffered_file(source, max_bytes=self._content_max_bytes if max_bytes is None else max_bytes)
        else:
            content = path_or_bytes
        if len(content) > self._content_max_bytes:
            raise ValueError("Telegram media exceeds the configured size limit")
        filename = name or (Path(path_or_bytes).name if isinstance(path_or_bytes, str) else "file")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        native = await self.client.send_file(room_id, content, filename, mime)
        attachment = ObservedMessengerFile(
            name=filename,
            mime=mime,
            size=len(content),
            kind=kind_from_mime(mime),
        )
        result = self._outbound_message(native, room_id, "", attachment=attachment)
        await self._record_outbound(result)
        return result

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        content = await self.client.download(attachment.id)
        if len(content) > self._content_max_bytes:
            raise ValueError("Telegram media exceeds the configured size limit")
        return content

    async def fetch_attachment_to_file(self, attachment: ObservedMessengerFile, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        return await self.client.download_to_file(attachment.id, dest, max_bytes=min(max_bytes, self._content_max_bytes))

    async def send_voice_note(
        self,
        room_id: str,
        path: Path,
        *,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        self._require_allowed_target(room_id)
        async with normalized_voice_note(
            path,
            max_input_bytes=self._content_max_bytes,
            max_output_bytes=self._content_max_bytes,
            max_duration_seconds=runtime_settings.messenger_voice_max_duration_seconds,
        ) as normalized:
            native = await self.client.send_voice(
                room_id,
                normalized,
                caption=caption,
                reply_to=_reply_message_id(reply_to),
            )
            attachment = ObservedMessengerFile(
                name=normalized.name,
                mime="audio/ogg",
                size=normalized.stat().st_size,
                kind="audio",
            )
            result = self._outbound_message(
                native,
                room_id,
                caption or "",
                reply_to=reply_to,
                attachment=attachment,
            )
            await self._record_outbound(result)
            return result

    def _authorized(self, native: TelegramMessage) -> bool:
        sender = native.from_user
        if sender is None or sender.is_bot:
            return False
        chat_type = str(native.chat.type)
        if chat_type == "private":
            return sender.id in self.config.users or native.chat.id in self.config.chats
        if native.chat.id not in self.config.chats:
            return False
        if self.config.users and sender.id not in self.config.users:
            return False
        return self._mentioned(native)

    def _mentioned(self, native: TelegramMessage) -> bool:
        if not self.config.require_group_mention:
            return True
        reply = native.reply_to_message
        if reply is not None and reply.from_user is not None:
            if reply.from_user.id == self.self_user.id:
                return True
        username = self.self_user.username
        if not username:
            return False
        content = native.text or native.caption or ""
        return re.search(rf"(?i)(?<!\w)@{re.escape(username)}\b", content) is not None

    def _strip_mention(self, message: ObservedMessengerMessage) -> None:
        username = self.self_user.username
        if username and message.text:
            message.text = re.sub(
                rf"(?i)(?<!\w)@{re.escape(username)}\b[:,]?",
                "",
                message.text,
            ).strip()

    async def _process_batch(self, updates: Sequence[Update]) -> None:
        native_messages = [update.effective_message for update in updates]
        messages = [item for item in native_messages if item is not None]
        if not messages:
            return
        primary = next((item for item in messages if item.text or item.caption), messages[0])
        if not self._authorized(primary):
            return
        age = time.time() - primary.date.timestamp()
        max_age = runtime_settings.MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS
        if max_age and age > max_age:
            logger.info(
                "Telegram ignored stale update connection={} age={}s",
                self.connection_id,
                int(age),
            )
            return
        canonical = telegram_to_message(
            messages,
            self_user=self.self_user,
            tool_id=self.tool_id,
            connection_id=self.connection_id,
        )
        canonical.attachments = [
            item
            for item in canonical.attachments
            if item.size is None or item.size <= self._content_max_bytes
        ]
        self._strip_mention(canonical)
        if not canonical.text and not canonical.attachments:
            return
        await dispatch_incoming(canonical)

    @staticmethod
    def _group_updates(updates: Sequence[Update]) -> list[list[Update]]:
        """Group consecutive album updates without reordering cursor acknowledgements."""
        groups: list[list[Update]] = []
        for update in updates:
            message = update.effective_message
            media_group_id = message.media_group_id if message is not None else None
            previous = groups[-1][-1].effective_message if groups else None
            previous_group_id = (
                previous.media_group_id if previous is not None else None
            )
            if media_group_id and media_group_id == previous_group_id:
                groups[-1].append(update)
            else:
                groups.append([update])
        return groups

    async def _settle_album_updates(self, updates: Sequence[Update]) -> list[Update]:
        """Briefly collect album parts that Telegram delivers in adjacent poll responses."""
        collected = list(updates)
        if not any(
            update.effective_message is not None
            and update.effective_message.media_group_id
            for update in collected
        ):
            return collected
        seen = {update.update_id for update in collected}
        # Advancing past unprocessed updates acknowledges them on Telegram.
        # Re-read from the first pending update until the album has settled.
        pending_offset = min(seen)
        for _round in range(_ALBUM_SETTLE_ROUNDS):
            await asyncio.sleep(_ALBUM_SETTLE_SECONDS)
            following = await self.client.get_updates(offset=pending_offset, timeout=0)
            fresh = [update for update in following if update.update_id not in seen]
            if not fresh:
                break
            collected.extend(fresh)
            seen.update(update.update_id for update in fresh)
        return sorted(collected, key=lambda update: update.update_id)

    async def listen(self) -> None:
        cursor_raw = await journal.listener_cursor(self.connection_id)
        try:
            offset = int(cursor_raw) if cursor_raw else None
        except ValueError:
            offset = None
        await self.client.delete_webhook()
        backoff = 1.0
        logger.info("Telegram listener started connection={}", self.connection_id)
        try:
            while True:
                try:
                    updates = await self.client.get_updates(
                        offset=offset,
                        timeout=runtime_settings.MESSENGER_TELEGRAM_POLL_TIMEOUT_S,
                    )
                    backoff = 1.0
                    if not updates:
                        await journal.update_listener_state(
                            self.connection_id,
                            self.kind,
                            cursor=str(offset) if offset is not None else None,
                            available=True,
                        )
                        continue
                    updates = await self._settle_album_updates(updates)
                    for batch in self._group_updates(updates):
                        await self._process_batch(batch)
                        offset = max(update.update_id for update in batch) + 1
                        await journal.update_listener_state(
                            self.connection_id,
                            self.kind,
                            cursor=str(offset),
                            available=True,
                            event_received=True,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await journal.update_listener_state(
                        self.connection_id,
                        self.kind,
                        cursor=str(offset) if offset is not None else None,
                        available=False,
                        error=type(exc).__name__,
                        reconnect=True,
                    )
                    logger.warning(
                        "Telegram listener error connection={} retry_in={}s type={}",
                        self.connection_id,
                        backoff,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _SYNC_ERROR_BACKOFF_MAX)
        finally:
            await self.client.aclose()
