import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import MessengerHub


@pytest.mark.asyncio
async def test_old_disconnect_preserves_replacement_socket():
    hub = MessengerHub()
    old = SimpleNamespace(accept=AsyncMock())
    new = SimpleNamespace(accept=AsyncMock())
    await hub.register("qq", "42", old)
    await hub.register("qq", "42", new)
    hub.unregister("qq", "42", old)
    assert hub.adapters["qq:42"] is new
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
