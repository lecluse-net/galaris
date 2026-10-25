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
from pydantic import ValidationError
from core.util import as_dict

from app.messenger.inbound import dispatch_incoming

from .client import OneBotMessage, hub
from .messenger import onebot_to_message

onebot_router = APIRouter()
_EVENT_DRAIN_TIMEOUT = 5.0


async def _dispatch_onebot_event(
    platform: str,
    event: OneBotMessage,
    *,
    connected_user_id: str | None = None,
    connection_id: int | None = None,
    tool_id: int | None = None,
    token: str | None = None,
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
    if event.user_id == event.self_id:
        return
    if connection_id is not None and tool_id is not None:
        from core.database import get_db_session
        from app.messenger import resolve_messenger_configuration

        async with get_db_session():
            try:
                resolved = await resolve_messenger_configuration(connection_id, expected_service="one_bot")
            except ValueError:
                return
            if (resolved.tool_id != tool_id or resolved.settings.get("platform") != platform
                    or str(resolved.params.get("user_id") or "") != event.self_id
                    or (token is not None and not hmac.compare_digest(
                        token.encode(), str(resolved.params.get("token") or "").encode(),
                    ))):
                return
        await dispatch_incoming(
            onebot_to_message(event, tool_id, connection_id, agent_id=resolved.agent_id)
        )
        return
    matches: dict[int, tuple[int, Any]] = {}
    try:
        from core.database import get_db_session
        from app.messenger import messaging_tool_records

        async with get_db_session():
            from app.connection import connection_service

            for record in await messaging_tool_records("one_bot"):
                config = cast(dict[str, Any], getattr(record, "messenger_config", None) or {})
                if as_dict(config.get("settings")).get("platform", platform) != platform:
                    continue
                param_map = cast(dict[str, Any], config.get("param_map") or {})
                connections = await connection_service.get_connections_by_param(
                    tool_id=int(record.id),
                    param_name=str(param_map.get("user_id") or "user_id"),
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
    connection_id, (tool_id, connection) = next(iter(matches.items()))
    await dispatch_incoming(onebot_to_message(event, tool_id, connection_id, agent_id=connection.agent_id))


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
                try:
                    resolved = await resolve_messenger_configuration(
                        int(connection.id), expected_service="one_bot",
                    )
                except ValueError:
                    logger.warning("OneBot invalid connection configuration connection={}", connection.id)
                    continue
                expected_token = str(resolved.params.get("token") or "")
                expected_platform = resolved.settings.get("platform", "")
                if (
                    expected_platform == platform
                    and expected_token
                    and hmac.compare_digest(token.encode(), expected_token.encode())
                ):
                    matches.append((int(connection.id), int(record.id)))
    return matches[0] if len(matches) == 1 else None


@onebot_router.websocket("/ws/onebot/{platform}/{user_id}")
async def onebot_endpoint(websocket: WebSocket, platform: str, user_id: str) -> None:
    from app.messenger import is_kind_enabled

    if not is_kind_enabled("one_bot"):
        await websocket.close(code=1008)
        return
    role = websocket.headers.get("x-client-role", "Universal").lower()
    if role != "universal":
        await websocket.close(code=1008)
        return
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
    authenticated = await _authenticate_connection(platform, user_id, token) if token else None
    if authenticated is None:
        await websocket.close(code=1008)
        return
    connection_id, tool_id = authenticated
    header_self_id = str(websocket.headers.get("x-self-id") or "").strip()
    if header_self_id and header_self_id != user_id:
        await websocket.close(code=1008)
        return
    await hub.register(platform, user_id, websocket, connection_id=connection_id, token=token)
    events: asyncio.Queue[OneBotMessage] = asyncio.Queue(maxsize=64)
    drain_events = False

    async def consume_events() -> None:
        while True:
            event = await events.get()
            try:
                if drain_events or hub.is_current(platform, user_id, websocket, connection_id=connection_id, token=token):
                    await _dispatch_onebot_event(
                        platform, event, connected_user_id=user_id,
                        connection_id=connection_id, tool_id=tool_id, token=token,
                    )
            except Exception as exc:
                logger.warning("OneBot admission failed connection={} error={}", connection_id, type(exc).__name__)
            finally:
                events.task_done()

    # Admission may itself call the adapter. Keep the reader free to resolve API
    # responses while a bounded, ordered worker processes incoming observations.
    worker = asyncio.create_task(consume_events(), name=f"onebot-events:{connection_id}")
    try:
        while True:
            raw_data = await websocket.receive_text()
            if not is_kind_enabled("one_bot") or not hub.is_current(
                platform, user_id, websocket, connection_id=connection_id, token=token,
            ):
                await websocket.close(code=1008)
                return
            if len(raw_data.encode()) > 1_048_576:
                await websocket.close(code=1009)
                return
            try:
                data: object = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            data_dict = cast(dict[str, Any], data)
            if "echo" in data_dict:
                hub.resolve_response(websocket, data_dict)
                continue
            if data_dict.get("post_type") != "message":
                continue
            try:
                event = OneBotMessage.model_validate(data_dict)
            except ValidationError:
                logger.warning("OneBot invalid event connection={}", connection_id)
                continue
            try:
                events.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("OneBot event queue full connection={}", connection_id)
                await websocket.close(code=1013)
                return
    except WebSocketDisconnect:
        pass
    finally:
        drain_events = hub.is_current(platform, user_id, websocket, connection_id=connection_id, token=token)
        hub.unregister(platform, user_id, websocket, connection_id=connection_id, token=token)
        try:
            async with asyncio.timeout(_EVENT_DRAIN_TIMEOUT):
                await events.join()
        except TimeoutError:
            logger.warning("OneBot event drain timed out connection={} pending={}", connection_id, events.qsize())
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
