import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bridge.nextcloud.call import (
    _CALL_FLAG_WITH_AUDIO,
    _CallHandle,
    TalkCall,
    _build_out_track,
    _participant_call_flags,
    _participant_has_media_stream,
    _install_turn_failure_logging,
    _send_status_data_channel_state,
    _subscriber_ice_strategy,
    _subscriber_offer_profile,
    _wait_ice_complete,
)


@pytest.mark.asyncio
async def test_outbound_track_reports_when_playback_is_drained() -> None:
    track = _build_out_track()
    await track.push(b"\x01\x00" * 960)
    drained = asyncio.create_task(track.wait_drained())
    await asyncio.sleep(0)

    assert not drained.done()

    await track.recv()
    await asyncio.wait_for(drained, timeout=1)


@pytest.mark.asyncio
async def test_initial_greeting_waits_for_inbound_pcm() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    ready = asyncio.create_task(call.wait_input_ready(handle))
    await asyncio.sleep(0)

    assert not ready.done()

    handle.inbound_ready.set()
    await asyncio.wait_for(ready, timeout=1)


@pytest.mark.parametrize(
    ("raw", "expected_flags", "has_media"),
    [
        (0, 0, False),
        (1, 1, False),
        (3, 3, True),
        (5, 5, True),
        ("3", 3, True),
        (True, 1, False),
    ],
)
def test_participant_media_requires_audio_or_video_flag(
    raw: object,
    expected_flags: int,
    has_media: bool,
) -> None:
    participant = {"inCall": raw}

    assert _participant_call_flags(participant) == expected_flags
    assert _participant_has_media_stream(participant) is has_media


def test_ice_configuration_matches_android_urls_and_uses_max_bundle() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    handle.ice_servers = call._ice_servers_from_settings(
        {
            "stunservers": [{"urls": ["stun:ice.test:3478"]}],
            "turnservers": [
                {
                    "urls": [
                        "turn:ice.test:3478?transport=udp",
                        "turn:ice.test:3478?transport=tcp",
                    ],
                    "username": "user",
                    "credential": "secret",
                }
            ],
        }
    )

    first = call._rtc_config(handle, turn_attempt=0, max_bundle=True)
    second = call._rtc_config(handle, turn_attempt=1, max_bundle=True)
    subscriber = call._rtc_config(handle, turn_attempt=0)

    assert [server.urls for server in handle.ice_servers] == [
        "stun:ice.test:3478",
        "turn:ice.test:3478?transport=udp",
        "turn:ice.test:3478?transport=tcp",
    ]
    assert first.bundlePolicy.value == "max-bundle"
    assert subscriber.bundlePolicy.value == "balanced"
    assert [server.urls for server in first.iceServers] == [
        "stun:ice.test:3478",
        "turn:ice.test:3478?transport=udp",
        "turn:ice.test:3478?transport=tcp",
    ]
    assert [server.urls for server in second.iceServers] == [
        "stun:ice.test:3478",
        "turn:ice.test:3478?transport=tcp",
        "turn:ice.test:3478?transport=udp",
    ]


@pytest.mark.asyncio
async def test_subscriber_refreshes_turn_credentials_before_gathering() -> None:
    client = SimpleNamespace(
        get_signaling_settings=AsyncMock(
            return_value={
                "turnservers": [
                    {
                        "urls": ["turn:fresh.test:3478?transport=udp"],
                        "username": "fresh-user",
                        "credential": "fresh-secret",
                    }
                ]
            }
        )
    )
    call = TalkCall(
        client=client,
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    call._room_id = "room-token"
    handle = _CallHandle()
    handle.ice_servers = call._ice_servers_from_settings(
        {
            "turnservers": [
                {
                    "urls": ["turn:join.test:3478?transport=udp"],
                    "username": "join-user",
                    "credential": "join-secret",
                }
            ]
        }
    )

    refreshed = await call._refresh_subscriber_ice_servers(handle)

    client.get_signaling_settings.assert_awaited_once_with("room-token")
    assert [server.urls for server in refreshed] == [
        "turn:fresh.test:3478?transport=udp"
    ]
    assert refreshed[0].username == "fresh-user"
    assert refreshed[0].credential == "fresh-secret"


@pytest.mark.asyncio
async def test_subscriber_uses_join_ice_credentials_when_refresh_fails() -> None:
    client = SimpleNamespace(
        get_signaling_settings=AsyncMock(side_effect=RuntimeError("unavailable"))
    )
    call = TalkCall(
        client=client,
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    call._room_id = "room-token"
    handle = _CallHandle()
    handle.ice_servers = [object()]

    refreshed = await call._refresh_subscriber_ice_servers(handle)

    assert refreshed is handle.ice_servers


@pytest.mark.asyncio
async def test_turn_failure_logging_excludes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import aioice.ice

    async def fail_candidate(*args: object, **kwargs: object) -> object:
        raise RuntimeError("allocation quota reached")

    warning = Mock()
    monkeypatch.setattr(aioice.ice, "relayed_candidate", fail_candidate)
    monkeypatch.setattr("bridge.nextcloud.call.logger.warning", warning)

    _install_turn_failure_logging()

    with pytest.raises(RuntimeError, match="allocation quota reached"):
        await aioice.ice.relayed_candidate(
            component=1,
            protocol_factory=Mock(),
            turn_server=("turn.test", 3478),
            turn_username="private-user",
            turn_password="private-password",
            turn_ssl=False,
            turn_transport="udp",
        )

    rendered = " ".join(str(value) for value in warning.call_args.args)
    assert "turn.test" in rendered
    assert "allocation quota reached" in rendered
    assert "private-user" not in rendered
    assert "private-password" not in rendered


@pytest.mark.parametrize(
    ("sdp", "retries", "expected"),
    [
        (
            "a=group:BUNDLE 0 1\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            0,
            (0, False),
        ),
        (
            "a=group:BUNDLE 0 1 2\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            0,
            (0, True),
        ),
        (
            "a=group:BUNDLE 0 1 2\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            1,
            (0, False),
        ),
        (
            "a=group:BUNDLE 0 1 2\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            2,
            (1, True),
        ),
        (
            "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
            0,
            (0, False),
        ),
    ],
)
def test_subscriber_ice_strategy_handles_browser_and_android_offers(
    sdp: str,
    retries: int,
    expected: tuple[int, bool],
) -> None:
    assert _subscriber_ice_strategy(sdp, retries) == expected


def test_subscriber_offer_profile_excludes_sensitive_sdp_values() -> None:
    profile = _subscriber_offer_profile(
        "a=group:BUNDLE audio video data\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=mid:audio\r\na=sendonly\r\na=rtcp-mux\r\n"
        "a=ice-ufrag:sensitive\r\na=candidate:private-address\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=mid:video\r\na=inactive\r\na=rtcp-mux\r\n"
        "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
        "a=mid:data\r\n"
    )

    assert profile == {
        "bundle": ["audio", "video", "data"],
        "media": [
            {
                "kind": "audio",
                "port": "9",
                "mid": "audio",
                "direction": "sendonly",
                "rtcp_mux": True,
            },
            {
                "kind": "video",
                "port": "9",
                "mid": "video",
                "direction": "inactive",
                "rtcp_mux": True,
            },
            {
                "kind": "application",
                "port": "9",
                "mid": "data",
                "direction": "",
                "rtcp_mux": False,
            },
        ],
    }


@pytest.mark.asyncio
async def test_ice_completion_cannot_be_lost_during_listener_registration() -> None:
    class Peer:
        reads = 0

        @property
        def iceGatheringState(self) -> str:
            self.reads += 1
            return "gathering" if self.reads == 1 else "complete"

        def on(self, _event: str):  # type: ignore[no-untyped-def]
            def register(callback):  # type: ignore[no-untyped-def]
                return callback

            return register

    peer = Peer()

    await _wait_ice_complete(peer)

    assert peer.reads >= 2


@pytest.mark.asyncio
async def test_local_description_is_authoritative_for_aiortc_ice_gathering() -> None:
    peer = SimpleNamespace(
        localDescription=object(),
        iceGatheringState="new",
        on=Mock(side_effect=AssertionError("listener should not be installed")),
    )

    await _wait_ice_complete(peer)

    peer.on.assert_not_called()


def test_status_data_channel_state_matches_talk_android_messages() -> None:
    channel = SimpleNamespace(readyState="open", send=Mock())

    assert _send_status_data_channel_state(channel) is True
    assert [call.args[0] for call in channel.send.call_args_list] == [
        '{"type":"audioOn"}',
        '{"type":"stoppedSpeaking"}',
        '{"type":"videoOff"}',
    ]


def test_status_data_channel_state_waits_until_channel_is_open() -> None:
    channel = SimpleNamespace(readyState="connecting", send=Mock())

    assert _send_status_data_channel_state(channel) is False
    channel.send.assert_not_called()


def test_local_status_messages_queue_and_follow_speaking_state() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()

    call._broadcast_local_data_state(handle)

    assert handle.pending_status_messages == [
        '{"type":"audioOn"}',
        '{"type":"stoppedSpeaking"}',
        '{"type":"videoOff"}',
    ]

    channel = SimpleNamespace(readyState="open", send=Mock())
    handle.out_status_channel = channel
    call._set_local_speaking(handle, True)
    call._set_local_speaking(handle, True)
    call._set_local_speaking(handle, False)

    assert [item.args[0] for item in channel.send.call_args_list] == [
        '{"type":"speaking"}',
        '{"type":"stoppedSpeaking"}',
    ]


@pytest.mark.asyncio
async def test_publisher_is_ready_before_android_sees_flags_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    timeline: list[str] = []

    async def publish(current: _CallHandle) -> None:
        timeline.append("publisher")
        current.publisher_ready.set()
        current.publisher_connected.set()

    async def join_visible(
        room_id: str,
        *,
        silent: bool,
        flags: int,
    ) -> bool:
        assert handle.publisher_ready.is_set()
        assert handle.publisher_connected.is_set()
        timeline.append("call-api")
        assert room_id == "room-token"
        assert silent is True
        assert flags == 3
        return True

    monkeypatch.setattr(call, "_publish", publish)
    monkeypatch.setattr(call, "_join_media_call_visible", join_visible)

    visible = await call._publish_before_call_api_entry(
        handle,
        "room-token",
        visible_prejoined=False,
        silent=True,
    )

    assert visible is True
    assert timeline == ["publisher", "call-api"]
    assert handle.audio_advertised_at is not None


class _FakeWebSocket:
    def __init__(self, incoming: list[dict[str, object]] | None = None) -> None:
        self.incoming = [json.dumps(item) for item in (incoming or [])]
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self.incoming:
            raise RuntimeError("no more messages")
        return self.incoming.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_signaling_messages_queue_until_connection_is_ready() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    handle.ws = _FakeWebSocket()
    message = {"type": "message", "message": {"data": {"type": "unmute"}}}

    await call._send(handle, message)

    assert handle.pending_signaling_messages == [message]
    assert handle.ws.sent == []

    handle.ws_ready.set()
    await call._flush_signaling_messages(handle)

    assert handle.pending_signaling_messages == []
    assert handle.ws.sent == [message]


@pytest.mark.asyncio
async def test_hpb_session_resume_matches_android_and_flushes_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import websockets
    from bridge.nextcloud import call as call_module

    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    old_ws = _FakeWebSocket()
    resumed_ws = _FakeWebSocket(
        [
            {
                "type": "hello",
                "hello": {
                    "sessionid": "signaling-session",
                    "resumeid": "next-resume-id",
                    "server": {"features": ["mcu", "chat-relay"]},
                },
            }
        ]
    )
    handle.ws = old_ws
    handle.hpb_url = "wss://hpb.test/spreed"
    handle.sig_session = "signaling-session"
    handle.resume_id = "resume-id"
    queued = {"type": "message", "message": {"data": {"type": "mute"}}}
    handle.pending_signaling_messages.append(queued)
    connect = AsyncMock(return_value=resumed_ws)
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(call_module, "_HPB_RESUME_DELAYS_S", (0.0,))

    assert await call._resume_signaling(handle) is True

    assert old_ws.closed is True
    connect.assert_awaited_once_with(
        "wss://hpb.test/spreed",
        subprotocols=["com.nextcloud.spreed-signaling-v1"],
    )
    assert resumed_ws.sent == [
        {
            "type": "hello",
            "hello": {
                "version": "1.0",
                "resumeid": "resume-id",
                "features": ["chat-relay"],
            },
        },
        queued,
    ]
    assert handle.resume_id == "next-resume-id"
    assert handle.ws_ready.is_set()


@pytest.mark.asyncio
async def test_remote_candidates_wait_for_matching_remote_description() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    pc = SimpleNamespace(remoteDescription=None, addIceCandidate=AsyncMock())
    handle.subs["human-session"] = pc
    handle.sub_sids["human-session"] = "subscriber-sid"

    await call._add_candidate(
        handle,
        "human-session",
        "subscriber-sid",
        None,
    )

    assert handle.pending_remote_candidates == {
        ("human-session", "subscriber-sid"): [None]
    }
    pc.remoteDescription = object()
    await call._flush_remote_candidates(
        handle,
        "human-session",
        "subscriber-sid",
        pc,
    )

    pc.addIceCandidate.assert_awaited_once_with(None)
    assert handle.pending_remote_candidates == {}


@pytest.mark.asyncio
async def test_screen_offer_cannot_replace_voice_subscriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    handle.ws = _FakeWebSocket(
        [
            {
                "type": "message",
                "message": {
                    "sender": {"sessionid": "human-session"},
                    "data": {
                        "type": "offer",
                        "roomType": "screen",
                        "sid": "screen-sid",
                        "payload": {"sdp": "screen-offer"},
                    },
                },
            },
            {"type": "bye", "bye": {}},
        ]
    )
    on_remote_offer = AsyncMock()
    monkeypatch.setattr(call, "_on_remote_offer", on_remote_offer)

    await call._signaling_loop_inner(handle)

    on_remote_offer.assert_not_awaited()
    assert handle.call_ended.is_set()


@pytest.mark.asyncio
async def test_all_participants_disconnected_ends_call_and_closes_subscribers() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    subscriber = SimpleNamespace(close=AsyncMock())
    handle.subs["human-session"] = subscriber
    handle.ws = _FakeWebSocket(
        [
            {
                "type": "event",
                "event": {
                    "target": "participants",
                    "type": "update",
                    "update": {"all": True, "incall": 0},
                },
            },
            {"type": "bye", "bye": {}},
        ]
    )

    await call._signaling_loop_inner(handle)

    assert handle.call_ended.is_set()
    assert handle.subs == {}
    subscriber.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_participants_update_without_incall_is_ignored() -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    subscriber = SimpleNamespace(close=AsyncMock())
    handle.subs["human-session"] = subscriber
    handle.ws = _FakeWebSocket(
        [
            {
                "type": "event",
                "event": {
                    "target": "participants",
                    "type": "update",
                    "update": {"all": True},
                },
            },
            {"type": "bye", "bye": {}},
        ]
    )

    await call._signaling_loop_inner(handle)

    subscriber.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_audio_permission_matches_android() -> None:
    client = SimpleNamespace(
        get_rooms=AsyncMock(
            return_value=[{"token": "room-token", "permissions": 1}]
        )
    )
    call = TalkCall(
        client=client,
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )

    with pytest.raises(PermissionError, match="publish audio|publier de l.audio"):
        await call._assert_can_publish_audio("room-token")

    client.get_rooms.return_value = [
        {"token": "room-token", "permissions": 16}
    ]
    await call._assert_can_publish_audio("room-token")
    client.get_rooms.return_value = [
        {"token": "room-token", "permissions": 0}
    ]
    await call._assert_can_publish_audio("room-token")


@pytest.mark.asyncio
async def test_subscriber_offer_waits_for_browser_publisher_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import call as call_module

    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    handle.ws = object()
    handle.remote_call_flags["human-session"] = _CALL_FLAG_WITH_AUDIO
    request_offer = AsyncMock()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(call_module, "_OFFER_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(call, "_request_offer", request_offer)

    await call._request_offer_retries(handle, "human-session")

    assert sleeps == [call_module._OFFER_INITIAL_DELAY_S]
    request_offer.assert_awaited_once_with(handle, "human-session")
    assert "human-session" not in handle.pending_offers


@pytest.mark.asyncio
async def test_subscriber_without_relay_keeps_retrying_with_capped_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    peer = SimpleNamespace(close=AsyncMock())
    handle.subs["human-session"] = peer
    remove_subscriber = AsyncMock()
    ensure_offer = Mock()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(call, "_remove_subscriber", remove_subscriber)
    monkeypatch.setattr(call, "_ensure_subscriber_offer", ensure_offer)

    await call._retry_subscriber_without_relay(
        handle,
        "human-session",
        peer,
        retries=20,
    )

    assert sleeps == [0]
    remove_subscriber.assert_awaited_once_with(handle, "human-session")
    assert handle.sub_relay_retries["human-session"] == 21
    ensure_offer.assert_called_once_with(
        handle,
        "human-session",
        initial_delay_s=30.0,
    )


@pytest.mark.asyncio
async def test_media_state_broadcast_matches_talk_mcu_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import call as call_module

    call = TalkCall(
        client=SimpleNamespace(),
        self_id="bot",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
    )
    handle = _CallHandle()
    handle.ws = object()
    handle.publisher_ready.set()
    handle.remote_call_flags["human-session"] = _CALL_FLAG_WITH_AUDIO
    send = AsyncMock()
    monkeypatch.setattr(call_module, "_MEDIA_STATE_RETRY_DELAYS_S", (0.0,))
    monkeypatch.setattr(call, "_send", send)

    await call._broadcast_media_state(handle, "human-session")

    assert [awaited.args[1]["message"]["data"] for awaited in send.await_args_list] == [
        {
            "to": "human-session",
            "type": "unmute",
            "roomType": "video",
            "payload": {"name": "audio"},
        },
        {
            "to": "human-session",
            "type": "mute",
            "roomType": "video",
            "payload": {"name": "video"},
        },
    ]


def _patch_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from bridge.nextcloud import call as call_module
    from core.params.runtime_settings import runtime_settings

    async def resolve_nextcloud_connection(connection_id: int) -> SimpleNamespace:
        assert connection_id == 42
        return SimpleNamespace(
            base_url="https://cloud.test",
            login="bot",
            password="app-password",
            self_id="bot-user",
        )

    monkeypatch.setattr(
        call_module,
        "resolve_nextcloud_connection",
        resolve_nextcloud_connection,
    )
    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_NEXTCLOUD_TALK_HPB_URL",
        "wss://hpb.test/spreed",
    )


@pytest.mark.asyncio
async def test_from_connection_id_uses_connection_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connection(monkeypatch)

    call = await TalkCall.from_connection_id(42)

    assert call._client.password == "app-password"
    assert call._hpb_url == "wss://hpb.test/spreed"
    assert call._connection_id == 42


@pytest.mark.asyncio
async def test_local_terminate_suppresses_auto_answer_before_ending_call_for_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import call_listener

    timeline: list[str] = []
    client = SimpleNamespace(aclose=AsyncMock())
    call = TalkCall(
        client=client,
        self_id="orion",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
        connection_id=8,
    )
    call._room_id = "room-orion"
    handle = _CallHandle()
    handle.join_completed = True
    handle.remote_actor_ids.add("nicolas")

    def suppress(
        connection_id: int,
        room_id: str,
        remote_actor_ids: set[str],
    ) -> None:
        assert handle.call_ended.is_set() is False
        timeline.append("suppress")
        assert (connection_id, room_id, remote_actor_ids) == (
            8,
            "room-orion",
            {"nicolas"},
        )

    async def leave_media_call(*, all_participants: bool) -> None:
        timeline.append("terminate" if all_participants else "leave")

    monkeypatch.setattr(call_listener, "suppress_auto_answer", suppress)
    monkeypatch.setattr(call, "_leave_media_call_visible", leave_media_call)

    await call.terminate(handle)

    assert timeline == ["suppress", "terminate"]
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_join_cleanup_does_not_suppress_auto_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bridge.nextcloud import call_listener

    client = SimpleNamespace(aclose=AsyncMock())
    call = TalkCall(
        client=client,
        self_id="orion",
        nextcloud_url="https://cloud.test",
        hpb_url="wss://hpb.test/spreed",
        connection_id=8,
    )
    call._room_id = "room-orion"
    suppress = Mock()
    monkeypatch.setattr(call_listener, "suppress_auto_answer", suppress)
    leave_media_call = AsyncMock()
    monkeypatch.setattr(call, "_leave_media_call_visible", leave_media_call)

    await call.leave(_CallHandle())

    suppress.assert_not_called()
    leave_media_call.assert_awaited_once_with(all_participants=False)


@pytest.mark.asyncio
async def test_audio_backpressure_is_bounded_and_interruption_discards_blocked_speech():
    track = _build_out_track()
    speech = b"\x01\x00" * 960
    producer = asyncio.create_task(track.push(speech * 102))
    await asyncio.sleep(0)
    assert track._queue.qsize() == 100 and not producer.done()
    track.clear()
    await asyncio.wait_for(producer, 1)
    # A producer blocked during clear may have queued one old-generation frame.
    # It must never become audible after barge-in.
    frame = await track.recv()
    assert not any(bytes(frame.planes[0]))
    await asyncio.wait_for(track.wait_drained(), 1)
    track.stop()
