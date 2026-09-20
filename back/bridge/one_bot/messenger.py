"""
OneBot v11 implementation of ``app.messenger.Messenger``.

It wraps the low-level client, which communicates with adapters through the
reverse-WebSocket hub, and converts the OneBot wire format to and from canonical
messages. Adapters push inbound events, so no listener loop is needed here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, cast

from core.i18n import render_prompt, t
from core.util import as_dict, as_list
from app.messenger.interface import HistoryPage, Messenger
from app.messenger._observations import (
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import Capability

from .client import OneBot, OneBotMessage


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


_GROUP_ROOM_PREFIX = "group:"
_DIRECT_ROOM_PREFIX = "direct:"


def onebot_room_id(message_type: str, remote_id: str) -> str:
    """Namespace OneBot group and direct identifiers in the canonical room space."""
    prefix = _GROUP_ROOM_PREFIX if message_type == "group" else _DIRECT_ROOM_PREFIX
    return f"{prefix}{remote_id}"


def _parse_room_id(room_id: str) -> tuple[Literal["group", "direct"], str]:
    if room_id.startswith(_GROUP_ROOM_PREFIX):
        return "group", room_id.removeprefix(_GROUP_ROOM_PREFIX)
    if room_id.startswith(_DIRECT_ROOM_PREFIX):
        return "direct", room_id.removeprefix(_DIRECT_ROOM_PREFIX)
    # Compatibility for Tasks created before room kinds were namespaced: those Tasks were
    # always sent through the group action.
    return "group", room_id


def _message_id_from_response(response: Any) -> str:
    payload = as_dict(response)
    status = str(payload.get("status") or "").lower()
    raw_retcode = payload.get("retcode")
    try:
        retcode = int(raw_retcode) if raw_retcode is not None else -1
    except (TypeError, ValueError):
        retcode = -1
    if status != "ok" or retcode != 0:
        detail = str(
            payload.get("message")
            or payload.get("wording")
            or payload.get("msg")
            or retcode
        )
        raise RuntimeError(_error("onebot_action_failed", error=detail))
    data = as_dict(payload.get("data"))
    remote_id = data.get("message_id")
    if remote_id is None or not str(remote_id).strip():
        raise RuntimeError(_error("onebot_message_id_missing"))
    return str(remote_id).strip()


# --- OneBot wire-format to canonical-message conversions ---


def _onebot_text(message: Any) -> str:
    """Extract text from a raw OneBot string or segment list."""
    if not isinstance(message, list):
        return str(message or "")
    parts: List[str] = []
    for seg in cast("List[Any]", message):
        if isinstance(seg, dict):
            seg_dict = cast("Dict[str, Any]", seg)
            if seg_dict.get("type") == "text":
                data = seg_dict.get("data")
                if isinstance(data, dict):
                    parts.append(str(cast("Dict[str, Any]", data).get("text", "")))
    return "".join(parts)


def onebot_to_message(
    event: OneBotMessage,
    tool_id: int = 0,
    connection_id: int | None = None,
    conversation_remote_id: str | None = None,
) -> ObservedMessengerMessage:
    """Convert a wire-format ``OneBotMessage`` to a canonical ObservedMessengerMessage.

    The receiving bot in ``recipient`` lets inbound routing resolve the target agent.
    """
    is_group = event.message_type == "group"
    remote_room_id = str(
        event.group_id
        if is_group
        else conversation_remote_id or event.user_id
    ).strip()
    if not remote_room_id:
        raise ValueError("OneBot message has no conversation identifier")
    return ObservedMessengerMessage(
        id=str(event.message_id),
        platform="one_bot",
        tool_id=tool_id,
        sender=ObservedMessengerUser(
            id=str(event.user_id),
            display_name=event.sender.nickname or "",
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        recipient=ObservedMessengerUser(
            id=str(event.self_id),
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        room=ObservedMessengerRoom(
            id=onebot_room_id(event.message_type, remote_room_id),
            kind="group" if is_group else "direct",
            connection_id=connection_id,
            tool_id=tool_id,
        ),
        text=_onebot_text(event.message),
        time=event.time,
    )


class OneBotMessenger(Messenger):
    """OneBot v11 implementation of the internal Messenger interface.

    It wraps the low-level OneBot hub client and converts messages to the canonical model.
    """

    kind = "one_bot"
    capabilities = {
        Capability.SEND,
        Capability.HISTORY,
        Capability.SEARCH_USERS,
    }
    def __init__(
        self, one_bot: OneBot, tool_id: int, self_id: str, connection_id: Optional[int] = None
    ) -> None:
        self._one_bot = one_bot
        self.tool_id = tool_id
        self.self_id = self_id
        self.connection_id = connection_id

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "OneBotMessenger":
        from app.connection import connection_service

        connection = await connection_service.get_connection(connection_id)
        if connection is None:
            raise ValueError(_error(
                "connection_not_found", connection_id=connection_id
            ))
        one_bot = await OneBot.from_connection(connection)
        return cls(
            one_bot=one_bot,
            tool_id=int(connection.tool_id),
            self_id=one_bot.user_id,
            connection_id=connection_id,
        )

    async def check_connection(self) -> str:
        response = await self._one_bot.get_group_list()
        if isinstance(response, dict):
            response_dict = cast("Dict[str, Any]", response)
            if response_dict.get("status") == "failed":
                raise RuntimeError(
                    str(response_dict.get("msg") or "OneBot adapter check failed")
                )
        return self.self_id

    async def search_users(self, query: str) -> List[ObservedMessengerUser]:
        """Search the complete standard OneBot friend and group-member directories."""

        needle = query.strip().casefold()
        rows: list[dict[str, Any]] = []

        def response_rows(payload: Any) -> list[dict[str, Any]]:
            value = as_dict(payload)
            data = value.get("data") if value else payload
            return [as_dict(item) for item in as_list(data) if as_dict(item)]

        rows.extend(response_rows(await self._one_bot.get_friend_list()))
        groups = response_rows(await self._one_bot.get_group_list())
        for group in groups:
            group_id = str(group.get("group_id") or "").strip()
            if not group_id:
                continue
            rows.extend(
                response_rows(await self._one_bot.get_group_member_list(group_id))
            )

        users: dict[str, ObservedMessengerUser] = {}
        for row in rows:
            user_id = str(row.get("user_id") or "").strip()
            if not user_id or user_id == self.self_id:
                continue
            display_name = str(
                row.get("card")
                or row.get("remark")
                or row.get("nickname")
                or user_id
            ).strip()
            if needle and needle not in user_id.casefold() and needle not in display_name.casefold():
                continue
            users[user_id] = ObservedMessengerUser(
                id=user_id,
                display_name=display_name,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            )
        return sorted(
            users.values(),
            key=lambda user: ((user.display_name or user.id).casefold(), user.id),
        )

    async def send_to_room(
        self, room_id: str, text: str, reply_to: Optional[str] = None
    ) -> ObservedMessengerMessage:
        room_kind, remote_id = _parse_room_id(room_id)
        if not remote_id:
            raise ValueError("OneBot room identifier is empty")
        wire_message: Any = text
        if reply_to:
            wire_message = [
                {"type": "reply", "data": {"id": reply_to}},
                {"type": "text", "data": {"text": text}},
            ]
        response = (
            await self._one_bot.send_group_msg(remote_id, wire_message)
            if room_kind == "group"
            else await self._one_bot.send_private_msg(remote_id, wire_message)
        )
        return ObservedMessengerMessage(
            id=_message_id_from_response(response),
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=onebot_room_id(room_kind, remote_id),
                kind=room_kind,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
            reply_to=reply_to,
        )

    async def send_to_user(self, user_id: str, text: str) -> ObservedMessengerMessage:
        response = await self._one_bot.send_private_msg(user_id, text)
        return ObservedMessengerMessage(
            id=_message_id_from_response(response),
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=self.self_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            recipient=ObservedMessengerUser(
                id=user_id,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=onebot_room_id("direct", user_id),
                kind="direct",
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=text,
        )

    async def history(self, room_id: str, limit: int = 20) -> List[ObservedMessengerMessage]:
        room_kind, remote_id = _parse_room_id(room_id)
        if not remote_id:
            raise ValueError("OneBot room identifier is empty")
        events = (
            await self._one_bot.get_group_msg_history(remote_id, limit)
            if room_kind == "group"
            else await self._one_bot.get_private_msg_history(remote_id, limit)
        )
        return [
            onebot_to_message(
                event,
                self.tool_id,
                self.connection_id,
                conversation_remote_id=remote_id,
            )
            for event in events
        ]

    async def history_page(
        self,
        room_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> HistoryPage[ObservedMessengerMessage]:
        if cursor:
            raise ValueError("OneBot provider history has no durable cursor.")
        return HistoryPage(
            messages=await self.history(room_id, limit),
            has_more=False,
            next_cursor=None,
        )
