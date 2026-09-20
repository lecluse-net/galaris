"""Messaging backend interface and bridge-capability declaration.

Each concrete bridge implements ``Messenger`` and registers through
``app.messenger.facade.register_bridge``. The application only handles canonical messages and
remains independent of the underlying protocol. Core send/history methods are abstract; optional
operations raise ``NotSupported`` unless a bridge implements their declared capability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection, Generic, List, Literal, Optional, Set, TypeVar, Union

from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import Capability


class NotSupported(Exception):
    """Raised when a bridge does not support the requested operation."""


class DeliveryOutcomeUnknown(RuntimeError):
    """A send may have taken effect; do not retry without a provider receipt."""


HistoryItem = TypeVar("HistoryItem")


@dataclass(frozen=True)
class HistoryPage(Generic[HistoryItem]):
    """One room-history page and the opaque cursor for the next older batch."""

    messages: List[HistoryItem]
    has_more: bool
    next_cursor: str | None


@dataclass
class ParamDef:
    """Parameter expected by a bridge at tool or connection level."""

    name: str
    type: str = "string"        # "string" | "password" | "integer" | "boolean"
    required: bool = True
    default: str = ""
    description: str = ""


@dataclass
class BridgeSpec:
    """Bridge declaration: parameters, capabilities, and inbound modes."""

    kind: str
    label: str = ""
    tool_params: List[ParamDef] = field(default_factory=lambda: [])  # Shared configuration.
    connection_params: List[ParamDef] = field(default_factory=lambda: [])  # Per-agent credentials.
    capabilities: Set[Capability] = field(default_factory=lambda: set())
    inbound_modes: List[str] = field(default_factory=lambda: [])  # push|polling|signaling|sync
    availability: Literal["global", "tool"] = "global"
    inbound_admission: Literal["conversation", "task"] = "conversation"
    deliver_task_result: bool = True
    identity_param: str | None = "user_id"


class Messenger(ABC):
    """Unified internal interface implemented by every messaging backend."""

    tool_id: int = 0
    tool_code: str = ""
    kind: str = ""
    self_id: str = ""
    capabilities: Set[Capability] = set()
    # These flags certify an exhaustive snapshot for the exact persistence scope.
    # Keep them false for filtered, paginated or per-account subsets.
    rooms_snapshot_complete: bool = False
    users_snapshot_complete: bool = False
    provider_history: bool = True

    # Construction helpers.

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "Messenger":
        """Build an instance from a connection ID; concrete bridges override this method."""
        raise NotImplementedError(f"{cls.__name__}.from_connection_id is not implemented")

    # Capabilities

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def _require(self, capability: Capability) -> None:
        if capability not in self.capabilities:
            raise NotSupported(
                f"{self.kind or type(self).__name__}: capability '{capability.value}' is unsupported"
            )

    async def check_connection(self) -> str:
        """Perform a read-only provider check and return a short detail."""
        return self.self_id

    async def close(self) -> None:
        """Release client resources created for a short-lived operation."""
        return None

    # Sending (text is Markdown)

    @abstractmethod
    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        """Send a message to a room or group."""
        ...

    @abstractmethod
    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        """Send a private message to a user."""
        ...

    async def send(self, target: Union[ObservedMessengerRoom, ObservedMessengerUser], text: str) -> ObservedMessengerMessage:
        """Route a message to ``send_to_room`` or ``send_to_user`` by target type."""
        if isinstance(target, ObservedMessengerRoom):
            return await self.send_to_room(target.id, text)
        return await self.send_to_user(target.id, text)

    # Reading

    @abstractmethod
    async def history(self, room_id: str, limit: int = 20) -> List[ObservedMessengerMessage]:
        """Return canonical room messages in chronological order."""
        ...

    async def history_page(
        self,
        room_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[ObservedMessengerMessage]:
        """Return one history page.

        Bridges with a native or durable cursor override this method. The fallback preserves
        compatibility for integrations that can only expose their latest bounded batch.
        """
        if cursor:
            raise NotSupported(f"{self.kind}: paginated history")
        return HistoryPage(
            messages=await self.history(room_id, limit),
            has_more=False,
            next_cursor=None,
        )

    async def unread(self, room_id: str) -> List[ObservedMessengerMessage]:
        self._require(Capability.UNREAD)
        raise NotSupported(f"{self.kind}: unread")

    async def unread_counts(self, room_ids: Collection[str]) -> dict[str, int]:
        """Return provider unread counts for the requested room identifiers."""

        self._require(Capability.UNREAD)
        return {room_id: len(await self.unread(room_id)) for room_id in room_ids}

    async def mark_read(self, room_id: str, message_id: str | None = None) -> None:
        """Mark the provider room read through the last message actually displayed."""

        del message_id
        self._require(Capability.UNREAD)
        raise NotSupported(f"{self.kind}: mark_read")

    # Rooms and members

    async def rooms(self) -> List[ObservedMessengerRoom]:
        self._require(Capability.ROOMS)
        raise NotSupported(f"{self.kind}: rooms")

    async def room(self, room_id: str) -> Optional[ObservedMessengerRoom]:
        self._require(Capability.ROOMS)
        raise NotSupported(f"{self.kind}: room")

    async def ensure_direct_room(self, user_id: str) -> ObservedMessengerRoom:
        """Resolve or create the direct-message room for ``user_id``."""
        raise NotSupported(f"{self.kind}: ensure_direct_room")

    async def create_room(
        self, label: str, invitees: List[str], kind: str = "group"
    ) -> ObservedMessengerRoom:
        self._require(Capability.ROOMS)
        raise NotSupported(f"{self.kind}: create_room")

    async def add_user(self, room_id: str, user_id: str) -> None:
        self._require(Capability.MEMBERS)
        raise NotSupported(f"{self.kind}: add_user")

    async def remove_user(self, room_id: str, user_id: str) -> None:
        self._require(Capability.MEMBERS)
        raise NotSupported(f"{self.kind}: remove_user")

    # Users

    async def search_users(self, query: str) -> List[ObservedMessengerUser]:
        self._require(Capability.SEARCH_USERS)
        raise NotSupported(f"{self.kind}: search_users")

    # Outbound reactions

    async def react(self, message_id: str, emoji: str, room_id: Optional[str] = None) -> None:
        self._require(Capability.REACT)
        raise NotSupported(f"{self.kind}: react")

    async def unreact(self, message_id: str, emoji: str, room_id: Optional[str] = None) -> None:
        self._require(Capability.REACT)
        raise NotSupported(f"{self.kind}: unreact")

    # Attachments

    async def upload_file(
        self, room_id: str, path_or_bytes: Union[str, bytes], name: Optional[str] = None
    ) -> ObservedMessengerMessage:
        self._require(Capability.FILES)
        raise NotSupported(f"{self.kind}: upload_file")

    async def upload_file_path(
        self, room_id: str, path: Path, name: Optional[str] = None
    ) -> ObservedMessengerMessage:
        """Upload a local file to a room.

        The default implementation reads the file and delegates to ``upload_file``. Streaming
        bridges should override it to transfer large files without loading them entirely in RAM.
        """
        return await self.upload_file(room_id, str(path), name or path.name)

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        """Download attachment content on demand."""
        self._require(Capability.FILES)
        raise NotSupported(f"{self.kind}: fetch_attachment")

    async def fetch_attachment_to_file(self, attachment: ObservedMessengerFile, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        """Download an attachment to ``dest`` and return its byte count.

        The default implementation fetches all bytes before writing. Streaming bridges should
        override it for large files.
        """
        data = await self.fetch_attachment(attachment)
        if len(data) > max_bytes:
            raise ValueError("Messenger attachment exceeds the requested byte limit")
        dest.write_bytes(data)
        return len(data)

    async def send_voice_note(
        self,
        room_id: str,
        path: Path,
        *,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        """Send a native asynchronous voice note when the bridge supports it."""
        self._require(Capability.VOICE_NOTES)
        raise NotSupported(f"{self.kind}: send_voice_note")

    # Presence

    async def typing(self, target: Union[ObservedMessengerRoom, ObservedMessengerUser], on: bool = True) -> None:
        self._require(Capability.TYPING)
        raise NotSupported(f"{self.kind}: typing")

    # Inbound reception for pull-based bridges

    async def listen(self) -> None:
        """Receive messages for pull-based bridges such as Matrix sync or Talk polling.

        Each message must be converted to ``ObservedMessengerMessage`` and dispatched through
        ``app.messenger.inbound.dispatch_incoming``. Push-based bridges keep this as a no-op.
        """
        return None
