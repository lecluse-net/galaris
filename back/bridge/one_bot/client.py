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
import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated, Any, List, Literal, Optional

from fastapi import WebSocket, HTTPException
from loguru import logger
from pydantic import BaseModel, BeforeValidator, ConfigDict

from core.i18n import render_prompt, t, tr
from core.util import as_dict, as_list
from app.messenger.interface import DeliveryOutcomeUnknown


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


def _history_rows(result: Any) -> list[Any]:
    data = action_data(result)
    if isinstance(data, dict):
        data = as_dict(data).get("messages")
    return as_list(data)


def action_data(response: object) -> Any:
    """Require a confirmed OneBot result before consuming provider data."""
    payload = as_dict(response)
    try:
        retcode = int(payload.get("retcode", -1))
    except (TypeError, ValueError):
        retcode = -1
    if payload.get("status") != "ok" or retcode != 0:
        detail = str(payload.get("message") or payload.get("wording") or payload.get("msg") or retcode)[:500]
        raise RuntimeError(_error("onebot_action_failed", error=detail))
    return payload.get("data")


def _wire_identifier(value: object) -> object:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


OneBotIdentifier = Annotated[str, BeforeValidator(_wire_identifier)]


class MessageSender(BaseModel):
    user_id: OneBotIdentifier | None = None
    nickname: Optional[str] = None
    role: Optional[str] = None  # admin, owner, member


class OneBotMessage(BaseModel):
    """Standard format of a received message (Inbound)"""

    model_config = ConfigDict(extra="ignore")  # Ignores bonus fields sent by some adapters

    time: int
    self_id: OneBotIdentifier
    post_type: str  # message, notice, request, meta_event
    message_type: Literal["private", "group"]
    sub_type: Optional[str] = None
    message_id: OneBotIdentifier
    user_id: OneBotIdentifier
    message: Any  # Can be a string or a list of segments
    raw_message: str
    font: Optional[int] = None
    sender: MessageSender
    group_id: OneBotIdentifier | None = None


class OneBot:
    def __init__(
        self,
        platform: str = "",
        user_id: str = "",
        password: str = "",
        *, connection_id: int | None = None,
    ) -> None:
        self.platform = platform
        self.user_id = user_id
        self.password = password
        self.connection_id = connection_id

    async def _call(self, action: str, params: dict[str, Any]) -> Any:
        if self.connection_id is not None:
            from app.messenger import resolve_messenger_configuration

            resolved = await resolve_messenger_configuration(self.connection_id, expected_service="one_bot")
            if (resolved.settings.get("platform") != self.platform
                    or str(resolved.params.get("user_id") or "") != self.user_id
                    or not hmac.compare_digest(
                        str(resolved.params.get("token") or "").encode(), self.password.encode(),
                    )):
                raise ValueError(_error("onebot_connection_changed"))
        return await hub.call(
            self.platform, self.user_id, action, params,
            connection_id=self.connection_id, token=self.password,
        )

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
            connection_id=resolved.connection_id,
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
            connection_id=resolved.connection_id,
        )

    async def send_group_msg(
        self, group_id: str = "", message: Any = None
    ) -> Any:
        return await self._call(
            "send_group_msg",
            {"group_id": group_id, "message": message},
        )

    async def send_private_msg(
        self, user_id: str = "", message: Any = None
    ) -> Any:
        _user_id = user_id or self.user_id
        return await self._call(
            "send_private_msg",
            {"user_id": _user_id, "message": message},
        )

    async def delete_msg(self, message_id: str = "") -> Any:
        return await self._call(
            "delete_msg",
            {"message_id": message_id},
        )

    async def get_group_list(self) -> Any:
        return await self._call(
            "get_group_list", {}
        )

    async def get_login_info(self) -> Any:
        return await self._call("get_login_info", {})

    async def get_friend_list(self) -> Any:
        return await self._call(
            "get_friend_list", {}
        )

    async def get_group_member_list(self, group_id: str) -> Any:
        return await self._call(
            "get_group_member_list",
            {"group_id": group_id},
        )

    async def create_group(
        self, group_name: str = "", **kwargs: Any
    ) -> Any:
        return await self._call(
            "create_group",
            {"group_name": group_name, **kwargs},
        )

    async def set_group_add(
        self, group_id: str = "", user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await self._call(
            "set_group_add",
            {"group_id": group_id, "user_id": _user_id},
        )

    async def set_group_kick(
        self, group_id: str = "", user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await self._call(
            "set_group_kick",
            {"group_id": group_id, "user_id": _user_id},
        )

    async def get_group_msg_history(
        self, group_id: str = "", limit: int = 0
    ) -> List[OneBotMessage]:
        payload: dict[str, Any] = {"group_id": group_id}
        if limit > 0:
            payload["limit"] = limit
        result = await self._call(
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
        result = await self._call(
            "get_friend_msg_history",
            payload,
        )
        return [OneBotMessage.model_validate(msg) for msg in _history_rows(result)]

    async def get_unread_messages(
        self, group_id: str = ""
    ) -> List[OneBotMessage]:
        result = await self._call(
            "get_unread_messages",
            {"group_id": group_id},
        )
        # Normalize the OneBot v11 response by extracting the data list.
        messages_data = as_list(action_data(result))

        # Convert rows to OneBotMessage objects.
        return [OneBotMessage.model_validate(msg) for msg in messages_data]

    async def set_msg_emoji_like(
        self, message_id: str = "", emoji: str = ""
    ) -> Any:
        return await self._call(
            "set_msg_emoji_like",
            {"message_id": message_id, "emoji": emoji},
        )

    async def upload_group_file(
        self, group_id: str = "", file: str = ""
    ) -> Any:
        return await self._call(
            "upload_group_file",
            {"group_id": group_id, "file": file},
        )

    async def get_stranger_info(
        self, user_id: str = ""
    ) -> Any:
        _user_id = user_id or self.user_id
        return await self._call(
            "get_stranger_info",
            {"user_id": _user_id},
        )

    async def get_file(self, file_id: str = "") -> Any:
        return await self._call(
            "get_file",
            {"file_id": file_id},
        )

    async def send_display_status(
        self, target_id: str = "", status: str = ""
    ) -> Any:
        return await self._call(
            "send_display_status",
            {"target_id": target_id, "status": status},
        )

    async def mark_group_msg_as_read(
        self, group_id: str = ""
    ) -> Any:
        return await self._call(
            "mark_group_msg_as_read",
            {"group_id": group_id},
        )

    async def get_group_info(self, group_id: str = "") -> Any:
        return await self._call(
            "get_group_info",
            {"group_id": group_id},
        )

    async def set_group_pin(
        self,
        group_id: str = "",
        message_id: str = "",
        unpin: bool = False,
    ) -> Any:
        return await self._call(
            "set_group_pin",
            {"group_id": group_id, "message_id": message_id, "unpin": unpin}
        )


AdapterKey = tuple[str, str, int | None, str]


@dataclass
class _PendingResponse:
    key: AdapterKey
    websocket: WebSocket
    future: asyncio.Future[Any]


class MessengerHub:
    def __init__(self, *, response_timeout: float = 5.0, connection_timeout: float = 10.0) -> None:
        self.adapters: dict[AdapterKey, WebSocket] = {}
        self.pending_responses: dict[str, _PendingResponse] = {}
        self._connected_events: dict[AdapterKey, tuple[asyncio.Event, int]] = {}
        self.response_timeout = response_timeout
        self.connection_timeout = connection_timeout

    def _make_key(
        self, platform: str, user_id: str, connection_id: int | None = None, token: str = "",
    ) -> AdapterKey:
        return platform, user_id, connection_id, hashlib.sha256(token.encode()).hexdigest()

    def is_current(
        self, platform: str, user_id: str, websocket: WebSocket, *,
        connection_id: int | None = None, token: str = "",
    ) -> bool:
        return self.adapters.get(self._make_key(platform, user_id, connection_id, token)) is websocket

    def _fail_pending(self, websocket: WebSocket) -> None:
        for pending in list(self.pending_responses.values()):
            if pending.websocket is websocket and not pending.future.done():
                pending.future.set_exception(ConnectionError("OneBot adapter disconnected"))

    async def register(
        self, platform: str, user_id: str, websocket: WebSocket, *,
        connection_id: int | None = None, token: str = "",
    ) -> None:
        await websocket.accept()
        key = self._make_key(platform, user_id, connection_id, token)
        previous = self.adapters.get(key)
        self.adapters[key] = websocket
        if previous is not None and previous is not websocket:
            self._fail_pending(previous)
            try:
                await previous.close(code=1012)
            except Exception:
                logger.debug("OneBot previous adapter was already closed")
        waiting = self._connected_events.get(key)
        if waiting is not None:
            waiting[0].set()
        logger.info("OneBot adapter connected platform={} connection={}", platform, connection_id)

    def unregister(
        self, platform: str, user_id: str, websocket: WebSocket, *,
        connection_id: int | None = None, token: str = "",
    ) -> None:
        key = self._make_key(platform, user_id, connection_id, token)
        if self.adapters.get(key) is websocket:
            del self.adapters[key]
        self._fail_pending(websocket)

    def resolve_response(self, websocket: WebSocket, response: dict[str, Any]) -> None:
        echo = response.get("echo")
        if not isinstance(echo, str):
            return
        pending = self.pending_responses.get(echo)
        if (pending is None or pending.websocket is not websocket
                or self.adapters.get(pending.key) is not websocket or pending.future.done()):
            return
        pending.future.set_result(response)

    async def call(
        self, platform: str, user_id: str, action: str, params: dict[str, Any], *,
        connection_id: int | None = None, token: str = "",
    ) -> Any:
        """Keep each action bound to its authenticated connection and socket."""
        key = self._make_key(platform, user_id, connection_id, token)
        if key not in self.adapters:
            event, waiters = self._connected_events.get(key, (asyncio.Event(), 0))
            self._connected_events[key] = event, waiters + 1
            try:
                await asyncio.wait_for(event.wait(), timeout=self.connection_timeout)
            except asyncio.TimeoutError:
                raise HTTPException(status_code=404, detail=render_prompt(
                    await tr("messenger_bridge.errors.adapter_not_connected"), adapter=f"{platform}:{user_id}",
                )) from None
            finally:
                current = self._connected_events.get(key)
                if current is not None and current[0] is event:
                    if current[1] == 1:
                        self._connected_events.pop(key, None)
                    else:
                        self._connected_events[key] = event, current[1] - 1
        websocket = self.adapters.get(key)
        if websocket is None:
            raise HTTPException(status_code=404, detail=render_prompt(
                await tr("messenger_bridge.errors.adapter_not_connected"), adapter=f"{platform}:{user_id}",
            ))
        echo_id = str(uuid.uuid4())
        wire = json.dumps({"action": action, "params": params, "echo": echo_id})
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending_responses[echo_id] = _PendingResponse(key, websocket, future)
        try:
            await websocket.send_text(wire)
            return await asyncio.wait_for(future, timeout=self.response_timeout)
        except asyncio.TimeoutError as exc:
            if not action.startswith("get_"):
                raise DeliveryOutcomeUnknown("OneBot action outcome is uncertain; no automatic resend") from exc
            return {"status": "failed", "msg": "timeout"}
        except Exception as exc:
            if not action.startswith("get_"):
                raise DeliveryOutcomeUnknown("OneBot action outcome is uncertain; no automatic resend") from exc
            raise
        finally:
            self.pending_responses.pop(echo_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()


hub = MessengerHub()
