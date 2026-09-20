"""
Nextcloud Talk implementation of ``app.messenger.Messenger``.

It wraps the low-level OCS client and converts the Nextcloud wire format to and
from canonical messages. Inbound messages arrive through OCS long polling or
HPB signaling.

Galaris is a Nextcloud client, unlike OneBot adapters that connect to Galaris.
Credentials come from the agent's Connection.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Union

from loguru import logger

from core.params import runtime_settings
from core.i18n import render_prompt, t
from core.util import as_dict
from app.messenger.interface import HistoryPage, Messenger
from app.messenger._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import Capability, kind_from_mime
from app.messenger.inbound import dispatch_incoming

from .client import NextcloudTalkClient
from .credentials import resolve_nextcloud_connection
from .signaling import TalkSignalingRoom, extract_hpb_url, normalize_hpb_url

# OGG can contain audio or video and system MIME databases disagree about .oga.
# In messaging these files are Opus voice notes, so classify OGG extensions as audio.
_OGG_AUDIO_EXTS = (".ogg", ".oga", ".opus")


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


def _is_audio(filename: str) -> bool:
    """Return whether a filename represents audio and should become a Talk voice note."""
    if filename.lower().endswith(_OGG_AUDIO_EXTS):
        return True
    mime = mimetypes.guess_type(filename)[0] or ""
    return mime.startswith("audio/") or mime == "application/ogg"


def _listenable_room_tokens(rooms: List[Dict[str, Any]]) -> set[str]:
    """Return active Talk room tokens eligible for inbound listeners."""
    tokens: set[str] = set()
    for room in rooms:
        token = str(room.get("token", "") or "")
        if token and not room.get("isArchived"):
            tokens.add(token)
    return tokens


_KIND = "nextcloud_talk"
_CAPABILITIES = {
    Capability.SEND,
    Capability.HISTORY,
    Capability.UNREAD,
    Capability.REACT,
    Capability.FILES,
    Capability.ROOMS,
    Capability.MEMBERS,
    Capability.SEARCH_USERS,
}

# Maximum long-poll error backoff in seconds.
_POLL_ERROR_BACKOFF_MAX = 120.0


class NextcloudTalkMessenger(Messenger):
    """Nextcloud Talk backend for internal messaging."""

    kind = _KIND
    capabilities = _CAPABILITIES
    rooms_snapshot_complete = True

    def __init__(
        self,
        client: NextcloudTalkClient,
        tool_id: int,
        self_id: str,
        connection_id: Optional[int] = None,
        inbound: str = "polling",
        inbound_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.client = client
        self.tool_id = tool_id
        self.self_id = self_id
        self.connection_id = connection_id
        # Select the inbound listener from MESSENGER_NEXTCLOUD_TALK_INBOUND.
        self.inbound = inbound or "polling"
        self.inbound_options: Dict[str, Any] = inbound_options or {}
        self.room_discovery_interval = (
            runtime_settings.MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL
        )
        self.longpoll_timeout = runtime_settings.MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT
        # Polling state maps a room token to the last processed message ID.
        self._last_seen: Dict[str, int] = {}
        self._room_tasks: Dict[str, asyncio.Task[None]] = {}

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "NextcloudTalkMessenger":
        inbound = runtime_settings.MESSENGER_NEXTCLOUD_TALK_INBOUND
        inbound_options: Dict[str, Any] = {}
        if runtime_settings.MESSENGER_NEXTCLOUD_TALK_HPB_URL:
            inbound_options["signaling_url"] = runtime_settings.MESSENGER_NEXTCLOUD_TALK_HPB_URL

        config = await resolve_nextcloud_connection(connection_id)

        client = NextcloudTalkClient(
            base_url=config.base_url,
            login=config.login,
            password=config.password,
        )
        return cls(
            client=client,
            tool_id=config.tool_id,
            self_id=config.self_id,
            connection_id=connection_id,
            inbound=inbound,
            inbound_options=inbound_options,
        )

    async def check_connection(self) -> str:
        rooms = await self.client.get_rooms()
        return f"{len(rooms)} room(s) visible"

    async def close(self) -> None:
        await self.client.aclose()

    # -- Nextcloud wire-format conversions ------------------------------------

    def _to_room(
        self,
        raw: Dict[str, Any],
        *,
        users: list[ObservedMessengerUser] | None = None,
        users_complete: bool = False,
    ) -> ObservedMessengerRoom:
        return ObservedMessengerRoom(
            id=str(raw.get("token", "")),
            label=str(raw.get("displayName") or raw.get("name") or ""),
            kind="direct" if raw.get("type") == 1 else "group",
            users=users or [],
            users_complete=users_complete,
            connection_id=self.connection_id,
            tool_id=self.tool_id,
        )

    def _participant_users(self, rows: list[dict[str, Any]]) -> list[ObservedMessengerUser]:
        users: dict[str, ObservedMessengerUser] = {}
        for row in rows:
            external_id = str(row.get("actorId") or row.get("userId") or "").strip()
            if not external_id:
                continue
            is_ai = str(row.get("actorType") or "users") == "bots"
            users[external_id] = ObservedMessengerUser(
                id=external_id,
                display_name=str(
                    row.get("displayName")
                    or row.get("actorDisplayName")
                    or external_id
                ),
                is_ai=is_ai,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            )
        return list(users.values())

    async def _room_with_users(self, raw: Dict[str, Any]) -> ObservedMessengerRoom:
        token = str(raw.get("token") or "")
        participants = await self.client.get_room_participants(token)
        return self._to_room(
            raw,
            users=self._participant_users(participants),
            users_complete=True,
        )

    def _to_user(self, actor_id: str, display_name: str = "") -> ObservedMessengerUser:
        return ObservedMessengerUser(
            id=actor_id,
            display_name=display_name,
            connection_id=self.connection_id,
            tool_id=self.tool_id,
        )

    @staticmethod
    def _to_attachments(raw: Dict[str, Any]) -> List[ObservedMessengerFile]:
        """Extract file-share attachments from a Talk message.

        Shared files appear as ``file`` entries in ``messageParameters`` with
        path, name, MIME type, ID, size, and link. Keep only a DAV reference;
        ``fetch_attachment`` downloads it on demand without a local copy.
        """
        params = raw.get("messageParameters")
        if not isinstance(params, dict):
            return []
        atts: List[ObservedMessengerFile] = []
        for value_item in as_dict(params).values():
            value = as_dict(value_item)
            if value.get("type") != "file":
                continue
            mime = str(value.get("mimetype", "") or "")
            atts.append(
                ObservedMessengerFile(
                    id=str(value.get("id", "") or ""),
                    name=str(value.get("name", "") or ""),
                    mime=mime,
                    url=str(value.get("path", "") or "") or None,   # DAV path for download_dav.
                    size=int(value["size"]) if str(value.get("size", "")).isdigit() else None,
                    kind=kind_from_mime(mime),
                )
            )
        return atts

    @staticmethod
    def _render_text(raw: Dict[str, Any]) -> str:
        """Render Talk text by replacing ``{key}`` placeholders.

        Talk sends tokens such as ``{file}`` and ``{mention-user1}``; values live
        in ``messageParameters``. Replace each token with a readable name or ID
        and prefix mentions with ``@`` so the agent sees meaningful content.
        """
        text = str(raw.get("message", "") or "")
        params = raw.get("messageParameters")
        if not isinstance(params, dict):
            return text
        for key, val_item in as_dict(params).items():
            val = as_dict(val_item)
            label = str(val.get("name") or val.get("id") or key)
            if str(val.get("type", "")).startswith("user") or "mention" in str(key):
                label = f"@{label}"
            text = text.replace("{" + str(key) + "}", label)
        return text

    def _to_message(self, token: str, raw: Dict[str, Any]) -> ObservedMessengerMessage:
        return ObservedMessengerMessage(
            id=str(raw.get("id", "")),
            platform=self.kind,
            tool_id=self.tool_id,
            sender=self._to_user(
                str(raw.get("actorId", "")), str(raw.get("actorDisplayName", ""))
            ),
            # The receiving bot lets inbound routing resolve the target agent.
            recipient=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=token,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=self._render_text(raw),
            attachments=self._to_attachments(raw),
            time=int(raw.get("timestamp", 0) or 0),
        )

    @staticmethod
    def _is_relevant_chat(raw: Dict[str, Any]) -> bool:
        """Return whether the message is relevant human chat.

        Ignore system events, bot/system accounts, and markdown welcome notices.
        ``_maybe_dispatch`` separately prevents echoes from this account.
        """
        if raw.get("systemMessage"):
            return False
        if str(raw.get("messageType", "")) == "system":
            return False
        if str(raw.get("actorType", "")) == "bots" or str(raw.get("actorId", "")) == "sample":
            return False
        text = str(raw.get("message", "") or "")
        if not text or text.strip().startswith("## "):
            return False
        return True

    # -- Sending ---------------------------------------------------------------

    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        reply = int(reply_to) if reply_to and reply_to.isdigit() else 0
        res = await self.client.send_message(token=room_id, message=text, reply_to=reply)
        return ObservedMessengerMessage(
            id=str(res.get("id", "")),
            platform=self.kind,
            tool_id=self.tool_id,
            sender=self._to_user(self.self_id),
            room=ObservedMessengerRoom(
                id=room_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
            time=int(res.get("timestamp", 0) or 0),
        )

    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        room = await self.ensure_direct_room(user_id)
        return await self.send_to_room(room.id, text)

    # -- Reading ---------------------------------------------------------------

    async def history(self, room_id: str, limit: int = 20) -> List[ObservedMessengerMessage]:
        raws = await self.client.get_messages(room_id, limit=limit)
        msgs = [self._to_message(room_id, r) for r in raws if self._is_relevant_chat(r)]
        msgs.sort(key=lambda m: m.time)
        return msgs

    async def history_page(
        self,
        room_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[ObservedMessengerMessage]:
        if not 1 <= limit <= 500:
            raise ValueError("Nextcloud room history limit must be between 1 and 500.")
        try:
            last_known_message_id = int(cursor) if cursor else 0
        except ValueError as exc:
            raise ValueError("Invalid Nextcloud room history cursor.") from exc
        if last_known_message_id < 0:
            raise ValueError("Invalid Nextcloud room history cursor.")

        page_raws: list[dict[str, Any]] = []
        next_cursor = str(last_known_message_id) if last_known_message_id else None
        last_batch_size = 0
        last_requested = 0
        while len(page_raws) < limit:
            last_requested = min(200, limit - len(page_raws))
            batch, returned_cursor = await self.client.get_messages_page(
                room_id,
                limit=last_requested,
                last_known_message_id=int(next_cursor) if next_cursor else 0,
            )
            page_raws.extend(batch)
            last_batch_size = len(batch)
            if (
                not returned_cursor
                or returned_cursor == next_cursor
                or last_batch_size < last_requested
            ):
                next_cursor = None
                break
            next_cursor = returned_cursor

        messages = [
            self._to_message(room_id, raw)
            for raw in page_raws
            if self._is_relevant_chat(raw)
        ]
        messages.sort(key=lambda message: message.time)
        has_more = bool(next_cursor) and last_batch_size == last_requested
        return HistoryPage(
            messages=messages,
            has_more=has_more,
            next_cursor=next_cursor if has_more else None,
        )

    @staticmethod
    def _room_unread_count(raw: Dict[str, Any]) -> int:
        try:
            return max(0, int(raw.get("unreadMessages", 0) or 0))
        except (TypeError, ValueError):
            return 0

    async def unread_counts(self, room_ids: Collection[str]) -> dict[str, int]:
        self._require(Capability.UNREAD)
        requested = set(room_ids)
        return {
            token: self._room_unread_count(raw)
            for raw in await self.client.get_rooms()
            if (token := str(raw.get("token", "") or "")) in requested
        }

    async def unread(self, room_id: str) -> List[ObservedMessengerMessage]:
        count = (await self.unread_counts([room_id])).get(room_id, 0)
        if count == 0:
            return []
        page = await self.history_page(room_id, limit=min(count, 500))
        received = [
            message
            for message in page.messages
            if message.sender is None or message.sender.id != self.self_id
        ]
        return received[-count:]

    async def mark_read(self, room_id: str, message_id: str | None = None) -> None:
        if message_id is None or not message_id.isdigit():
            raise ValueError("A displayed numeric Talk message ID is required.")
        await self.client.mark_room_as_read(room_id, int(message_id))

    # -- Rooms and members -----------------------------------------------------

    async def rooms(self) -> List[ObservedMessengerRoom]:
        return [await self._room_with_users(raw) for raw in await self.client.get_rooms()]

    async def room(self, room_id: str) -> Optional[ObservedMessengerRoom]:
        for r in await self.client.get_rooms():
            if str(r.get("token", "")) == room_id:
                return await self._room_with_users(r)
        return None

    async def ensure_direct_room(self, user_id: str) -> ObservedMessengerRoom:
        """Resolve or create the private room shared with a user.

        A private message must land where the pair last talked, which in Talk
        may be the one-to-one room or a two-person group room. Select the most
        recently active non-archived room whose human participants are exactly
        the user and this account; bot attendees do not count. Archived rooms
        and rooms with a third person are never selected. Create a one-to-one
        room when no such room exists.
        """
        candidates = [
            raw
            for raw in await self.client.get_rooms()
            if raw.get("type") in (1, 2, 3) and not raw.get("isArchived")
        ]
        candidates.sort(key=lambda r: int(r.get("lastActivity", 0) or 0), reverse=True)
        for raw in candidates:
            participants = await self.client.get_room_participants(str(raw.get("token", "")))
            users = {
                str(p.get("actorId") or p.get("userId") or "")
                for p in participants
                if str(p.get("actorType") or "users") == "users"
            }
            users.discard("")
            if user_id not in users:
                continue
            # Talk guarantees one-to-one rooms hold exactly the two of us.
            if raw.get("type") == 1 or len(users) == 2:
                return self._to_room(
                    raw,
                    users=self._participant_users(participants),
                    users_complete=True,
                )
        created = await self.client.create_conversation(invitees=[user_id], room_type=1)
        return await self._room_with_users(created)

    async def create_room(
        self, label: str, invitees: List[str], kind: str = "group"
    ) -> ObservedMessengerRoom:
        room_type = 2 if kind == "group" else 1
        created = await self.client.create_conversation(
            invitees=invitees, room_type=room_type, room_name=label
        )
        return await self._room_with_users(created)

    async def add_user(self, room_id: str, user_id: str) -> None:
        await self.client.add_participant(room_id, user_id)

    async def remove_user(self, room_id: str, user_id: str) -> None:
        await self.client.remove_participant(room_id, user_id)

    # -- Users -----------------------------------------------------------------

    async def search_users(self, query: str) -> List[ObservedMessengerUser]:
        return [
            self._to_user(str(u.get("id", "")), str(u.get("displayName", "")))
            for u in await self.client.list_users(query)
            if u.get("id")
        ]

    # -- Reactions -------------------------------------------------------------

    async def react(
        self, message_id: str, emoji: str, room_id: Optional[str] = None
    ) -> None:
        if not room_id:
            raise ValueError(_error(
                "reaction_room_required", operation="react"
            ))
        await self.client.add_reaction(room_id, int(message_id), emoji)

    async def unreact(
        self, message_id: str, emoji: str, room_id: Optional[str] = None
    ) -> None:
        if not room_id:
            raise ValueError(_error(
                "reaction_room_required", operation="unreact"
            ))
        await self.client.remove_reaction(room_id, int(message_id), emoji)

    # -- Attachments -----------------------------------------------------------

    async def _shared_file_message(
        self,
        room_id: str,
        remote_path: str,
        display_name: str,
        accepted_ref: str = "",
    ) -> ObservedMessengerMessage:
        """Resolve the Talk message created by a successful OCS file share.

        The share endpoint acknowledges the mutation but does not return the Talk
        message id. Read the recent provider history once using the unique DAV name;
        if propagation is delayed, retain a unique accepted-share id rather than an
        empty id that would collide with every other outbound file.
        """

        expected_name = Path(remote_path).name
        try:
            raws = await self.client.get_messages(room_id, limit=30)
        except Exception as exc:
            logger.warning(
                "Talk file share accepted but recent history lookup failed: {}",
                exc,
            )
            raws = []
        candidates = [
            raw
            for raw in raws
            if any(
                attachment.name == expected_name
                for attachment in self._to_attachments(raw)
            )
        ]
        if candidates:
            raw = max(candidates, key=lambda item: int(item.get("id", 0) or 0))
            return self._to_message(room_id, raw)
        return ObservedMessengerMessage(
            id=f"file-share:{accepted_ref or remote_path.lstrip('/')}",
            platform=self.kind,
            tool_id=self.tool_id,
            sender=self._to_user(self.self_id),
            room=ObservedMessengerRoom(
                id=room_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=display_name,
        )

    async def upload_file(
        self, room_id: str, path_or_bytes: Union[str, bytes], name: Optional[str] = None
    ) -> ObservedMessengerMessage:
        """Share a file in a Talk room.

        A string references an existing Nextcloud path. Bytes are first uploaded
        to the ``Talk/`` WebDAV directory and then shared.
        """
        if isinstance(path_or_bytes, str):
            path = path_or_bytes
            voice = _is_audio(name or path)
        else:
            import uuid

            safe = (name or "file").replace("/", "_").lstrip(".") or "file"
            folder = "Talk"  # Nextcloud directory for Talk attachments.
            path = f"/{folder}/{uuid.uuid4().hex[:8]}-{safe}"
            content_type = mimetypes.guess_type(safe)[0]
            voice = _is_audio(safe)
            await self.client.ensure_folder(folder)
            await self.client.upload_dav(path, path_or_bytes, content_type)

        accepted = await self.client.share_file_to_room(
            room_id, path, voice_message=voice
        )
        return await self._shared_file_message(
            room_id,
            path,
            name or Path(path).name,
            str(accepted.get("id") or ""),
        )

    async def upload_file_path(
        self, room_id: str, path: Path, name: Optional[str] = None
    ) -> ObservedMessengerMessage:
        """Stream a local file into a Talk room, including large files and videos.

        Upload the disk file into the ``Talk/`` WebDAV directory without loading
        it into memory, then share it. This bounded-memory implementation overrides
        the buffered Messenger default.
        """
        import uuid

        display = name or path.name
        safe = display.replace("/", "_").lstrip(".") or "file"
        folder = "Talk"  # Nextcloud directory for Talk attachments.
        remote = f"/{folder}/{uuid.uuid4().hex[:8]}-{safe}"
        content_type = mimetypes.guess_type(safe)[0]
        await self.client.ensure_folder(folder)
        await self.client.upload_dav_file(remote, path, content_type)
        accepted = await self.client.share_file_to_room(
            room_id, remote, voice_message=_is_audio(safe)
        )
        return await self._shared_file_message(
            room_id,
            remote,
            display,
            str(accepted.get("id") or ""),
        )

    async def fetch_attachment(self, attachment: ObservedMessengerFile) -> bytes:
        if not attachment.id and not attachment.url:
            raise ValueError(_error("attachment_reference_missing"))
        # Prefer the stable fileId because Talk paths vary by sender/bot perspective.
        return await self.client.download_by_id(
            attachment.id, fallback_path=attachment.url or ""
        )

    async def fetch_attachment_to_file(self, attachment: ObservedMessengerFile, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        """Stream an attachment to ``dest`` with bounded memory."""
        if not attachment.id and not attachment.url:
            raise ValueError(_error("attachment_reference_missing"))
        return await self.client.download_by_id_to_file(
            attachment.id, dest, fallback_path=attachment.url or "", max_bytes=max_bytes
        )

    # -- Inbound polling -------------------------------------------------------

    async def listen(self) -> None:
        """Receive messages according to ``MESSENGER_NEXTCLOUD_TALK_INBOUND``.

        ``polling`` uses one OCS long poll per room. ``signaling`` uses real-time
        HPB WebSockets and requires an HPB. Unsupported values fall back to polling.
        """
        if self.inbound == "signaling":
            await self._listen_signaling()
            return
        if self.inbound not in ("polling", "", "push"):
            logger.warning(
                "Talk: unsupported inbound mode '{}'; falling back to polling", self.inbound
            )
        await self._listen_polling()

    async def _listen_polling(self) -> None:
        """Poll each room while periodically discovering room changes.

        Convert each relevant non-self message and deliver it to
        ``dispatch_incoming``. Run one background listener per Talk connection.

        Archived rooms are never listened to or replayed. Active room workers
        replay recent relevant history when they start, and stop when the room
        disappears or becomes archived.
        """
        logger.info(
            "Nextcloud Talk polling started (self_id={}, tool_id={})", self.self_id, self.tool_id
        )
        try:
            while True:
                try:
                    rooms = await self.client.get_rooms()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Talk: room discovery failed")
                    await asyncio.sleep(self.room_discovery_interval)
                    continue

                current = _listenable_room_tokens(rooms)

                # A room worker may terminate independently from the discovery loop.
                # Remove completed workers so the same reconciliation pass recreates them.
                for token, task in list(self._room_tasks.items()):
                    if token not in current or not task.done():
                        continue
                    self._room_tasks.pop(token, None)
                    outcome = (await asyncio.gather(task, return_exceptions=True))[0]
                    if isinstance(outcome, BaseException):
                        logger.warning(
                            "Talk: room {} listener stopped unexpectedly: {}",
                            token,
                            type(outcome).__name__,
                        )
                    else:
                        logger.warning("Talk: room {} listener stopped unexpectedly", token)

                # Replay the bounded provider history on every worker start. The canonical
                # journal deduplicates it and therefore also recovers messages received while
                # Galaris or this room worker was unavailable.
                for token in current - set(self._room_tasks):
                    self._room_tasks[token] = asyncio.create_task(
                        self._poll_room(token, process_existing=True),
                        name=f"talk_poll_{token}",
                    )
                # Stop long polls for rooms that disappeared.
                for token in set(self._room_tasks) - current:
                    task = self._room_tasks.pop(token, None)
                    if task:
                        task.cancel()
                    self._last_seen.pop(token, None)

                await asyncio.sleep(self.room_discovery_interval)
        except asyncio.CancelledError:
            for task in self._room_tasks.values():
                task.cancel()
            if self._room_tasks:
                await asyncio.gather(*self._room_tasks.values(), return_exceptions=True)
            self._room_tasks.clear()
            raise

    async def _poll_room(self, token: str, process_existing: bool = False) -> None:
        """Long-poll one room after setting a baseline at its latest message.

        For newly discovered rooms, ``process_existing=True`` replays recent
        history once. Inbound deduplication handles overlap. Persistent network
        errors use exponential backoff.
        """
        try:
            recent = await self.client.get_messages(token, limit=20, look_into_future=0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Talk: failed to establish room {} baseline", token)
            recent = []

        if recent and not process_existing:
            self._last_seen[token] = max(int(r.get("id", 0) or 0) for r in recent)
        elif recent:
            for raw in sorted(recent, key=lambda r: int(r.get("id", 0) or 0)):
                try:
                    await self._maybe_dispatch(token, raw)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Talk: failed to dispatch message {} (room {}); keeping cursor for retry",
                        raw.get("id"),
                        token,
                    )
                    break

        backoff = 1.0
        while True:
            try:
                last = self._last_seen.get(token, 0)
                new_msgs = await self.client.get_messages(
                    token,
                    look_into_future=1,
                    last_known_message_id=last,
                    limit=100,
                    timeout=self.longpoll_timeout,
                )
                backoff = 1.0  # Reset after a successful call.
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Talk: room {} long poll failed (retrying in {}s)", token, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _POLL_ERROR_BACKOFF_MAX)
                continue

            for raw in new_msgs:
                try:
                    await self._maybe_dispatch(token, raw)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Talk: failed to dispatch message {} (room {}); keeping cursor for retry",
                        raw.get("id"),
                        token,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _POLL_ERROR_BACKOFF_MAX)
                    break

    async def _maybe_dispatch(self, token: str, raw: Dict[str, Any]) -> None:
        """Filter relevance and echoes, then deliver to ``dispatch_incoming``.

        Polling and signaling share this filtering and deduplication entry point.
        """
        msg_id = int(raw.get("id", 0) or 0)
        if not self._is_relevant_chat(raw):
            if msg_id > self._last_seen.get(token, 0):
                self._last_seen[token] = msg_id
            return
        if str(raw.get("actorId", "")) == self.self_id:
            if msg_id > self._last_seen.get(token, 0):
                self._last_seen[token] = msg_id
            return  # Do not echo our own messages.
        await dispatch_incoming(self._to_message(token, raw))
        if msg_id > self._last_seen.get(token, 0):
            self._last_seen[token] = msg_id

    async def _seed_baselines(self) -> None:
        """Set ``_last_seen`` to the latest message in every active room."""
        try:
            rooms = await self.client.get_rooms()
        except Exception:
            logger.exception("Talk: failed to establish room baselines")
            return
        for token in _listenable_room_tokens(rooms):
            try:
                recent = await self.client.get_messages(token, look_into_future=0, limit=1)
            except Exception as exc:
                logger.warning(
                    "Talk: failed to seed room baseline room={} error={}",
                    token,
                    type(exc).__name__,
                )
                continue
            if recent:
                self._last_seen[token] = max(int(r.get("id", 0) or 0) for r in recent)

    async def _sync_room(self, token: str) -> None:
        """Fetch and dispatch room messages newer than ``_last_seen[token]``."""
        last = self._last_seen.get(token, 0)
        if last:
            new_msgs = await self.client.get_messages(
                token, look_into_future=1, last_known_message_id=last, limit=100, timeout=5
            )
        else:
            # For an unseen room, fetch recent history; inbound deduplication handles overlap.
            new_msgs = await self.client.get_messages(token, look_into_future=0, limit=20)
        for raw in new_msgs:
            await self._maybe_dispatch(token, raw)

    # -- Real-time inbound HPB signaling ---------------------------------------

    async def _resolve_hpb_url(self) -> str:
        """Resolve the HPB URL from inbound options or Talk discovery."""
        configured = str(
            self.inbound_options.get("signaling_url")
            or runtime_settings.MESSENGER_NEXTCLOUD_TALK_HPB_URL
            or ""
        )
        if configured:
            return normalize_hpb_url(configured)
        try:
            sig_settings = await self.client.get_signaling_settings()
            return extract_hpb_url(sig_settings)
        except Exception:
            logger.exception("Talk: HPB URL discovery failed")
            return ""

    async def _listen_signaling(self) -> None:
        """Receive in real time through one HPB WebSocket per room.

        Fall back to polling when no HPB is configured or discovered. Active
        room additions, removals, and archival transitions are discovered
        incrementally; archived rooms never receive an HPB client.
        """
        hpb_url = await self._resolve_hpb_url()
        if not hpb_url:
            logger.warning(
                "Talk: no HPB URL is configured or discovered; falling back to polling"
            )
            await self._listen_polling()
            return

        logger.info(
            "Nextcloud Talk signaling started (hpb={}, self_id={}, tool_id={})",
            hpb_url, self.self_id, self.tool_id,
        )
        clients: Dict[str, TalkSignalingRoom] = {}
        tasks: Dict[str, asyncio.Task[None]] = {}
        try:
            while True:
                try:
                    rooms = await self.client.get_rooms()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Talk signaling: room discovery failed")
                    await asyncio.sleep(self.room_discovery_interval)
                    continue

                current = _listenable_room_tokens(rooms)

                for token, task in list(tasks.items()):
                    if token not in current or not task.done():
                        continue
                    sig = clients.pop(token, None)
                    tasks.pop(token, None)
                    if sig is not None:
                        await sig.stop()
                    outcome = (await asyncio.gather(task, return_exceptions=True))[0]
                    if isinstance(outcome, BaseException):
                        logger.warning(
                            "Talk signaling: room {} listener stopped unexpectedly: {}",
                            token,
                            type(outcome).__name__,
                        )
                    else:
                        logger.warning(
                            "Talk signaling: room {} listener stopped unexpectedly", token
                        )

                for token in current - set(clients):
                    sig = TalkSignalingRoom(
                        hpb_url=hpb_url,
                        client=self.client,
                        room_token=token,
                        self_id=self.self_id,
                        nextcloud_url=self.client.base_url,
                        on_raw=self._maybe_dispatch,
                        on_refresh=self._sync_room,
                    )
                    clients[token] = sig
                    tasks[token] = asyncio.create_task(sig.start(), name=f"talk_sig_{token}")
                for token in set(clients) - current:
                    sig = clients.pop(token, None)
                    task = tasks.pop(token, None)
                    if sig is not None:
                        await sig.stop()
                    if task is not None:
                        task.cancel()

                await asyncio.sleep(self.room_discovery_interval)
        except asyncio.CancelledError:
            for sig in clients.values():
                await sig.stop()
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise
