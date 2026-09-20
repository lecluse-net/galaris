import json
from typing import Any

import pytest

from bridge.nextcloud.signaling import (
    TalkSignalingRoom,
    build_hello_message,
    build_resume_hello_message,
    build_room_join_message,
    normalize_hpb_url,
)


class _FakeClient:
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.refresh_calls = 0
        self.settings = settings or {"helloAuthParams": {"2.0": {"token": "jwt"}}}

    async def join_call(self, token: str) -> dict[str, Any]:
        return {"sessionId": f"nc-{token}"}

    async def get_signaling_settings(self, token: str = "") -> dict[str, Any]:
        return self.settings

    async def get_messages(self, token: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.refresh_calls += 1
        return [
            {
                "id": 42,
                "actorId": "alice",
                "actorType": "users",
                "message": "From OCS",
                "timestamp": 123,
            }
        ]


class _FakeWebSocket:
    def __init__(self, recv_messages: list[dict[str, Any]]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._recv = [json.dumps(message) for message in recv_messages]
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._recv:
            raise RuntimeError("no more messages")
        return self._recv.pop(0)

    async def close(self) -> None:
        self.closed = True


def test_build_hello_message_adds_client_features() -> None:
    hello = build_hello_message(
        "https://cloud.example",
        {"helloAuthParams": {"2.0": {"token": "jwt"}}},
        client_features=("chat-relay",),
    )

    assert hello["hello"]["auth"]["params"] == {"token": "jwt"}
    assert hello["hello"]["features"] == ["chat-relay"]


def test_build_resume_hello_message_matches_android() -> None:
    assert build_resume_hello_message(
        "resume-123",
        client_features=("chat-relay",),
    ) == {
        "type": "hello",
        "hello": {
            "version": "1.0",
            "resumeid": "resume-123",
            "features": ["chat-relay"],
        },
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://hpb.example/standalone-signaling", "wss://hpb.example/standalone-signaling/spreed"),
        ("wss://hpb.example/custom/", "wss://hpb.example/custom/spreed"),
        ("wss://hpb.example/custom/spreed", "wss://hpb.example/custom/spreed"),
    ],
)
def test_normalize_hpb_url_uses_spreed_endpoint(raw: str, expected: str) -> None:
    assert normalize_hpb_url(raw) == expected


def test_build_room_join_message_preserves_federation_settings() -> None:
    message = build_room_join_message(
        "local-room",
        "nc-session",
        {
            "federation": {
                "signaling": "wss://remote.example/standalone-signaling/spreed",
                "url": "https://remote.example",
                "roomid": "remote-room",
                "invite": [{"userid": "alice", "sessionid": "abc"}],
                "unused": "",
            }
        },
    )

    assert message == {
        "type": "room",
        "room": {
            "roomid": "local-room",
            "sessionid": "nc-session",
            "federation": {
                "signaling": "wss://remote.example/standalone-signaling/spreed",
                "url": "https://remote.example",
                "roomid": "remote-room",
                "invite": [{"userid": "alice", "sessionid": "abc"}],
            },
        },
    }


def test_build_room_join_message_maps_android_federation_settings() -> None:
    message = build_room_join_message(
        "local-room",
        "nc-session",
        {
            "federation": {
                "server": "https://remote.example/signaling",
                "nextcloudServer": "https://remote.example/nextcloud/",
                "roomId": "remote-room",
                "helloAuthParams": {"token": "federation-token"},
            }
        },
    )

    assert message["room"]["federation"] == {
        "signaling": "https://remote.example/signaling",
        "url": (
            "https://remote.example/nextcloud"
            "/ocs/v2.php/apps/spreed/api/v3/signaling/backend"
        ),
        "roomid": "remote-room",
        "token": "federation-token",
    }


@pytest.mark.asyncio
async def test_connect_sends_hello_then_joins_room(monkeypatch: pytest.MonkeyPatch) -> None:
    import websockets

    connect_urls: list[str] = []
    ws = _FakeWebSocket([
        {"type": "welcome"},
        {"type": "hello", "hello": {"sessionid": "sig-session"}},
        {"type": "room", "room": {"roomid": "abc"}},
    ])

    async def fake_connect(url: str, *args: Any, **kwargs: Any) -> _FakeWebSocket:
        connect_urls.append(url)
        return ws

    monkeypatch.setattr(websockets, "connect", fake_connect)

    room = TalkSignalingRoom(
        "wss://hpb.example/spreed",
        _FakeClient({
            "server": "wss://room-hpb.example/standalone-signaling/spreed",
            "helloAuthParams": {"2.0": {"token": "jwt-abc"}},
        }),
        "abc",
        "bot",
        "https://cloud.example",
        on_raw=lambda token, raw: None,  # type: ignore[arg-type]
    )

    await room._connect()
    await room.stop()

    assert connect_urls == ["wss://room-hpb.example/standalone-signaling/spreed"]
    assert ws.sent[0]["type"] == "hello"
    assert ws.sent[0]["hello"]["features"] == ["chat-relay"]
    assert ws.sent[1] == {
        "type": "room",
        "room": {"roomid": "abc", "sessionid": "nc-abc"},
    }
    assert ws.closed is True


@pytest.mark.asyncio
async def test_handle_dispatches_room_events() -> None:
    events: list[dict[str, Any]] = []

    async def on_event(token: str, event: dict[str, Any]) -> None:
        events.append({"token": token, **event})

    room = TalkSignalingRoom(
        "wss://hpb.example/spreed",
        _FakeClient(),
        "room1",
        "bot",
        "https://cloud.example",
        on_raw=lambda token, raw: None,  # type: ignore[arg-type]
        on_event=on_event,
    )

    await room._handle(json.dumps({
        "type": "event",
        "event": {
            "target": "participants",
            "type": "update",
            "update": [
                {
                    "roomid": "room1",
                    "users": [{"userid": "alice", "inCall": True, "flags": 3}],
                }
            ],
        },
    }))

    assert events == [
        {
            "token": "room1",
            "target": "participants",
            "type": "update",
            "update": [
                {
                    "roomid": "room1",
                    "users": [{"userid": "alice", "inCall": True, "flags": 3}],
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_handle_dispatches_chat_relay_comments_and_refresh() -> None:
    raws: list[dict[str, Any]] = []
    refreshes: list[str] = []

    async def on_raw(token: str, raw: dict[str, Any]) -> None:
        raws.append({"token": token, **raw})

    async def on_refresh(token: str) -> None:
        refreshes.append(token)

    room = TalkSignalingRoom(
        "wss://hpb.example/spreed",
        _FakeClient(),
        "room1",
        "bot",
        "https://cloud.example",
        on_raw=on_raw,
        on_refresh=on_refresh,
    )

    await room._handle(json.dumps({
        "type": "event",
        "event": {
            "target": "room",
            "type": "message",
            "message": {
                "data": {
                    "type": "chat",
                    "chat": {
                        "comment": {
                            "id": 1,
                            "actorId": "alice",
                            "actorType": "users",
                            "message": "Hello",
                            "timestamp": 123,
                        }
                    },
                }
            },
        },
    }))
    await room._handle(json.dumps({
        "type": "message",
        "message": {
            "data": {
                "type": "chat",
                "chat": {
                    "comments": [
                        {
                            "id": 2,
                            "actorId": "bob",
                            "actorType": "users",
                            "message": "Hello",
                            "timestamp": 124,
                        }
                    ]
                },
            }
        },
    }))
    await room._handle(json.dumps({
        "type": "message",
        "message": {"data": {"type": "chat", "chat": {"refresh": True}}},
    }))

    assert [(raw["id"], raw["token"]) for raw in raws] == [(1, "room1"), (2, "room1")]
    assert refreshes == ["room1"]


@pytest.mark.asyncio
async def test_catch_up_backlog_triggers_refresh() -> None:
    """On connection, catch up with the posted backlog through ``on_refresh`` (OCS)."""
    refreshes: list[str] = []

    async def on_refresh(token: str) -> None:
        refreshes.append(token)

    room = TalkSignalingRoom(
        "wss://hpb.example/spreed",
        _FakeClient(),
        "room1",
        "bot",
        "https://cloud.example",
        on_raw=lambda token, raw: None,  # type: ignore[arg-type]
        on_refresh=on_refresh,
    )

    await room._catch_up_backlog()

    assert refreshes == ["room1"]


@pytest.mark.asyncio
async def test_catch_up_backlog_falls_back_to_ocs_dispatch() -> None:
    """Without ``on_refresh``, fetch and dispatch recent OCS messages during catch-up."""
    raws: list[dict[str, Any]] = []

    async def on_raw(token: str, raw: dict[str, Any]) -> None:
        raws.append({"token": token, **raw})

    client = _FakeClient()
    room = TalkSignalingRoom(
        "wss://hpb.example/spreed",
        client,
        "room1",
        "bot",
        "https://cloud.example",
        on_raw=on_raw,
    )

    await room._catch_up_backlog()

    assert client.refresh_calls == 1
    assert [(raw["id"], raw["token"]) for raw in raws] == [(42, "room1")]
