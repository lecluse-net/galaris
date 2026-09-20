"""WhatsApp Business Cloud implementation of the canonical Messenger contract."""

from __future__ import annotations

import asyncio
import mimetypes
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from core.util import read_buffered_file, buffered_io_budget
from typing import Any, Optional

from app.messenger import journal
from app.messenger.interface import HistoryPage, Messenger, NotSupported
from app.messenger.media import normalized_voice_note
from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import Capability, kind_from_mime
from core.params import runtime_settings
from core.util import as_dict, as_list

from .client import WhatsAppClient
from .schemas import WhatsAppConnectionConfig, normalize_phone

_KIND = "whatsapp"
_CAPABILITIES = {
    Capability.SEND,
    Capability.HISTORY,
    Capability.FILES,
    Capability.VOICE_NOTES,
}
_SERVICE_WINDOW = timedelta(hours=24)
_MAX_TEXT = 4_096
_WHATSAPP_CONTENT_MAX_BYTES = 100_000_000


class WhatsAppServiceWindowError(NotSupported):
    """Raised when a free-form message cannot legally be initiated."""


def _chunks(text: str) -> list[str]:
    if len(text) <= _MAX_TEXT:
        return [text]
    result: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= _MAX_TEXT:
            result.append(remaining)
            break
        cut = max(
            remaining.rfind("\n", 0, _MAX_TEXT + 1),
            remaining.rfind(" ", 0, _MAX_TEXT + 1),
        )
        if cut < _MAX_TEXT // 2:
            cut = _MAX_TEXT
        result.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [item for item in result if item]


def _response_id(payload: dict[str, Any]) -> tuple[str, str]:
    messages = as_list(payload.get("messages"))
    first = as_dict(messages[0]) if messages else {}
    remote_id = str(first.get("id") or "")
    status = str(first.get("message_status") or "accepted")
    if not remote_id:
        raise RuntimeError("WhatsApp accepted a request without returning a message ID")
    return remote_id, status


def whatsapp_to_message(
    raw: dict[str, Any],
    *,
    contacts: dict[str, str],
    phone_number_id: str,
    tool_id: int,
    connection_id: int,
) -> ObservedMessengerMessage | None:
    """Map one supported Meta webhook message to the canonical model."""
    remote_id = str(raw.get("id") or "")
    sender_id = normalize_phone(str(raw.get("from") or ""))
    message_type = str(raw.get("type") or "")
    if not remote_id or not sender_id:
        return None
    text = ""
    attachments: list[ObservedMessengerFile] = []
    if message_type == "text":
        text = str(as_dict(raw.get("text")).get("body") or "")
    elif message_type in {"image", "document", "audio", "video"}:
        media = as_dict(raw.get(message_type))
        media_id = str(media.get("id") or "")
        if not media_id:
            return None
        mime = str(media.get("mime_type") or "application/octet-stream")
        suffix = mimetypes.guess_extension(mime) or ""
        name = str(media.get("filename") or f"{message_type}-{media_id[:12]}{suffix}")
        text = str(media.get("caption") or "")
        attachments.append(
            ObservedMessengerFile(
                id=media_id,
                name=name,
                mime=mime,
                kind=kind_from_mime(mime),
            )
        )
    else:
        return None
    context = as_dict(raw.get("context"))
    try:
        timestamp = int(raw.get("timestamp") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    return ObservedMessengerMessage(
        id=remote_id,
        platform=_KIND,
        tool_id=tool_id,
        sender=ObservedMessengerUser(
            id=sender_id,
            display_name=contacts.get(sender_id, ""),
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        recipient=ObservedMessengerUser(
            id=phone_number_id,
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        room=ObservedMessengerRoom(
            id=sender_id,
            kind="direct",
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        text=text,
        attachments=attachments,
        reply_to=str(context.get("id") or "") or None,
        time=timestamp,
    )


class WhatsAppMessenger(Messenger):
    kind = _KIND
    capabilities = _CAPABILITIES
    provider_history = False

    def __init__(
        self,
        client: WhatsAppClient,
        config: WhatsAppConnectionConfig,
        *,
        tool_id: int,
        connection_id: int,
    ) -> None:
        self.client = client
        self.config = config
        self.tool_id = tool_id
        self.connection_id = connection_id
        self.self_id = config.phone_number_id

    @property
    def _content_max_bytes(self) -> int:
        return min(
            runtime_settings.messenger_content_max_bytes,
            _WHATSAPP_CONTENT_MAX_BYTES,
        )

    @classmethod
    async def from_connection_id(
        cls, connection_id: int, *, validate: bool = True
    ) -> "WhatsAppMessenger":
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            connection_id,
            expected_service="whatsapp",
        )
        params = resolved.params
        config = WhatsAppConnectionConfig.model_validate(params)
        client = WhatsAppClient(
            access_token=config.access_token,
            phone_number_id=config.phone_number_id,
            graph_url=runtime_settings.MESSENGER_WHATSAPP_GRAPH_URL,
            graph_version=runtime_settings.MESSENGER_WHATSAPP_GRAPH_VERSION,
            timeout=runtime_settings.MESSENGER_WHATSAPP_HTTP_TIMEOUT_S,
        )
        if validate:
            try:
                await client.validate()
            except Exception:
                await client.aclose()
                raise
        return cls(
            client,
            config,
            tool_id=resolved.tool_id,
            connection_id=connection_id,
        )

    async def check_connection(self) -> str:
        return self.self_id

    async def close(self) -> None:
        await self.client.aclose()

    def is_allowed(self, phone: str) -> bool:
        normalized = normalize_phone(phone)
        return bool(normalized and normalized in self.config.allowed_phones)

    def _require_allowed(self, phone: str) -> str:
        normalized = normalize_phone(phone)
        if not self.is_allowed(normalized):
            raise ValueError("WhatsApp target is not present in allowed_phone_numbers")
        return normalized

    async def _inside_service_window(self, user_id: str) -> bool:
        latest = await journal.latest_inbound_at(self.connection_id, user_id)
        if latest is None:
            return False
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - latest <= _SERVICE_WINDOW

    def _outbound(
        self,
        remote_id: str,
        room_id: str,
        text: str,
        *,
        reply_to: str | None = None,
        attachment: ObservedMessengerFile | None = None,
    ) -> ObservedMessengerMessage:
        return ObservedMessengerMessage(
            id=remote_id,
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            recipient=ObservedMessengerUser(
                id=room_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=room_id,
                kind="direct",
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
            attachments=[attachment] if attachment is not None else [],
            reply_to=reply_to,
            time=int(time.time()),
        )

    async def _record(self, message: ObservedMessengerMessage, status: str) -> None:
        await journal.persist_outbound(
            message,
            connection_id=self.connection_id,
            platform=self.kind,
            status=status,
        )

    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        recipient = self._require_allowed(room_id)
        if not await self._inside_service_window(recipient):
            if not self.config.template_name:
                raise WhatsAppServiceWindowError(
                    "WhatsApp free-form messages require a user message in the last 24 hours; "
                    "configure an approved template_name for proactive messaging."
                )
            payload = await self.client.send_template(
                recipient,
                name=self.config.template_name,
                language=self.config.template_language,
                text_parameter=text,
            )
            remote_id, status = _response_id(payload)
            result = self._outbound(remote_id, recipient, text)
            await self._record(result, status)
            return result

        result: ObservedMessengerMessage | None = None
        for index, part in enumerate(_chunks(text)):
            payload = await self.client.send_text(
                recipient,
                part,
                reply_to=reply_to if index == 0 else None,
            )
            remote_id, status = _response_id(payload)
            result = self._outbound(
                remote_id,
                recipient,
                part,
                reply_to=reply_to if index == 0 else None,
            )
            await self._record(result, status)
        if result is None:
            raise ValueError("WhatsApp cannot send an empty text message")
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
        recipient = self._require_allowed(user_id)
        return ObservedMessengerRoom(
            id=recipient,
            kind="direct",
            connection_id=self.connection_id,
            tool_id=self.tool_id,
        )

    async def _require_media_window(self, recipient: str) -> None:
        if not await self._inside_service_window(recipient):
            raise WhatsAppServiceWindowError(
                "WhatsApp media can only be sent in the 24-hour customer service window; "
                "use an approved media template for proactive delivery."
            )

    async def upload_file(
        self,
        room_id: str,
        path_or_bytes: str | bytes,
        name: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        size = Path(path_or_bytes).stat().st_size if isinstance(path_or_bytes, str) else len(path_or_bytes)
        async with buffered_io_budget.reserve(max(1, size * 3), owner=f"whatsapp:{self.connection_id}:{room_id}"):
            return await self._upload_file(room_id, path_or_bytes, name, max_bytes=min(size, self._content_max_bytes))

    async def _upload_file(
        self,
        room_id: str,
        path_or_bytes: str | bytes,
        name: Optional[str] = None,
        *, max_bytes: int | None = None,
    ) -> ObservedMessengerMessage:
        recipient = self._require_allowed(room_id)
        await self._require_media_window(recipient)
        if isinstance(path_or_bytes, str):
            source = Path(path_or_bytes)
            if source.stat().st_size > self._content_max_bytes:
                raise ValueError("WhatsApp media exceeds the configured size limit")
            content = await read_buffered_file(source, max_bytes=self._content_max_bytes if max_bytes is None else max_bytes)
        else:
            content = path_or_bytes
        if len(content) > self._content_max_bytes:
            raise ValueError("WhatsApp media exceeds the configured size limit")
        filename = name or (Path(path_or_bytes).name if isinstance(path_or_bytes, str) else "file")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        inferred = kind_from_mime(mime)
        kind = inferred if inferred in {"image", "audio", "video"} else "document"
        media_id = await self.client.upload_media(content, filename, mime)
        payload = await self.client.send_media(
            recipient,
            kind=kind,
            media_id=media_id,
            name=filename,
        )
        remote_id, status = _response_id(payload)
        attachment = ObservedMessengerFile(
            id=media_id,
            name=filename,
            mime=mime,
            size=len(content),
            kind=inferred,
        )
        result = self._outbound(remote_id, recipient, "", attachment=attachment)
        await self._record(result, status)
        return result

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        content, _mime = await self.client.download_media(
            attachment.id,
            max_bytes=self._content_max_bytes,
        )
        return content

    async def fetch_attachment_to_file(self, attachment: ObservedMessengerFile, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        return await self.client.download_media_to_file(attachment.id, dest, max_bytes=min(max_bytes, self._content_max_bytes))

    async def send_voice_note(
        self,
        room_id: str,
        path: Path,
        *,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        recipient = self._require_allowed(room_id)
        await self._require_media_window(recipient)
        async with normalized_voice_note(
            path,
            max_input_bytes=self._content_max_bytes,
            max_output_bytes=self._content_max_bytes,
            max_duration_seconds=runtime_settings.messenger_voice_max_duration_seconds,
        ) as normalized:
            media_id = await self.client.upload_media(
                await asyncio.to_thread(normalized.read_bytes), normalized.name, "audio/ogg"
            )
            payload = await self.client.send_media(
                recipient,
                kind="audio",
                media_id=media_id,
                reply_to=reply_to,
                voice=True,
            )
            remote_id, status = _response_id(payload)
            attachment = ObservedMessengerFile(
                id=media_id,
                name=normalized.name,
                mime="audio/ogg",
                size=normalized.stat().st_size,
                kind="audio",
            )
            result = self._outbound(
                remote_id,
                recipient,
                caption or "",
                reply_to=reply_to,
                attachment=attachment,
            )
            await self._record(result, status)
            return result
