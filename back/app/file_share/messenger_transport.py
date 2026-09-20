"""Messaging ``FileTransport`` adapter.

Uploads attach a local file to a room or direct-message user. Downloads locate a recent room
attachment by identifier or name. Both operations delegate to streaming messenger methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from core.util import DEFAULT_DOWNLOAD_BYTES
from typing import Any
from uuid import UUID
import hashlib

from core.i18n import render_prompt, t
from .resource_uri import parse_resource_uri

# Number of recent messages searched for an attachment identifier or name.
_HISTORY_LOOKBACK = 30


@dataclass(frozen=True, slots=True)
class MessengerAttachmentResource:
    """One attachment paired with its provider-native room locator."""

    room_locator: str
    attachment: Any


class MessengerFileTransport:
    """Adapt a ``Messenger`` to the standard ``FileTransport`` interface."""

    def __init__(self, messenger: Any, *, language: str | None = None,
                 task_id: UUID | None = None, tool_code: str = "") -> None:
        self._messenger = messenger
        self._language = language
        self._task_id = task_id
        self._tool_code = tool_code

    def for_task(self, task_id: UUID | None, tool_code: str) -> MessengerFileTransport:
        """Bind operation context without mutating a reusable transport."""
        return MessengerFileTransport(self._messenger, language=self._language,
                                      task_id=task_id, tool_code=tool_code)

    def _message(self, key: str, **values: Any) -> str:
        return render_prompt(
            t(f"file_share.errors.{key}", self._language), **values
        )

    async def _resolve_room(self, target: str) -> str:
        """Resolve a room target; ``u:`` prefixes identify direct-message users."""
        ref = (target or "").strip()
        if not ref:
            raise ValueError(self._message("messaging_target_required"))
        if ref.startswith("u:"):
            room = await self._messenger.ensure_direct_room(ref[2:])
            return str(room.id)
        return ref

    async def _find_attachment(self, room_id: str, ref: str) -> Any:
        """Find an attachment by identifier or name in recent room history."""
        if not room_id:
            raise ValueError(self._message("room_required"))
        seen: dict[str, Any] = {}
        for message in await self._messenger.history(room_id, _HISTORY_LOOKBACK):
            for att in message.files:
                key = str(att.id)
                if key and key not in seen:
                    seen[key] = att
        att = seen.get(ref) or next(
            (a for a in seen.values() if ref in (str(a.id), a.name)), None
        )
        if att is None:
            raise ValueError(self._message(
                "attachment_not_found", attachment=ref, room_id=room_id
            ))
        return att

    async def describe_attachment_resource(
        self, room_id: str, ref: str
    ) -> MessengerAttachmentResource:
        """Resolve one attachment together with the room UUID used in its URI."""

        for message in await self._messenger.history(room_id, _HISTORY_LOOKBACK):
            for attachment in message.files:
                if ref not in (str(attachment.id), attachment.name):
                    continue
                if message.room is None:
                    raise RuntimeError(
                        f"Messenger attachment {attachment.id} has no canonical room."
                    )
                return MessengerAttachmentResource(
                    room_locator=str(message.room.external_id),
                    attachment=attachment,
                )
        raise ValueError(self._message(
            "attachment_not_found", attachment=ref, room_id=room_id
        ))

    async def list_attachments(self, room_id: str, *, limit: int = 100) -> list[Any]:
        """Return distinct recent canonical attachments in message order."""

        if not room_id:
            raise ValueError(self._message("room_required"))
        seen: set[str] = set()
        result: list[Any] = []
        history_limit = max(_HISTORY_LOOKBACK, min(limit, 500))
        for message in await self._messenger.history(room_id, history_limit):
            for attachment in message.files:
                key = str(attachment.id)
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(attachment)
                if len(result) >= limit:
                    return result
        return result

    async def list_attachment_resources(
        self, room_id: str, *, limit: int = 100
    ) -> list[MessengerAttachmentResource]:
        """Return distinct attachments with stable local room references."""

        seen: set[str] = set()
        result: list[MessengerAttachmentResource] = []
        history_limit = max(_HISTORY_LOOKBACK, min(limit, 500))
        for message in await self._messenger.history(room_id, history_limit):
            room = message.room
            if not message.files:
                continue
            if room is None:
                raise RuntimeError("A Messenger attachment has no canonical room.")
            for attachment in message.files:
                key = str(attachment.id)
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(
                    MessengerAttachmentResource(
                        room_locator=str(room.external_id),
                        attachment=attachment,
                    )
                )
                if len(result) >= limit:
                    return result
        return result

    async def describe_attachment(self, room_id: str, ref: str) -> Any:
        """Resolve one canonical attachment for metadata presentation."""

        return await self._find_attachment(room_id, ref)

    # Standard FileTransport interface.

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        """Download attachment ``remote`` from room ``target`` to local ``dest``."""
        att = await self._find_attachment(target, remote)
        return await self._messenger.fetch_attachment_to_file(att, dest, max_bytes=max_bytes)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Attach local ``src`` to a room or ``u:<user_id>`` target."""
        room_id = await self._resolve_room(target)
        message = await self._messenger.upload_file_path(room_id, src, filename)
        attachment = next(
            (item for item in message.files if item.name == filename),
            message.files[0] if message.files else None,
        )
        identifier = str(attachment.id) if attachment is not None else filename
        room_locator = (
            str(message.room.external_id) if message.room is not None else room_id
        )
        if self._task_id is not None and attachment is not None and message.room is not None:
            from app.agent.contracts import WorkingResource
            from app.task import upsert_working_resource

            uri = str(parse_resource_uri(f"{self._tool_code}://{room_locator}/{identifier}"))
            identity = hashlib.sha256(uri.encode()).hexdigest()[:24]
            await upsert_working_resource(self._task_id, WorkingResource(
                resource_type="delivery_receipt", role=f"delivery_receipt:upload:{identity}",
                reference=uri, label=filename, producer_task_id=self._task_id,
                metadata={"tool": "messenger_resource_upload", "uri": uri,
                          "destination": str(message.room.id),
                          "connection_id": message.room.connection_id,
                          "message_id": str(message.id), "delivered": True},
            ))
        return f"{room_locator}/{identifier}"
