"""
Low-level OneBot v11 client and reverse-WebSocket hub.

``MessengerHub``, instantiated as ``hub``, maintains adapter connections from
Napcat, Lagrange, and similar clients. It relays OneBot actions such as
``send_group_msg`` and ``get_group_msg_history``. ``OneBot`` is the bridge's
high-level client and transitional direct-send fallback.

Protocol-specific behavior remains confined to this bridge.
"""

from __future__ import annotations

import json
import asyncio
import uuid
from typing import Any, List, Optional

from fastapi import WebSocket, HTTPException
from loguru import logger
from pydantic import BaseModel, ConfigDict

from core.i18n import render_prompt, t, tr
from core.util import as_dict, as_list


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


def _history_rows(result: Any) -> list[Any]:
    payload = as_dict(result)
    data: Any = payload.get("data") if payload else result
    if isinstance(data, dict):
        data = as_dict(data).get("messages")
    return as_list(data)


class MessageSender(BaseModel):
    user_id: Optional[str] = None
    nickname: Optional[str] = None
    role: Optional[str] = None  # admin, owner, member


class OneBotMessage(BaseModel):
    """Standard format of a received message (Inbound)"""

    model_config = ConfigDict(extra="ignore")  # Ignores bonus fields sent by some adapters

    time: int
    self_id: str
    post_type: str  # message, notice, request, meta_event
    message_type: str  # private, group
    sub_type: Optional[str] = None
    message_id: str
    user_id: str
    message: Any  # Can be a string or a list of segments
    raw_message: str
    font: Optional[int] = None
    sender: MessageSender
    group_id: Optional[str] = None  # Present only if message_type == 'group'


class OneBot:
    def __init__(
        self,
        platform: str = "",
        user_id: str = "",
        password: str = "",
    ) -> None:
        self.platform = platform
        self.user_id = user_id
        self.password = password

    @classmethod
    async def from_connection(cls, connection: Any) -> OneBot:
        """Create a OneBot client from a Connection object."""
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            int(connection.id),
            expected_service="one_bot",
        )
        platform = resolved.settings.get("platform", "")
        if not platform:
            raise ValueError(_error("onebot_platform_required"))
        return cls(
            platform=platform,
            user_id=str(resolved.params.get("user_id") or ""),
            password=str(resolved.params.get("token") or ""),
        )

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> OneBot:
        """Create a OneBot client from a connection ID."""
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            connection_id,
            expected_service="one_bot",
        )
        platform = resolved.settings.get("platform", "")
        if not platform:
            raise ValueError(_error("onebot_platform_required"))
        return cls(
            platform=platform,
            user_id=str(resolved.params.get("user_id") or ""),
            password=str(resolved.params.get("token") or ""),
        )

    async def send_group_msg(
        self, group_id: str = "", message: Any = None
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "send_group_msg",
            {"group_id": group_id, "message": message},
        )

    async def send_private_msg(
        self, user_id: str = "", message: Any = None
    ) -> Any:
        _user_id = user_id or self.user_id
        return await hub.call(
            self.platform,
            self.user_id,
            "send_private_msg",
            {"user_id": _user_id, "message": message},
        )

    async def delete_msg(self, message_id: str = "") -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "delete_msg",
            {"message_id": message_id},
        )

    async def get_group_list(self) -> Any:
        return await hub.call(
            self.platform, self.user_id, "get_group_list", {}
        )

    async def get_friend_list(self) -> Any:
        return await hub.call(
            self.platform, self.user_id, "get_friend_list", {}
        )

    async def get_group_member_list(self, group_id: str) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "get_group_member_list",
            {"group_id": group_id},
        )

    async def create_group(
        self, group_name: str = "", **kwargs: Any
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "create_group",
            {"group_name": group_name, **kwargs},
        )

    async def set_group_add(
        self, group_id: str = "", user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await hub.call(
            self.platform,
            self.user_id,
            "set_group_add",
            {"group_id": group_id, "user_id": _user_id},
        )

    async def set_group_kick(
        self, group_id: str = "", user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await hub.call(
            self.platform,
            self.user_id,
            "set_group_kick",
            {"group_id": group_id, "user_id": _user_id},
        )

    async def get_group_msg_history(
        self, group_id: str = "", limit: int = 0
    ) -> List[OneBotMessage]:
        payload: dict[str, Any] = {"group_id": group_id}
        if limit > 0:
            payload["limit"] = limit
        result = await hub.call(
            self.platform,
            self.user_id,
            "get_group_msg_history",
            payload,
        )
        # Normalize the OneBot v11 response by extracting the data list.
        messages_data = _history_rows(result)

        # Convert rows to OneBotMessage objects.
        return [OneBotMessage.model_validate(msg) for msg in messages_data]

    async def get_private_msg_history(
        self, user_id: str = "", limit: int = 0
    ) -> List[OneBotMessage]:
        """Return private history through the common NapCat/Lagrange extension."""
        payload: dict[str, Any] = {"user_id": user_id}
        if limit > 0:
            payload["limit"] = limit
        result = await hub.call(
            self.platform,
            self.user_id,
            "get_friend_msg_history",
            payload,
        )
        return [OneBotMessage.model_validate(msg) for msg in _history_rows(result)]

    async def get_unread_messages(
        self, group_id: str = ""
    ) -> List[OneBotMessage]:
        result = await hub.call(
            self.platform,
            self.user_id,
            "get_unread_messages",
            {"group_id": group_id},
        )
        # Normalize the OneBot v11 response by extracting the data list.
        messages_data: List[Any] = []
        if isinstance(result, dict) and "data" in result:
            messages_data = as_list(as_dict(result).get("data"))
        elif isinstance(result, list):
            messages_data = as_list(result)
        else:
            messages_data = []

        # Convert rows to OneBotMessage objects.
        return [OneBotMessage.model_validate(msg) for msg in messages_data]

    async def set_msg_emoji_like(
        self, message_id: str = "", emoji: str = ""
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "set_msg_emoji_like",
            {"message_id": message_id, "emoji": emoji},
        )

    async def upload_group_file(
        self, group_id: str = "", file: str = ""
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "upload_group_file",
            {"group_id": group_id, "file": file},
        )

    async def get_stranger_info(
        self, user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await hub.call(
            self.platform,
            self.user_id,
            "get_stranger_info",
            {"user_id": _user_id},
        )

    async def get_file(self, file_id: str = "") -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "get_file",
            {"file_id": file_id},
        )

    async def send_display_status(
        self, target_id: str = "", status: str = ""
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "send_display_status",
            {"target_id": target_id, "status": status},
        )

    async def mark_group_msg_as_read(
        self, group_id: str = ""
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "mark_group_msg_as_read",
            {"group_id": group_id},
        )

    async def get_group_info(self, group_id: str = "") -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "get_group_info",
            {"group_id": group_id},
        )

    async def set_group_pin(
        self,
        group_id: str = "",
        message_id: str = "",
        unpin: bool = False,
    ) -> Any:
        return await hub.call(
            self.platform,
            self.user_id,
            "set_group_pin",
            {"group_id": group_id, "message_id": message_id, "unpin": unpin}
        )


class MessengerHub:
    def __init__(self) -> None:
        # { "platform:user_id": WebSocket }
        self.adapters: dict[str, WebSocket] = {}
        # { "echo_id": asyncio.Future } to wait for responses
        self.pending_responses: dict[str, asyncio.Future[Any]] = {}
        # Events to signal adapter connection for pending calls
        self._connected_events: dict[str, asyncio.Event] = {}

    def _make_key(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}" if user_id else platform

    async def register(self, platform: str, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        key = self._make_key(platform, user_id)
        self.adapters[key] = websocket
        event = self._connected_events.pop(key, None)
        if event:
            event.set()
        logger.info("OneBot adapter connected: {}", key)

    def unregister(self, platform: str, user_id: str, websocket: WebSocket) -> None:
        key = self._make_key(platform, user_id)
        if self.adapters.get(key) is websocket:
            del self.adapters[key]
            logger.info("OneBot adapter disconnected: {}", key)

    async def call(
        self, platform: str, user_id: str, action: str, params: dict[str, Any]
    ) -> Any:
        """Universal method to send an order and wait for the result."""
        key = self._make_key(platform, user_id)
        if key not in self.adapters:
            # Wait for the adapter to connect (lazy registration)
            event = self._connected_events.get(key)
            if event is None:
                event = asyncio.Event()
                self._connected_events[key] = event
            try:
                await asyncio.wait_for(event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                self._connected_events.pop(key, None)
                raise HTTPException(
                    status_code=404,
                    detail=render_prompt(
                        await tr("messenger_bridge.errors.adapter_not_connected"),
                        adapter=key,
                    ),
                )

        echo_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending_responses[echo_id] = future

        # Standard OneBot v11 Format
        payload: dict[str, Any] = {"action": action, "params": params, "echo": echo_id}
        try:
            await self.adapters[key].send_text(json.dumps(payload))
            # We wait max 5 seconds for the adapter's response
            return await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            return {"status": "failed", "msg": "timeout"}
        finally:
            self.pending_responses.pop(echo_id, None)
            if not future.done():
                future.cancel()


hub = MessengerHub()
