"""Native Messenger provider backed entirely by the canonical journal."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Union
from uuid import uuid4

from fastapi import UploadFile

from app.messenger import (
    BridgeSpec,
    Capability,
    kind_from_mime,
    internal_connection,
    internal_direct_room_observation,
    internal_history_observations,
    internal_outbound_observation,
    register_bridge,
    search_internal_users,
)
from app.messenger.interface import (
    Messenger,
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from . import storage


class InternalMessenger(Messenger):
    """Provider implementation used by one agent's auto-created connection."""

    kind = "internal"
    capabilities = {
        Capability.SEND,
        Capability.HISTORY,
        Capability.FILES,
        Capability.SEARCH_USERS,
        Capability.VOICE_NOTES,
    }
    provider_history = False

    def __init__(
        self,
        *,
        connection_id: int,
        tool_id: int,
        tool_code: str,
        agent_id: int,
        self_id: str,
    ) -> None:
        self.connection_id = connection_id
        self.tool_id = tool_id
        self.tool_code = tool_code
        self.agent_id = agent_id
        self.self_id = self_id

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "InternalMessenger":
        scope = await internal_connection(connection_id)
        if scope is None or not scope.active:
            raise LookupError("The Chat connection is unavailable.")
        return cls(
            connection_id=scope.connection_id,
            tool_id=scope.tool_id,
            tool_code=scope.tool_code,
            agent_id=scope.agent_id,
            self_id=f"agent:{scope.agent_id}",
        )

    async def send_to_room(
        self, room_id: str, text: str, reply_to: str | None = None
    ) -> ObservedMessengerMessage:
        return await internal_outbound_observation(
            self.connection_id, room_id, text, reply_to=reply_to
        )

    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        room = await self.ensure_direct_room(user_id)
        return await self.send_to_room(room.id, text)

    async def search_users(self, query: str) -> list[ObservedMessengerUser]:
        return await search_internal_users(self.connection_id, query)

    async def ensure_direct_room(self, user_id: str) -> ObservedMessengerRoom:
        room = await internal_direct_room_observation(self.connection_id, user_id)
        if room is None:
            raise LookupError("No direct Chat room exists for this human contact.")
        return room

    async def history(self, room_id: str, limit: int = 20) -> list[ObservedMessengerMessage]:
        return await internal_history_observations(self.connection_id, room_id, limit)

    async def upload_file_path(
        self, room_id: str, path: Path, name: str | None = None
    ) -> ObservedMessengerMessage:
        file_id = uuid4()
        upload_name = (name or path.name)[:512]
        _stored, size, mime_type = await storage.store_path(
            path,
            file_id,
            filename=upload_name,
        )
        try:
            return await internal_outbound_observation(
                self.connection_id,
                room_id,
                "",
                attachments=[
                    ObservedMessengerFile(
                        id=str(file_id),
                        local_id=file_id,
                        name=upload_name,
                        mime=mime_type,
                        size=size,
                        kind=kind_from_mime(mime_type),
                    )
                ],
            )
        except BaseException:
            await storage.discard(file_id)
            raise

    async def upload_file(
        self,
        room_id: str,
        path_or_bytes: Union[str, bytes],
        name: str | None = None,
    ) -> ObservedMessengerMessage:
        if isinstance(path_or_bytes, str):
            return await self.upload_file_path(
                room_id,
                Path(path_or_bytes),
                name=name,
            )
        file_id = uuid4()
        upload_name = (name or str(file_id))[:512]
        upload = UploadFile(filename=upload_name, file=BytesIO(path_or_bytes))
        _stored, size, mime_type = await storage.store_upload(upload, file_id)
        try:
            return await internal_outbound_observation(
                self.connection_id,
                room_id,
                "",
                attachments=[
                    ObservedMessengerFile(
                        id=str(file_id),
                        local_id=file_id,
                        name=upload_name,
                        mime=mime_type,
                        size=size,
                        kind=kind_from_mime(mime_type),
                    )
                ],
            )
        except BaseException:
            await storage.discard(file_id)
            raise

    async def send_voice_note(
        self,
        room_id: str,
        path: Path,
        *,
        caption: str | None = None,
        reply_to: str | None = None,
    ) -> ObservedMessengerMessage:
        file_id = uuid4()
        _stored, size, mime_type = await storage.store_path(path, file_id)
        if not mime_type.startswith("audio/"):
            await storage.discard(file_id)
            raise ValueError("A native voice note must use a recognized audio format.")
        try:
            return await internal_outbound_observation(
                self.connection_id,
                room_id,
                caption or "",
                reply_to=reply_to,
                attachments=[
                    ObservedMessengerFile(
                        id=str(file_id),
                        local_id=file_id,
                        name=path.name[:512],
                        mime=mime_type,
                        size=size,
                        kind="audio",
                    )
                ],
            )
        except BaseException:
            await storage.discard(file_id)
            raise

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        if attachment.local_id is None:
            raise LookupError("The native attachment has no local identifier.")
        return await storage.read_bytes(attachment.local_id)

    async def fetch_attachment_to_file(
        self, attachment: ObservedMessengerFile, dest: Path, *, max_bytes: int = 512 * 1024 * 1024,
    ) -> int:
        if attachment.local_id is None:
            raise LookupError("The native attachment has no local identifier.")
        return await storage.copy_to(attachment.local_id, dest, max_bytes=max_bytes)


register_bridge(
    "internal",
    InternalMessenger,
    BridgeSpec(
        kind="internal",
        label="Chat",
        capabilities=set(InternalMessenger.capabilities),
        availability="global",
        inbound_admission="conversation",
        deliver_task_result=False,
    ),
)


__all__ = ["InternalMessenger"]
