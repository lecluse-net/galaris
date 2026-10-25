import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import MessengerHub
from app.messenger.interface import DeliveryOutcomeUnknown


@pytest.mark.asyncio
async def test_old_disconnect_preserves_replacement_socket():
    hub = MessengerHub()
    old = SimpleNamespace(accept=AsyncMock(), close=AsyncMock())
    new = SimpleNamespace(accept=AsyncMock(), close=AsyncMock())
    await hub.register("qq", "42", old)
    await hub.register("qq", "42", new)
    hub.unregister("qq", "42", old)
    assert hub.is_current("qq", "42", new)
    hub.unregister("qq", "42", new)
    assert not hub.adapters


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("disconnected"), asyncio.CancelledError()])
async def test_send_failure_releases_pending_response(failure):
    hub = MessengerHub()
    socket = SimpleNamespace(accept=AsyncMock(), send_text=AsyncMock(side_effect=failure))
    await hub.register("qq", "42", socket)
    with pytest.raises(type(failure)):
        await hub.call("qq", "42", "get_status", {})
    assert not hub.pending_responses


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["timeout", "disconnect", "replace"])
async def test_uncertain_send_is_not_successful_or_retried(end):
    import json

    hub = MessengerHub(response_timeout=0.01)
    sent = asyncio.Event()

    async def send(raw):
        sent.set()

    socket = SimpleNamespace(accept=AsyncMock(), close=AsyncMock(), send_text=AsyncMock(side_effect=send))
    await hub.register("qq", "700", socket, connection_id=19, token="synthetic")
    call = asyncio.create_task(hub.call("qq", "700", "send_private_msg", {"user_id": "420", "message": "hello"},
        connection_id=19, token="synthetic"))
    await sent.wait()
    if end == "disconnect":
        hub.unregister("qq", "700", socket, connection_id=19, token="synthetic")
    elif end == "replace":
        await hub.register("qq", "700", SimpleNamespace(accept=AsyncMock()), connection_id=19, token="synthetic")
    with pytest.raises(DeliveryOutcomeUnknown):
        await call
    socket.send_text.assert_awaited_once()
    assert not hub.pending_responses


@pytest.mark.asyncio
async def test_cancelled_connection_waiter_does_not_abandon_other_callers():
    hub = MessengerHub(connection_timeout=1)
    socket = SimpleNamespace(accept=AsyncMock(), send_text=AsyncMock())
    first = asyncio.create_task(hub.call("qq", "700", "get_status", {}))
    second = asyncio.create_task(hub.call("qq", "700", "get_status", {}))
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert len(hub._connected_events) == 1
    await hub.register("qq", "700", socket)
    async with asyncio.timeout(1):
        while not socket.send_text.await_count:
            await asyncio.sleep(0)
    import json
    payload = json.loads(socket.send_text.await_args.args[0])
    hub.resolve_response(socket, {"echo": payload["echo"], "status": "ok", "retcode": 0, "data": {}})
    assert (await second)["status"] == "ok"
    assert not hub._connected_events and not hub.pending_responses
