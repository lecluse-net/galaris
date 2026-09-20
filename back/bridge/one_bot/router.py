"""
OneBot reverse-WebSocket endpoint. Adapters such as Napcat and Lagrange connect
to Galaris and push events. Incoming events become canonical messages and enter
through ``app.messenger.dispatch_incoming``.

The composition root mounts this router outside ``/api``.
"""

from __future__ import annotations

import json
import asyncio
import hmac
from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.messenger.inbound import dispatch_incoming

from .client import OneBotMessage, hub
from .messenger import onebot_to_message

onebot_router = APIRouter()


async def _dispatch_onebot_event(
    platform: str,
    event: OneBotMessage,
    *,
    connected_user_id: str | None = None,
    connection_id: int | None = None,
    tool_id: int | None = None,
) -> None:
    """Resolve ``tool_id`` from the platform and deliver the canonical message.

    Tool resolution needs a dedicated database session because WebSockets do not
    own one. The inbound handler then opens its own transaction boundary.
    """
    from app.messenger import is_kind_enabled

    if not is_kind_enabled("one_bot"):
        return
    if connected_user_id is not None and str(event.self_id) != connected_user_id:
        logger.warning(
            "OneBot event ignored because self_id does not match the WebSocket identity: "
            "platform={}",
            platform,
        )
        return
    if connection_id is not None and tool_id is not None:
        await dispatch_incoming(
            onebot_to_message(event, tool_id, connection_id)
        )
        return
    matches: dict[int, tuple[int, Any]] = {}
    try:
        from core.database import get_db_session
        from app.messenger import messaging_tool_records

        async with get_db_session():
            from app.connection import connection_service

            for record in await messaging_tool_records("one_bot"):
                connections = await connection_service.get_connections_by_param(
                    tool_id=int(record.id),
                    param_name="user_id",
                    param_value=str(event.self_id),
                )
                for connection in connections:
                    if connection.active:
                        matches[int(connection.id)] = (int(record.id), connection)
    except Exception:
        logger.exception(
            "OneBot event ignored because its exact connection could not be resolved: "
            "platform={}",
            platform,
        )
        return
    if len(matches) != 1:
        logger.warning(
            "OneBot event ignored because its bot identity resolved to {} active connections: "
            "platform={}",
            len(matches),
            platform,
        )
        return
    connection_id, (tool_id, _connection) = next(iter(matches.items()))
    await dispatch_incoming(onebot_to_message(event, tool_id, connection_id))


async def _authenticate_connection(
    platform: str,
    user_id: str,
    token: str,
) -> tuple[int, int] | None:
    """Resolve and authenticate one exact Tool/Connection adapter binding."""

    from core.database import get_db_session
    from app.messenger import messaging_tool_records, resolve_messenger_configuration

    matches: list[tuple[int, int]] = []
    async with get_db_session():
        from app.connection import connection_service

        for record in await messaging_tool_records("one_bot"):
            config = cast(dict[str, Any], record.messenger_config or {})
            param_map = cast(dict[str, Any], config.get("param_map") or {})
            param_name = str(param_map.get("user_id") or "user_id")
            connections = await connection_service.get_connections_by_param(
                tool_id=int(record.id),
                param_name=param_name,
                param_value=user_id,
            )
            for connection in connections:
                if not connection.active:
                    continue
                resolved = await resolve_messenger_configuration(
                    int(connection.id),
                    expected_service="one_bot",
                )
                expected_token = str(resolved.params.get("token") or "")
                expected_platform = resolved.settings.get("platform", "")
                if (
                    expected_platform == platform
                    and expected_token
                    and hmac.compare_digest(token, expected_token)
                ):
                    matches.append((int(connection.id), int(record.id)))
    return matches[0] if len(matches) == 1 else None


@onebot_router.websocket("/ws/onebot/{platform}/{user_id}")
async def onebot_endpoint(websocket: WebSocket, platform: str, user_id: str) -> None:
    from app.messenger import is_kind_enabled

    if not is_kind_enabled("one_bot"):
        await websocket.close(code=1008)
        return
    auth_header: str | None = websocket.headers.get("authorization")
    token: str | None = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:]

    authenticated = (
        await _authenticate_connection(platform, user_id, token)
        if token
        else None
    )
    if authenticated is None:
        await websocket.close(code=1008)
        return
    connection_id, tool_id = authenticated
    header_self_id = str(websocket.headers.get("x-self-id") or "").strip()
    if header_self_id and header_self_id != user_id:
        await websocket.close(code=1008)
        return
    await hub.register(platform, user_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            if not is_kind_enabled("one_bot"):
                await websocket.close(code=1008)
                return
            try:
                data_dict: Any = json.loads(raw_data)
            except json.JSONDecodeError:
                continue

            # Response handling (Echo)
            if "echo" in data_dict:
                echo_id = data_dict["echo"]
                future = hub.pending_responses.pop(echo_id, None)
                if future and not future.done():
                    future.set_result(data_dict)
                continue

            # Incoming Message Handling with Pydantic
            if data_dict.get("post_type") == "message":
                try:
                    # Validate the OneBot payload before canonical conversion and dispatch.
                    event = OneBotMessage(**data_dict)
                    asyncio.create_task(
                        _dispatch_onebot_event(
                            platform,
                            event,
                            connected_user_id=user_id,
                            connection_id=connection_id,
                            tool_id=tool_id,
                        )
                    )
                except Exception as exc:
                    logger.warning("OneBot validation error on {}: {}", platform, exc)

    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(platform, user_id, websocket)
