"""Messaging facade and bridge registry, the application's unified entry point.

Each bridge registers its factory and specification. Application services inject a resolver that
maps connection/tool data to the correct bridge without coupling this facade to those models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Dict, List, Mapping, Optional, Protocol, Type, Union, cast
from uuid import UUID

from loguru import logger

from app.messenger.interface import BridgeSpec, HistoryPage, Messenger
from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import (
    Capability,
    File,
    Message,
    Room,
    MessengerUser,
)


# Bridge registry: kind to factory and specification.

_factories: Dict[str, Type[Messenger]] = {}
_specs: Dict[str, BridgeSpec] = {}

_KIND_ALIASES = {
    "nextcloud": "nextcloud_talk",
    "talk": "nextcloud_talk",
    "wa": "whatsapp",
    "onebot": "one_bot",
}


def normalize_kind(value: str | None) -> str | None:
    """Normalize user-facing channel names without introducing identity state."""

    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.startswith("messenger."):
        normalized = normalized.removeprefix("messenger.")
    if not normalized:
        return None
    return _KIND_ALIASES.get(normalized, normalized)


def register_bridge(kind: str, factory: Type[Messenger], spec: BridgeSpec) -> None:
    """Register a bridge kind, replacing an existing registration idempotently."""
    _factories[kind] = factory
    _specs[kind] = spec


def get_factory(kind: str) -> Optional[Type[Messenger]]:
    return _factories.get(kind)


def get_spec(kind: str) -> Optional[BridgeSpec]:
    return _specs.get(kind)


def all_specs() -> List[BridgeSpec]:
    """Return available bridge specifications for configuration interfaces."""
    return list(_specs.values())


def available_bridges() -> list[dict[str, object]]:
    """Return bridge metadata for dynamic Tool configuration forms."""

    def param_info(param: Any) -> dict[str, object]:
        return {
            "key": param.name,
            "label": param.name.replace("_", " ").title(),
            "type": param.type,
            "required": param.required,
            "default": param.default,
            "description": param.description,
        }

    return [
        {
            "service": spec.kind,
            "label": spec.label or spec.kind.replace("_", " ").title(),
            "settings": [param_info(param) for param in spec.tool_params],
            "params": [param_info(param) for param in spec.connection_params],
        }
        for spec in _specs.values()
    ]


def registered_kinds() -> List[str]:
    return list(_factories.keys())


def enabled_kinds() -> List[str]:
    """Return registered bridges made globally available by administrators."""

    from core.params import runtime_settings

    try:
        raw: object = json.loads(runtime_settings.MESSENGER_ENABLED_CHANNELS)
    except (TypeError, ValueError):
        raw = []
    items = cast(list[object], raw) if isinstance(raw, list) else []
    configured = {str(item) for item in items if isinstance(item, str)}
    return [kind for kind in _factories if kind in configured]


def is_kind_enabled(kind: str) -> bool:
    """Return whether one registered bridge is globally available at runtime."""

    spec = get_spec(kind)
    return bool(
        spec is not None
        and (spec.availability == "tool" or kind in enabled_kinds())
    )


def enabled_specs() -> List[BridgeSpec]:
    """Return bridge specifications visible to runtime discovery."""

    enabled = set(enabled_kinds())
    return [
        spec
        for spec in _specs.values()
        if spec.availability == "tool" or spec.kind in enabled
    ]


def kind_for_tool(
    tool: Any,
    *,
    preferred_kind: str | None = None,
) -> Optional[str]:
    """Resolve the bridge explicitly selected by a Tool's Messenger configuration."""

    del preferred_kind
    messenger = getattr(tool, "messenger", None)
    service = getattr(messenger, "service", None)
    if not service:
        raw = getattr(tool, "messenger_config", None)
        if isinstance(raw, dict):
            mapping = cast(Mapping[str, Any], raw)
            raw_service = mapping.get("service")
            service = str(raw_service) if raw_service is not None else ""
    normalized = normalize_kind(str(service)) if service else None
    if normalized in _factories:
        return normalized
    return None


# Application resolver injected at startup.


class MessengerResolver(Protocol):
    """Resolve application connection or tool data to a registered messenger."""

    async def messenger_for_connection(self, connection_id: int) -> Messenger: ...

    async def messenger_for(self, tool_id: int, self_id: str) -> Messenger: ...

    async def default_messenger(self) -> Messenger: ...


_resolver: Optional[MessengerResolver] = None


def set_resolver(resolver: MessengerResolver) -> None:
    """Inject the application resolver during startup."""
    global _resolver
    _resolver = resolver


def _require_resolver() -> MessengerResolver:
    if _resolver is None:
        raise RuntimeError(
            "No MessengerResolver is registered; call app.messenger.set_resolver(...) "
            "during application startup."
        )
    return _resolver


# Resolution API.


async def get_messenger(connection_id: int) -> MessengerFacade:
    """Return the messenger associated with an agent connection."""
    resolved = await _require_resolver().messenger_for_connection(connection_id)
    if isinstance(resolved, MessengerFacade):
        return resolved
    return MessengerFacade(resolved, connection_id)


async def get_messenger_for(tool_id: int, self_id: str) -> MessengerFacade:
    """Return the messenger for a tool and bot identity."""
    resolved = await _require_resolver().messenger_for(tool_id, self_id)
    connection_id = getattr(resolved, "connection_id", None)
    if not isinstance(connection_id, int):
        raise RuntimeError("The resolved Messenger has no canonical connection scope.")
    return MessengerFacade(resolved, connection_id)


async def get_default_messenger() -> MessengerFacade:
    """Return the reserved default messaging tool's messenger."""
    resolved = await _require_resolver().default_messenger()
    connection_id = getattr(resolved, "connection_id", None)
    if not isinstance(connection_id, int):
        raise RuntimeError("The default Messenger has no canonical connection scope.")
    return MessengerFacade(resolved, connection_id)


class MessengerFacade:
    """Transparent outbound decorator feeding the canonical session journal."""

    def __init__(self, delegate: Messenger, connection_id: int) -> None:
        self._delegate = delegate
        self._connection_id = connection_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    @property
    def connection_id(self) -> int:
        return self._connection_id

    @property
    def tool_id(self) -> int:
        return self._delegate.tool_id

    @property
    def tool_code(self) -> str:
        return self._delegate.tool_code

    @property
    def kind(self) -> str:
        return self._delegate.kind

    @property
    def self_id(self) -> str:
        return self._delegate.self_id

    def supports(self, capability: Capability) -> bool:
        return self._delegate.supports(capability)

    async def check_connection(self) -> str:
        return await self._delegate.check_connection()

    async def close(self) -> None:
        await self._delegate.close()

    async def _external_room_id(self, room_id: UUID | str) -> str:
        from sqlalchemy import select

        from core.database import get_db

        try:
            local_id = room_id if isinstance(room_id, UUID) else UUID(room_id)
        except ValueError:
            return str(room_id)
        external_id = await get_db().scalar(
            select(Room.external_id).where(
                Room.id == local_id,
                Room.connection_id == self._connection_id,
            )
        )
        if external_id is None:
            raise ValueError(f"Messenger room {local_id} is unknown for this connection.")
        return external_id

    async def _external_user_id(self, user_id: UUID | str) -> str:
        from sqlalchemy import select

        from core.database import get_db

        try:
            local_id = user_id if isinstance(user_id, UUID) else UUID(user_id)
        except ValueError:
            return str(user_id)
        external_id = await get_db().scalar(
            select(MessengerUser.external_id).where(
                MessengerUser.id == local_id,
                MessengerUser.tool_id == self._delegate.tool_id,
            )
        )
        if external_id is None:
            raise ValueError(f"Messenger user {local_id} is unknown for this tool.")
        return external_id

    async def _record(
        self,
        message: ObservedMessengerMessage,
        *,
        room_id: str | None = None,
        user_id: str | None = None,
        publish_event: bool = True,
        journal_metadata: dict[str, Any] | None = None,
    ) -> Message:
        from app.messenger import journal
        from app.messenger.events import message_sent

        canonical = message.model_copy(deep=True)
        canonical.platform = canonical.platform or self._delegate.kind or "messenger"
        canonical.tool_id = canonical.tool_id or self._delegate.tool_id
        if room_id and canonical.room is None:
            canonical.room = ObservedMessengerRoom(
                id=room_id,
                kind="direct" if user_id else "group",
                connection_id=self._connection_id,
                tool_id=canonical.tool_id or self._delegate.tool_id,
            )
        elif canonical.room is not None and canonical.room.connection_id is None:
            canonical.room.connection_id = self._connection_id
        if user_id and canonical.recipient is None:
            canonical.recipient = ObservedMessengerUser(
                id=user_id,
                connection_id=self._connection_id,
                tool_id=canonical.tool_id or self._delegate.tool_id,
            )
        try:
            await journal.persist_outbound(
                canonical,
                connection_id=self._connection_id,
                platform=canonical.platform,
                metadata=journal_metadata,
            )
            stored = await journal.stored_message(
                connection_id=self._connection_id,
                remote_message_id=canonical.id,
                direction="outbound",
            )
            if stored is None:
                raise RuntimeError("The outbound message was not found after persistence.")
            if publish_event:
                await message_sent.send_async(stored)
            return stored
        except Exception:
            logger.exception(
                "Could not journal outbound message connection={} message={}",
                self._connection_id,
                canonical.id,
            )
            raise RuntimeError(
                "The provider accepted the message but Galaris could not persist it."
            ) from None

    async def history(
        self, room_id: UUID | str, limit: int = 20
    ) -> list[Message]:
        from app.messenger import journal

        external_room_id = await self._external_room_id(room_id)
        if not self._delegate.provider_history:
            return await journal.history(
                self._connection_id, external_room_id, limit
            )
        remote = await self._delegate.history(external_room_id, limit)
        return await journal.synchronize_messages(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            self_id=self._delegate.self_id,
            messages=remote,
            counts_as_unread=False,
        )

    async def history_page(
        self,
        room_id: UUID | str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[Message]:
        from app.messenger import journal

        external_room_id = await self._external_room_id(room_id)
        if not self._delegate.provider_history:
            return await journal.history_page(
                self._connection_id,
                external_room_id,
                limit=limit,
                cursor=cursor,
            )
        remote = await self._delegate.history_page(external_room_id, limit, cursor)
        messages = await journal.synchronize_messages(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            self_id=self._delegate.self_id,
            messages=remote.messages,
            counts_as_unread=False,
        )
        return HistoryPage(
            messages=messages,
            has_more=remote.has_more,
            next_cursor=remote.next_cursor,
        )

    async def unread(self, room_id: UUID | str) -> list[Message]:
        """Import unread provider messages and return local reconstructions only."""
        from app.messenger import journal

        remote = await self._delegate.unread(await self._external_room_id(room_id))
        return await journal.synchronize_messages(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            self_id=self._delegate.self_id,
            messages=remote,
            counts_as_unread=True,
        )

    async def unread_counts(
        self,
        room_ids: Collection[UUID | str],
    ) -> dict[str, int]:
        """Return provider counts keyed by the caller's canonical room identifiers."""

        room_pairs = [
            (str(room_id), await self._external_room_id(room_id))
            for room_id in room_ids
        ]
        provider_counts = await self._delegate.unread_counts(
            {external_id for _room_id, external_id in room_pairs}
        )
        return {
            room_id: max(0, provider_counts[external_id])
            for room_id, external_id in room_pairs
            if external_id in provider_counts
        }

    async def mark_read(
        self,
        room_id: UUID | str,
        message_id: str | None = None,
    ) -> None:
        await self._delegate.mark_read(
            await self._external_room_id(room_id),
            message_id,
        )

    async def rooms(self) -> list[Room]:
        from app.messenger.room_service import synchronize_rooms

        remote = await self._delegate.rooms()
        return await synchronize_rooms(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            rooms=remote,
            authoritative=bool(
                getattr(self._delegate, "rooms_snapshot_complete", False)
            ),
        )

    async def room(self, room_id: UUID | str) -> Room | None:
        from app.messenger.room_service import synchronize_rooms

        remote = await self._delegate.room(await self._external_room_id(room_id))
        if remote is None:
            return None
        rooms = await synchronize_rooms(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            rooms=[remote],
        )
        return rooms[0] if rooms else None

    async def search_users(self, query: str) -> list[MessengerUser]:
        from app.messenger.user_service import synchronize_users

        remote = await self._delegate.search_users(query)
        authoritative = (
            not query.strip()
            and bool(getattr(self._delegate, "users_snapshot_complete", False))
        )
        if authoritative and self._delegate.self_id:
            remote.append(
                ObservedMessengerUser(
                    id=self._delegate.self_id,
                    connection_id=self._connection_id,
                    tool_id=self._delegate.tool_id,
                )
            )
        users = await synchronize_users(
            tool_id=self._delegate.tool_id,
            users=remote,
            connection_id=self._connection_id,
            authoritative=authoritative,
        )
        return [user for user in users if user.external_id != self._delegate.self_id]

    async def ensure_direct_room(self, user_id: UUID | str) -> Room:
        from app.messenger.room_service import synchronize_rooms
        from .contact_access import require_outgoing_user
        await require_outgoing_user(self._connection_id, self.tool_id, await self._external_user_id(user_id))

        remote = await self._delegate.ensure_direct_room(
            await self._external_user_id(user_id)
        )
        rooms = await synchronize_rooms(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            rooms=[remote],
        )
        if not rooms:
            raise RuntimeError("The direct Messenger room could not be persisted.")
        return rooms[0]

    async def create_room(
        self, label: str, invitees: list[UUID | str], kind: str = "group"
    ) -> Room:
        from app.messenger.room_service import synchronize_rooms
        from .contact_access import require_outgoing_user
        for invitee in invitees:
            await require_outgoing_user(self._connection_id, self.tool_id, await self._external_user_id(invitee))

        remote = await self._delegate.create_room(
            label,
            [await self._external_user_id(user_id) for user_id in invitees],
            kind,
        )
        rooms = await synchronize_rooms(
            connection_id=self._connection_id,
            tool_id=self._delegate.tool_id,
            rooms=[remote],
        )
        if not rooms:
            raise RuntimeError("The created Messenger room could not be persisted.")
        return rooms[0]

    async def add_user(self, room_id: UUID | str, user_id: UUID | str) -> None:
        from .contact_access import require_outgoing_user
        await require_outgoing_user(self._connection_id, self.tool_id, await self._external_user_id(user_id))
        await self._delegate.add_user(
            await self._external_room_id(room_id),
            await self._external_user_id(user_id),
        )
        await self.room(room_id)

    async def remove_user(self, room_id: UUID | str, user_id: UUID | str) -> None:
        await self._delegate.remove_user(
            await self._external_room_id(room_id),
            await self._external_user_id(user_id),
        )
        await self.room(room_id)

    async def send_to_room(
        self,
        room_id: UUID | str,
        text: str,
        reply_to: str | None = None,
        *,
        publish_event: bool = True,
        journal_metadata: dict[str, Any] | None = None,
    ) -> Message:
        await self.require_room_contact(room_id)
        external_room_id = await self._external_room_id(room_id)
        message = await self._delegate.send_to_room(external_room_id, text, reply_to)
        return await self._record(
            message,
            room_id=external_room_id,
            publish_event=publish_event,
            journal_metadata=journal_metadata,
        )

    async def send_to_user(
        self, user_id: UUID | str, text: str
    ) -> Message:
        external_user_id = await self._external_user_id(user_id)
        from .contact_access import require_outgoing_user
        await require_outgoing_user(self._connection_id, self.tool_id, external_user_id)
        message = await self._delegate.send_to_user(external_user_id, text)
        return await self._record(
            message,
            room_id=external_user_id,
            user_id=external_user_id,
        )

    async def send(
        self, target: Union[Room, MessengerUser], text: str
    ) -> Message:
        if isinstance(target, Room):
            return await self.send_to_room(target.id, text)
        return await self.send_to_user(target.id, text)

    async def upload_file(
        self,
        room_id: UUID | str,
        path_or_bytes: Union[str, bytes],
        name: str | None = None,
    ) -> Message:
        await self.require_room_contact(room_id)
        external_room_id = await self._external_room_id(room_id)
        message = await self._delegate.upload_file(
            external_room_id, path_or_bytes, name
        )
        return await self._record(message, room_id=external_room_id)

    async def upload_file_path(
        self, room_id: UUID | str, path: Path, name: str | None = None
    ) -> Message:
        await self.require_room_contact(room_id)
        external_room_id = await self._external_room_id(room_id)
        message = await self._delegate.upload_file_path(external_room_id, path, name)
        return await self._record(message, room_id=external_room_id)

    def _file_observation(self, file: File) -> ObservedMessengerFile:
        if file.connection_id != self._connection_id:
            raise ValueError("Messenger file does not belong to this connection.")
        return ObservedMessengerFile(
            id=file.external_identifier or "",
            local_id=file.id,
            name=file.name,
            mime=file.mime_type,
            url=file.remote_url,
            size=file.size_bytes,
            kind=cast(Any, file.kind),
        )

    async def fetch_attachment(self, file: File) -> bytes:
        """Download one persisted file reference without exposing provider metadata."""

        return await self._delegate.fetch_attachment(self._file_observation(file))

    async def fetch_attachment_to_file(self, file: File, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        """Stream one persisted file reference to a local destination."""

        return await self._delegate.fetch_attachment_to_file(
            self._file_observation(file), dest, max_bytes=max_bytes
        )

    async def send_voice_note(
        self,
        room_id: UUID | str,
        path: Path,
        *,
        caption: str | None = None,
        reply_to: str | None = None,
    ) -> Message:
        await self.require_room_contact(room_id)
        external_room_id = await self._external_room_id(room_id)
        message = await self._delegate.send_voice_note(
            external_room_id, path, caption=caption, reply_to=reply_to
        )
        return await self._record(message, room_id=external_room_id)

    async def require_room_contact(self, room_id: UUID | str) -> None:
        from sqlalchemy import select
        from core.database import get_db
        from .contact_access import require_outgoing_room
        external_id = await self._external_room_id(room_id)
        room = await get_db().scalar(select(Room).where(Room.connection_id == self._connection_id, Room.external_id == external_id))
        if room is None:
            raise PermissionError("Room not found")
        await require_outgoing_room(self._connection_id, room.id)
