from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import MessageSender, OneBotMessage
from bridge.one_bot import router


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
