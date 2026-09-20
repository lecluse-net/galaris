from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import TimedOut, RetryAfter

from app.messenger.interface import DeliveryOutcomeUnknown
from bridge.telegram.client import TelegramClient


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["sendMessage", "sendPhoto", "sendDocument", "sendVoice"])
async def test_ambiguous_send_is_never_repeated(operation):
    call = AsyncMock(side_effect=TimedOut("accepted remotely, response lost"))
    client = TelegramClient("unused", bot=SimpleNamespace())
    with pytest.raises(DeliveryOutcomeUnknown):
        await client._retry(operation, call)
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,error", [("getUpdates", TimedOut()), ("sendMessage", RetryAfter(1))])
async def test_safe_read_or_explicit_rate_rejection_can_retry(operation, error, monkeypatch):
    monkeypatch.setattr("bridge.telegram.client.asyncio.sleep", AsyncMock())
    call = AsyncMock(side_effect=[error, "receipt"])
    client = TelegramClient("unused", bot=SimpleNamespace())
    assert await client._retry(operation, call) == "receipt"
    assert call.await_count == 2
