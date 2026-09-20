import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ResourceClosedError

from bridge.nextcloud.messenger import NextcloudTalkMessenger


def test_to_message_preserves_receiver_connection_id() -> None:
    messenger = NextcloudTalkMessenger(
        client=None,  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    message = messenger._to_message(
        "room-token",
        {
            "id": 123,
            "actorId": "alice",
            "actorDisplayName": "Alice",
            "message": "Appelle-moi",
            "timestamp": 456,
        },
    )

    assert message.recipient is not None
    assert message.recipient.connection_id == 42
    assert message.sender is not None
    assert message.sender.connection_id == 42


@pytest.mark.asyncio
async def test_unread_counts_use_one_room_snapshot_for_requested_tokens() -> None:
    get_rooms = AsyncMock(
        return_value=[
            {"token": "room-a", "unreadMessages": 4},
            {"token": "room-b", "unreadMessages": "2"},
            {"token": "other", "unreadMessages": 99},
        ]
    )
    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_rooms=get_rooms),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    counts = await messenger.unread_counts(["room-a", "room-b"])

    assert counts == {"room-a": 4, "room-b": 2}
    get_rooms.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_mark_read_uses_the_last_displayed_talk_message() -> None:
    mark_room_as_read = AsyncMock(return_value={"success": True})
    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(mark_room_as_read=mark_room_as_read),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    await messenger.mark_read("room-token", "123")

    mark_room_as_read.assert_awaited_once_with("room-token", 123)


@pytest.mark.asyncio
async def test_mark_read_refuses_to_advance_without_a_displayed_talk_message() -> None:
    mark_room_as_read = AsyncMock(return_value={"success": True})
    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(mark_room_as_read=mark_room_as_read),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    with pytest.raises(ValueError, match="displayed numeric Talk message ID"):
        await messenger.mark_read("room-token")

    mark_room_as_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_file_path_returns_the_created_talk_message_id() -> None:
    shared_path = ""

    async def ensure_folder(_folder: str) -> None:
        return None

    async def upload_dav_file(
        _remote: str,
        _path: Path,
        _content_type: str | None,
    ) -> None:
        return None

    async def share_file_to_room(
        _room_id: str,
        path: str,
        *,
        voice_message: bool = False,
    ) -> dict[str, object]:
        nonlocal shared_path
        assert voice_message is False
        shared_path = path
        return {"id": 9}

    async def get_messages(
        _room_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        assert limit == 30
        name = Path(shared_path).name
        return [
            {
                "id": 55,
                "actorId": "bot",
                "message": "{file}",
                "timestamp": 123,
                "messageParameters": {
                    "file": {"type": "file", "id": "file-1", "name": name}
                },
            }
        ]

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(
            ensure_folder=ensure_folder,
            upload_dav_file=upload_dav_file,
            share_file_to_room=share_file_to_room,
            get_messages=get_messages,
        ),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    message = await messenger.upload_file_path(
        "room-token", Path("report.html"), "report.html"
    )

    assert message.id == "55"
    assert message.attachments[0].id == "file-1"


@pytest.mark.asyncio
async def test_file_share_fallback_never_returns_an_empty_message_id() -> None:
    async def get_messages(
        _room_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        assert limit == 30
        return []

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_messages=get_messages),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    message = await messenger._shared_file_message(
        "room-token", "/Talk/unique-report.html", "report.html", "share-42"
    )

    assert message.id == "file-share:share-42"


@pytest.mark.asyncio
async def test_file_share_history_failure_keeps_a_unique_accepted_reference() -> None:
    async def get_messages(
        _room_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        assert limit == 30
        raise RuntimeError("history temporarily unavailable")

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_messages=get_messages),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    message = await messenger._shared_file_message(
        "room-token", "/Talk/report.html", "report.html", "share-99"
    )

    assert message.id == "file-share:share-99"


@pytest.mark.asyncio
async def test_history_page_continues_to_older_talk_messages() -> None:
    calls: list[tuple[int, int]] = []

    def message(message_id: int) -> dict[str, Any]:
        return {
            "id": message_id,
            "actorId": "alice",
            "actorDisplayName": "Alice",
            "message": f"message-{message_id}",
            "timestamp": message_id,
        }

    async def get_messages_page(
        _room_id: str,
        *,
        limit: int,
        last_known_message_id: int = 0,
    ) -> tuple[list[dict[str, Any]], str | None]:
        calls.append((limit, last_known_message_id))
        if last_known_message_id == 0:
            return [message(3), message(4)], "3"
        assert last_known_message_id == 3
        return [message(1), message(2)], None

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_messages_page=get_messages_page),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    first = await messenger.history_page("room-token", limit=2)
    second = await messenger.history_page(
        "room-token",
        limit=2,
        cursor=first.next_cursor,
    )

    assert [item.id for item in first.messages] == ["3", "4"]
    assert first.has_more
    assert first.next_cursor == "3"
    assert [item.id for item in second.messages] == ["1", "2"]
    assert not second.has_more
    assert second.next_cursor is None
    assert calls == [(2, 0), (2, 3)]


@pytest.mark.asyncio
async def test_history_page_aggregates_provider_batches_up_to_500() -> None:
    calls: list[tuple[int, int]] = []

    async def get_messages_page(
        _room_id: str,
        *,
        limit: int,
        last_known_message_id: int = 0,
    ) -> tuple[list[dict[str, Any]], str | None]:
        calls.append((limit, last_known_message_id))
        if last_known_message_id == 0:
            message_ids = range(301, 501)
            cursor = "301"
        elif last_known_message_id == 301:
            message_ids = range(101, 301)
            cursor = "101"
        else:
            assert last_known_message_id == 101
            message_ids = range(1, 101)
            cursor = None
        return (
            [
                {
                    "id": message_id,
                    "actorId": "alice",
                    "message": f"message-{message_id}",
                    "timestamp": message_id,
                }
                for message_id in message_ids
            ],
            cursor,
        )

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_messages_page=get_messages_page),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )

    page = await messenger.history_page("room-token", limit=500)

    assert len(page.messages) == 500
    assert page.messages[0].id == "1"
    assert page.messages[-1].id == "500"
    assert not page.has_more
    assert page.next_cursor is None
    assert calls == [(200, 0), (200, 301), (100, 101)]


@pytest.mark.asyncio
async def test_inbound_cursor_advances_only_after_successful_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import messenger as messenger_module

    dispatch = AsyncMock(
        side_effect=[ResourceClosedError("This transaction is closed"), True]
    )
    monkeypatch.setattr(messenger_module, "dispatch_incoming", dispatch)
    messenger = NextcloudTalkMessenger(
        client=None,  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )
    messenger._last_seen["room-token"] = 122  # pyright: ignore[reportPrivateUsage]
    raw = {
        "id": 123,
        "actorId": "alice",
        "actorType": "users",
        "message": "Bonjour",
        "timestamp": 456,
    }

    with pytest.raises(ResourceClosedError, match="transaction is closed"):
        await messenger._maybe_dispatch("room-token", raw)  # pyright: ignore[reportPrivateUsage]

    assert messenger._last_seen["room-token"] == 122  # pyright: ignore[reportPrivateUsage]
    await messenger._maybe_dispatch("room-token", raw)  # pyright: ignore[reportPrivateUsage]
    assert messenger._last_seen["room-token"] == 123  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_polling_restarts_a_completed_room_worker() -> None:
    calls = 0

    async def get_rooms() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise asyncio.CancelledError
        return [{"token": "room-token"}]

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_rooms=get_rooms),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )
    messenger.room_discovery_interval = 0
    poll_room = AsyncMock(return_value=None)
    messenger._poll_room = poll_room  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await messenger._listen_polling()  # pyright: ignore[reportPrivateUsage]

    assert poll_room.await_count == 2
    assert all(call.kwargs["process_existing"] is True for call in poll_room.await_args_list)


@pytest.mark.asyncio
async def test_polling_ignores_archived_rooms() -> None:
    calls = 0
    listened: list[str] = []

    async def get_rooms() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise asyncio.CancelledError
        return [
            {"token": "active-room", "isArchived": False},
            {"token": "archived-room", "isArchived": True},
        ]

    async def poll_room(token: str, process_existing: bool = False) -> None:
        del process_existing
        listened.append(token)

    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(get_rooms=get_rooms),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )
    messenger.room_discovery_interval = 0
    messenger._poll_room = poll_room  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await messenger._listen_polling()  # pyright: ignore[reportPrivateUsage]

    assert listened == ["active-room"]


@pytest.mark.asyncio
async def test_signaling_stops_a_room_when_it_becomes_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import messenger as messenger_module

    created: list[str] = []
    stopped: list[str] = []

    class FakeTalkSignalingRoom:
        def __init__(self, **kwargs: Any) -> None:
            self.room_token = str(kwargs["room_token"])
            created.append(self.room_token)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            stopped.append(self.room_token)

    calls = 0

    async def get_rooms() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                {"token": "active-room", "isArchived": False},
                {"token": "already-archived", "isArchived": True},
            ]
        if calls == 2:
            return [
                {"token": "active-room", "isArchived": True},
                {"token": "already-archived", "isArchived": True},
            ]
        raise asyncio.CancelledError

    monkeypatch.setattr(messenger_module, "TalkSignalingRoom", FakeTalkSignalingRoom)
    messenger = NextcloudTalkMessenger(
        client=SimpleNamespace(
            base_url="https://cloud.test",
            get_rooms=get_rooms,
        ),  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
        inbound="signaling",
        inbound_options={"signaling_url": "wss://hpb.test"},
    )
    messenger.room_discovery_interval = 0

    async def seed_baselines() -> None:
        return None

    messenger._seed_baselines = seed_baselines  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await messenger._listen_signaling()  # pyright: ignore[reportPrivateUsage]

    assert created == ["active-room"]
    assert stopped == ["active-room"]


@pytest.mark.asyncio
async def test_from_connection_id_reads_runtime_and_connection_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import messenger as messenger_module
    from core.params.runtime_settings import runtime_settings

    async def resolve(connection_id: int) -> SimpleNamespace:
        assert connection_id == 42
        return SimpleNamespace(
            base_url="https://cloud.test",
            login="bot",
            password="app-password",
            self_id="bot-user",
            tool_id=7,
        )

    monkeypatch.setattr(messenger_module, "resolve_nextcloud_connection", resolve)
    monkeypatch.setattr(runtime_settings, "MESSENGER_NEXTCLOUD_TALK_INBOUND", "polling")
    monkeypatch.setattr(runtime_settings, "MESSENGER_NEXTCLOUD_TALK_HPB_URL", "")

    messenger = await NextcloudTalkMessenger.from_connection_id(42)

    assert messenger.client.base_url == "https://cloud.test"
    assert messenger.client.login == "bot"
    assert messenger.client.password == "app-password"


def _messenger_for_rooms(
    rooms: list[dict[str, Any]],
    participants_by_token: dict[str, list[dict[str, Any]]],
    created: dict[str, Any] | None = None,
) -> NextcloudTalkMessenger:
    async def get_rooms() -> list[dict[str, Any]]:
        return rooms

    async def get_room_participants(token: str) -> list[dict[str, Any]]:
        return participants_by_token.get(token, [])

    async def create_conversation(
        invitees: list[str], room_type: int, room_name: str | None = None
    ) -> dict[str, Any]:
        return created or {"token": "t-created", "type": 1, "displayName": invitees[0]}

    client = SimpleNamespace(
        get_rooms=get_rooms,
        get_room_participants=get_room_participants,
        create_conversation=create_conversation,
    )
    messenger = NextcloudTalkMessenger(
        client=client,  # type: ignore[arg-type]
        tool_id=7,
        self_id="bot",
        connection_id=42,
    )
    return messenger


_PAIR = [
    {"actorId": "alice", "actorType": "users"},
    {"actorId": "bot", "actorType": "users"},
]


@pytest.mark.asyncio
async def test_ensure_direct_room_ignores_archived_and_picks_most_recent() -> None:
    rooms = [
        # Archived yet most active: it must be ignored completely.
        {"token": "t-archived", "type": 1, "isArchived": True, "lastActivity": 9000},
        {"token": "t-old", "type": 1, "lastActivity": 100},
        {"token": "t-recent", "type": 1, "lastActivity": 500},
    ]
    participants = {"t-old": _PAIR, "t-recent": _PAIR, "t-archived": _PAIR}
    messenger = _messenger_for_rooms(rooms, participants)

    room = await messenger.ensure_direct_room("alice")

    # Most recently used direct room (highest lastActivity among non-archived rooms).
    assert room.id == "t-recent"


@pytest.mark.asyncio
async def test_ensure_direct_room_prefers_two_person_group_with_latest_activity() -> None:
    rooms = [
        {"token": "t-direct", "type": 1, "lastActivity": 100},
        # Two-person group room where the pair last talked: it must win.
        {"token": "t-group-pair", "type": 2, "lastActivity": 8000},
        # Group room with a third human, even more recent: never selected.
        {"token": "t-group-crowd", "type": 2, "lastActivity": 9500},
    ]
    participants = {
        "t-direct": _PAIR,
        "t-group-pair": _PAIR,
        "t-group-crowd": _PAIR + [{"actorId": "carol", "actorType": "users"}],
    }
    messenger = _messenger_for_rooms(rooms, participants)

    room = await messenger.ensure_direct_room("alice")

    assert room.id == "t-group-pair"


@pytest.mark.asyncio
async def test_ensure_direct_room_does_not_count_bot_attendees() -> None:
    rooms = [{"token": "t-group", "type": 2, "lastActivity": 500}]
    participants = {
        "t-group": _PAIR + [{"actorId": "helper", "actorType": "bots"}],
    }
    messenger = _messenger_for_rooms(rooms, participants)

    room = await messenger.ensure_direct_room("alice")

    assert room.id == "t-group"


@pytest.mark.asyncio
async def test_ensure_direct_room_creates_when_only_archived_remain() -> None:
    rooms = [
        {"token": "t-archived", "type": 1, "isArchived": True, "lastActivity": 9000},
    ]
    messenger = _messenger_for_rooms(rooms, {"t-archived": _PAIR})

    room = await messenger.ensure_direct_room("alice")

    assert room.id == "t-created"
