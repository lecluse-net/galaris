from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import MessageSender, OneBotMessage
from bridge.one_bot import router


class AdapterSocket:
    def __init__(self):
        self.headers = {"authorization": "Bearer synthetic-token"}
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.accepted = asyncio.Event()
        self.closed = None

    async def accept(self):
        self.accepted.set()

    async def receive_text(self):
        value = await self.incoming.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def send_text(self, value):
        self.outgoing.put_nowait(json.loads(value))

    async def close(self, code=1000):
        self.closed = code


@pytest.mark.asyncio
@pytest.mark.parametrize("other_bot", ["701", "700"])
async def test_action_response_cannot_cross_agent_connections(monkeypatch, other_bot):
    import app.messenger as messenger_module
    from bridge.one_bot.client import MessengerHub, OneBot

    hub = MessengerHub()
    monkeypatch.setattr(router, "hub", hub)
    monkeypatch.setattr("bridge.one_bot.client.hub", hub)
    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _: True)
    monkeypatch.setattr(router, "_authenticate_connection", AsyncMock(side_effect=[(19, 3), (20, 4)]))
    monkeypatch.setattr(messenger_module, "resolve_messenger_configuration", AsyncMock(return_value=SimpleNamespace(
        connection_id=19, tool_id=3, agent_id=7, settings={"platform": "qq"},
        params={"user_id": "700", "token": "synthetic-token"},
    )))
    owner, other = AdapterSocket(), AdapterSocket()
    endpoints = [asyncio.create_task(router.onebot_endpoint(owner, "qq", "700"))]
    call = None
    try:
        await asyncio.wait_for(owner.accepted.wait(), 1)
        client = await OneBot.from_connection_id(19)
        call = asyncio.create_task(client.get_group_list())
        request = await asyncio.wait_for(owner.outgoing.get(), 1)
        endpoints.append(asyncio.create_task(router.onebot_endpoint(other, "qq", other_bot)))
        await asyncio.wait_for(other.accepted.wait(), 1)
        forged = {"echo": request["echo"], "status": "ok", "retcode": 0, "data": []}
        other.incoming.put_nowait(json.dumps(forged))
        await asyncio.sleep(0.01)
        assert not call.done(), "Another agent's adapter completed this request"
        owner.incoming.put_nowait(json.dumps(forged))
        assert await asyncio.wait_for(call, 1) == forged
    finally:
        for task in [*endpoints, *([call] if call is not None else [])]:
            task.cancel()
        await asyncio.gather(*endpoints, *([call] if call is not None else []), return_exceptions=True)


def _event() -> OneBotMessage:
    return OneBotMessage(
        time=1,
        self_id="bot-42",
        post_type="message",
        message_type="private",
        message_id="message-1",
        user_id="human-1",
        message="hello",
        raw_message="hello",
        sender=MessageSender(user_id="human-1", nickname="Human"),
    )


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield None


@pytest.mark.asyncio
async def test_router_dispatches_only_one_exact_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module
    from app.connection import connection_service
    from core.database import database

    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _kind: True)
    monkeypatch.setattr(
        messenger_module,
        "messaging_tool_records",
        AsyncMock(return_value=[SimpleNamespace(id=3)]),
    )
    monkeypatch.setattr(database, "get_db_session", _db_session)
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_param",
        AsyncMock(
            return_value=[SimpleNamespace(id=19, active=True, agent_id=7)]
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(router, "dispatch_incoming", dispatch)

    await router._dispatch_onebot_event(  # pyright: ignore[reportPrivateUsage]
        "qq",
        _event(),
        connected_user_id="bot-42",
    )

    dispatch.assert_awaited_once()
    message = dispatch.await_args.args[0]
    assert message.recipient is not None
    assert message.recipient.connection_id == 19
    assert message.room is not None and message.room.id == "direct:human-1"


@pytest.mark.asyncio
async def test_router_fails_closed_for_ambiguous_bot_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module
    from app.connection import connection_service
    from core.database import database

    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _kind: True)
    monkeypatch.setattr(
        messenger_module,
        "messaging_tool_records",
        AsyncMock(return_value=[SimpleNamespace(id=3)]),
    )
    monkeypatch.setattr(database, "get_db_session", _db_session)
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_param",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=19, active=True, agent_id=7),
                SimpleNamespace(id=20, active=True, agent_id=8),
            ]
        ),
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(router, "dispatch_incoming", dispatch)

    await router._dispatch_onebot_event(  # pyright: ignore[reportPrivateUsage]
        "qq",
        _event(),
        connected_user_id="bot-42",
    )

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_rejects_event_from_another_socket_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module

    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _kind: True)
    dispatch = AsyncMock()
    monkeypatch.setattr(router, "dispatch_incoming", dispatch)

    await router._dispatch_onebot_event(  # pyright: ignore[reportPrivateUsage]
        "qq",
        _event(),
        connected_user_id="another-bot",
    )

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", ["null", "[]", '"text"', '{"echo":[]}'])
async def test_malformed_frames_do_not_terminate_the_adapter(monkeypatch, frame):
    import app.messenger as messenger_module
    from fastapi import WebSocketDisconnect

    socket = SimpleNamespace(headers={"authorization": "Bearer synthetic-token"},
        accept=AsyncMock(), close=AsyncMock(),
        receive_text=AsyncMock(side_effect=[frame, WebSocketDisconnect()]))
    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _: True)
    monkeypatch.setattr(router, "_authenticate_connection", AsyncMock(return_value=(19, 3)))
    await router.onebot_endpoint(socket, "qq", "700")
    assert socket.receive_text.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["API", "Event"])
async def test_split_role_socket_is_refused_explicitly(monkeypatch, role):
    import app.messenger as messenger_module
    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _: True)
    socket = AdapterSocket()
    socket.headers["x-client-role"] = role
    await router.onebot_endpoint(socket, "qq", "700")
    assert socket.closed == 1008 and not socket.accepted.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["overflow", "cancel_during_drain"])
async def test_event_worker_is_bounded_and_cleaned_up(monkeypatch, ending):
    import app.messenger as messenger_module
    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _: True)
    monkeypatch.setattr(router, "_authenticate_connection", AsyncMock(return_value=(19, 3)))
    monkeypatch.setattr(router, "_EVENT_DRAIN_TIMEOUT", 0.01 if ending == "overflow" else 5.0)
    entered = asyncio.Event()
    stopped = asyncio.Event()
    workers = []

    async def stalled(*args, **kwargs):
        workers.append(asyncio.current_task())
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(router, "_dispatch_onebot_event", stalled)
    socket = AdapterSocket()
    task = asyncio.create_task(router.onebot_endpoint(socket, "qq", "700"))
    try:
        await socket.accepted.wait()
        socket.incoming.put_nowait(json.dumps(_event().model_dump()))
        await asyncio.wait_for(entered.wait(), 1)
        if ending == "overflow":
            for _ in range(100):
                socket.incoming.put_nowait(json.dumps(_event().model_dump()))
            await asyncio.wait_for(task, 1)
            assert socket.closed == 1013
        else:
            from fastapi import WebSocketDisconnect
            socket.incoming.put_nowait(WebSocketDisconnect())
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
        assert stopped.is_set()
    finally:
        task.cancel()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.asyncio
async def test_last_received_event_is_drained_before_disconnect_cleanup(monkeypatch):
    import app.messenger as messenger_module
    from fastapi import WebSocketDisconnect

    monkeypatch.setattr(messenger_module, "is_kind_enabled", lambda _: True)
    monkeypatch.setattr(router, "_authenticate_connection", AsyncMock(return_value=(19, 3)))
    dispatch = AsyncMock()
    monkeypatch.setattr(router, "_dispatch_onebot_event", dispatch)
    socket = AdapterSocket()
    socket.incoming.put_nowait(json.dumps(_event().model_dump()))
    socket.incoming.put_nowait(WebSocketDisconnect())
    await router.onebot_endpoint(socket, "qq", "700")
    dispatch.assert_awaited_once()
