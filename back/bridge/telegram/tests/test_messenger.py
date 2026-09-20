from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bridge.telegram.client import TelegramClient
from bridge.telegram.messenger import TelegramMessenger, _chunks, telegram_to_message
from bridge.telegram.schemas import TelegramConnectionConfig, parse_id_set


def _native_message(**overrides: Any) -> SimpleNamespace:
    sender = SimpleNamespace(id=42, full_name="Alice", is_bot=False)
    chat = SimpleNamespace(
        id=-100,
        type="supergroup",
        title="Galaris",
        full_name=None,
        username=None,
    )
    values: dict[str, Any] = {
        "message_id": 7,
        "from_user": sender,
        "chat": chat,
        "text": "@galaris_bot bonjour",
        "caption": None,
        "photo": (),
        "document": None,
        "audio": None,
        "voice": None,
        "video": None,
        "reply_to_message": None,
        "media_group_id": None,
        "date": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _messenger(config: TelegramConnectionConfig) -> TelegramMessenger:
    self_user = SimpleNamespace(
        id=99,
        username="galaris_bot",
        full_name="Galaris",
    )
    return TelegramMessenger(
        client=SimpleNamespace(),  # type: ignore[arg-type]
        config=config,
        self_user=self_user,  # type: ignore[arg-type]
        tool_id=3,
        connection_id=8,
    )


def test_mapping_uses_chat_scoped_id_and_combines_album() -> None:
    photo = SimpleNamespace(
        file_id="file-1",
        file_unique_id="unique-1",
        file_size=123,
    )
    first = _native_message(photo=(photo,), media_group_id="album")
    second = _native_message(
        message_id=8,
        text=None,
        photo=(photo,),
        media_group_id="album",
    )
    self_user = SimpleNamespace(id=99, username="galaris_bot", full_name="Galaris")

    message = telegram_to_message(
        [first, second],  # type: ignore[list-item]
        self_user=self_user,  # type: ignore[arg-type]
        tool_id=3,
        connection_id=8,
    )

    assert message.id == "-100:7"
    assert message.platform == "telegram"
    assert len(message.attachments) == 2
    assert message.recipient is not None and message.recipient.connection_id == 8


def test_allowlists_are_restrictive_and_group_requires_mention() -> None:
    denied = _messenger(TelegramConnectionConfig(bot_token="x"))
    assert not denied._authorized(_native_message())  # pyright: ignore[reportPrivateUsage]

    allowed = _messenger(
        TelegramConnectionConfig(
            bot_token="x",
            allowed_chat_ids="-100",
            require_group_mention=True,
        )
    )
    assert allowed._authorized(_native_message())  # pyright: ignore[reportPrivateUsage]
    assert not allowed._authorized(  # pyright: ignore[reportPrivateUsage]
        _native_message(text="bonjour")
    )


def test_id_parser_and_long_message_chunks() -> None:
    assert parse_id_set("42, -100\n7") == {42, -100, 7}
    parts = _chunks("word " * 2_000)
    assert "".join(parts).replace(" ", "") == ("word " * 2_000).replace(" ", "")
    assert all(len(part) <= 4_096 for part in parts)


@pytest.mark.asyncio
async def test_album_parts_are_collected_across_adjacent_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = SimpleNamespace(
        update_id=10,
        effective_message=_native_message(media_group_id="album"),
    )
    second = SimpleNamespace(
        update_id=11,
        effective_message=_native_message(message_id=8, media_group_id="album"),
    )
    client = SimpleNamespace(get_updates=AsyncMock(side_effect=[(second,), ()]))
    messenger = _messenger(TelegramConnectionConfig(bot_token="x"))
    messenger.client = client  # type: ignore[assignment]
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    updates = await messenger._settle_album_updates([first])  # type: ignore[list-item]  # pyright: ignore[reportPrivateUsage]

    assert [item.update_id for item in updates] == [10, 11]
    assert all(call.kwargs["offset"] == 10 for call in client.get_updates.await_args_list)
    assert len(messenger._group_updates(updates)) == 1  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_long_poll_http_timeout_outlives_server_poll() -> None:
    bot = SimpleNamespace(get_updates=AsyncMock(return_value=()))
    client = TelegramClient("unused", bot=bot)  # type: ignore[arg-type]

    await client.get_updates(offset=12, timeout=30)

    assert bot.get_updates.await_args.kwargs["read_timeout"] == 40.0
