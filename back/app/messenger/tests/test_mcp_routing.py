from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.messenger import mcp
from app.messenger.interface import HistoryPage, NotSupported
from app.messenger.models import (
    Capability,
    File,
    Message,
    Room,
    MessengerUser,
)
from app.tools.mcp_loader import McpToolContext


@pytest.mark.asyncio
async def test_explicit_channel_is_strict_and_never_uses_context_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import service

    messenger = type(
        "FakeMessenger",
        (),
        {
            "connection_id": 19,
            "supports": lambda _self, capability: capability is Capability.SEND,
        },
    )()
    exact_resolver = AsyncMock(return_value=messenger)
    fallback = AsyncMock()
    recipient_resolver = AsyncMock(return_value="@nicolas:example.test")
    monkeypatch.setattr(service, "messenger_for_agent_kind", exact_resolver)
    monkeypatch.setattr(mcp, "_resolve_context_messenger", fallback)
    monkeypatch.setattr(mcp, "_resolve_task_recipient_id", recipient_resolver)

    resolved, user_id = await mcp._resolve_user_delivery(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(agent_id=7, runtime="internal"),
        "Nicolas",
        "en",
        channel="telegram",
    )

    assert resolved is messenger
    assert user_id == "@nicolas:example.test"
    exact_resolver.assert_awaited_once_with(7, "telegram")
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_pinned_connection_must_keep_declared_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    monkeypatch.setattr(
        mcp,
        "_task_data",
        AsyncMock(
            return_value={
                "messenger_connection_id": 19,
                "message_platform": "matrix",
            }
        ),
    )
    from app.messenger import service

    exact_resolver = AsyncMock(
        return_value=type("FakeMessenger", (), {"kind": "telegram"})()
    )
    monkeypatch.setattr(service, "messenger_for_agent_connection", exact_resolver)

    with pytest.raises(NotSupported, match="no longer uses matrix"):
        await mcp._resolve_agent_messenger(  # pyright: ignore[reportPrivateUsage]
            7,
            "en",
            task_id,
        )

    exact_resolver.assert_awaited_once_with(7, 19)


@pytest.mark.asyncio
async def test_addressed_task_without_connection_does_not_fall_back_cross_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    monkeypatch.setattr(
        mcp,
        "_task_data",
        AsyncMock(return_value={"message_platform": "matrix"}),
    )
    from app.messenger import service

    fallback = AsyncMock()
    monkeypatch.setattr(service, "messenger_for_agent", fallback)

    with pytest.raises(NotSupported, match="cross-channel fallback is disabled"):
        await mcp._resolve_agent_messenger(  # pyright: ignore[reportPrivateUsage]
            7,
            "en",
            task_id,
        )

    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_users_exposes_exact_ids_without_contact_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import service
    from core.database import database

    local_user_id = uuid4()
    monkeypatch.setattr(
        service,
        "search_agent_users",
        AsyncMock(
            return_value=[
                (
                    19,
                    3,
                    "matrix",
                    MessengerUser(
                        id=local_user_id,
                        tool_id=3,
                        external_id="@nicolas:example.test",
                        display_name="Nicolas",
                    ),
                )
            ]
        ),
    )
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value="en"))

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(database, "get_db_session", session)

    result = await mcp.mcp_search_users(
        McpToolContext(agent_id=7, runtime="internal")
    )

    assert f"id: {local_user_id}" in result
    assert "external_id: @nicolas:example.test" in result
    assert "connection_id: 19" in result
    assert "tool_id: 3" in result
    assert "channel: matrix" in result
    assert "contact_id" not in result


@pytest.mark.asyncio
async def test_room_history_returns_structured_page_and_forwards_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    sender_id = uuid4()
    room_id = uuid4()
    file_id = uuid4()
    sender = MessengerUser(
        id=sender_id,
        tool_id=3,
        external_id="@alice:test",
        display_name="Alice",
    )
    room = Room(
        id=room_id,
        connection_id=19,
        external_id="!room:test",
        label="!room:test",
        kind="group",
        conversation_type="text",
    )
    attachment = File(
        id=file_id,
        connection_id=19,
        external_identifier="file-1",
        name="report.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        kind="document",
        remote_url="https://private.test/report.pdf",
    )
    message = Message(
        id=(message_id := uuid4()),
        connection_id=19,
        tool_id=3,
        platform="matrix",
        remote_message_id="message-7",
        direction="inbound",
        text="hello",
        reply_to="message-6",
        created_at=datetime.fromtimestamp(123, tz=timezone.utc),
    )
    message.sender = sender
    message.room = room
    message.files = [attachment]
    message.tool_code = "matrix-primary"
    history_page = AsyncMock(
        return_value=HistoryPage(
            messages=[message],
            has_more=True,
            next_cursor="next-page",
        )
    )
    messenger = type("FakeMessenger", (), {"history_page": history_page})()
    resolver = AsyncMock(return_value=messenger)
    monkeypatch.setattr(mcp, "_resolve_context_messenger", resolver)
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value="en"))

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(database, "get_db_session", session)

    result = await mcp.mcp_room_history(
        McpToolContext(agent_id=7, runtime="internal"),
        "!room:test",
        limit=50,
        cursor="previous-page",
    )

    assert isinstance(result, dict)
    assert result["room_id"] == str(room_id)
    assert result["external_room_id"] == "!room:test"
    assert result["messages"][0]["id"] == str(message_id)
    assert result["messages"][0]["external_id"] == "message-7"
    assert result["messages"][0]["sender"] == {
        "id": str(sender_id),
        "external_id": "@alice:test",
        "display_name": "Alice",
    }
    assert result["messages"][0]["attachments"] == [
        {
            "id": str(file_id),
            "uri": f"matrix-primary://!room:test/{file_id}",
            "external_identifier": "file-1",
            "name": "report.pdf",
            "mime": "application/pdf",
            "size": 12,
            "kind": "document",
        }
    ]
    assert result["page"] == {
        "limit": 50,
        "count": 1,
        "has_more": True,
        "next_cursor": "next-page",
    }
    history_page.assert_awaited_once_with(
        "!room:test",
        50,
        "previous-page",
    )


@pytest.mark.asyncio
async def test_list_rooms_returns_exact_connection_rooms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    room_id = uuid4()
    rooms = [
        Room(
            id=room_id,
            connection_id=19,
            external_id="talk-token",
            label="Projet Galaris",
            kind="group",
            conversation_type="text",
        )
    ]
    list_rooms = AsyncMock(return_value=rooms)
    messenger = type(
        "FakeMessenger",
        (),
        {"kind": "nextcloud_talk", "rooms": list_rooms},
    )()
    resolver = AsyncMock(return_value=messenger)
    monkeypatch.setattr(mcp, "_resolve_context_messenger", resolver)
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value="en"))

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(database, "get_db_session", session)
    context = McpToolContext(agent_id=7, runtime="internal", task_id=uuid4())

    result = await mcp.mcp_list_rooms(context)

    assert result == {
        "channel": "nextcloud_talk",
        "count": 1,
        "rooms": [
            {
                "id": str(room_id),
                "external_id": "talk-token",
                "label": "Projet Galaris",
                "kind": "group",
                "conversation_type": "text",
            }
        ],
    }
    resolver.assert_awaited_once_with(context, "en")
    list_rooms.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_room_send_failure_is_a_tool_error_not_a_success_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    send = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    messenger = type(
        "FakeMessenger",
        (),
        {"connection_id": 19, "send_to_room": send},
    )()
    monkeypatch.setattr(
        mcp,
        "_resolve_context_messenger",
        AsyncMock(return_value=messenger),
    )
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value="en"))

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(database, "get_db_session", session)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await mcp.mcp_room_send_message(
            McpToolContext(agent_id=7, runtime="internal", task_id=uuid4()),
            "room-1",
            "hello",
        )


@pytest.mark.asyncio
async def test_task_room_send_message_allows_two_identical_explicit_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database

    send = AsyncMock()
    messenger = type(
        "FakeMessenger",
        (),
        {"connection_id": 19, "send_to_room": send},
    )()
    monkeypatch.setattr(
        mcp,
        "_resolve_context_messenger",
        AsyncMock(return_value=messenger),
    )
    monkeypatch.setattr(mcp, "_context_language", AsyncMock(return_value="en"))

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(database, "get_db_session", session)
    context = McpToolContext(agent_id=7, runtime="internal", task_id=uuid4())

    await mcp.mcp_room_send_message(context, "room-1", "same message")
    await mcp.mcp_room_send_message(context, "room-1", "same message")

    assert send.await_count == 2
    send.assert_awaited_with("room-1", "same message")
