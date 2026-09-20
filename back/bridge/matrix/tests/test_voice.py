from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bridge.matrix.voice_provider as voice_provider_module
from app.connection import connection_service
from app.tools import tool_service
from bridge.matrix.call import (
    MatrixCall,
    _MatrixCallHandle,
    _OutboundAudioTrack,
    _sdp_candidates,
)
from bridge.matrix.events import MatrixRoomEvent, matrix_event_bus
from bridge.matrix.voice_provider import MatrixVoiceProvider
from bridge.matrix.voice_listener import _valid_invite


def _invite(*, lifetime: int = 60_000) -> MatrixRoomEvent:
    now = int(time.time() * 1_000)
    return MatrixRoomEvent(
        connection_id=4,
        room_id="!room:test",
        event_id="$invite",
        sender="@alice:test",
        type="m.call.invite",
        content={
            "call_id": "call-1",
            "party_id": "party-a",
            "version": "1",
            "lifetime": lifetime,
            "invitee": "@bot:test",
            "offer": {"type": "offer", "sdp": "v=0"},
        },
        origin_server_ts=now,
        raw={},
    )


def test_matrix_invite_validation_and_expiry() -> None:
    assert _valid_invite(_invite(), "@bot:test")
    expired = _invite(lifetime=1)
    expired = replace(
        expired,
        origin_server_ts=expired.origin_server_ts - 10_000,
    )
    assert not _valid_invite(expired, "@bot:test")


def test_sdp_candidates_include_mid_and_mline() -> None:
    candidates = _sdp_candidates(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=mid:0\r\n"
        "a=candidate:1 1 udp 1 192.0.2.1 5000 typ host\r\n"
    )
    assert candidates == [
        {
            "candidate": "candidate:1 1 udp 1 192.0.2.1 5000 typ host",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }
    ]


@pytest.mark.asyncio
async def test_outbound_track_reports_when_playback_is_drained() -> None:
    track = _OutboundAudioTrack()
    track.push(b"\x01\x00" * 960)
    drained = asyncio.create_task(track.wait_drained())
    await asyncio.sleep(0)

    assert not drained.done()

    await track.recv()
    await asyncio.wait_for(drained, timeout=1)


@pytest.mark.asyncio
async def test_initial_greeting_waits_for_inbound_pcm() -> None:
    matrix = SimpleNamespace(user_id="@bot:test")
    call = MatrixCall(matrix, connection_id=4, outgoing=False)
    handle = _MatrixCallHandle("!room:test")
    ready = asyncio.create_task(call.wait_input_ready(handle))
    await asyncio.sleep(0)

    assert not ready.done()

    handle.inbound_ready.set()
    await asyncio.wait_for(ready, timeout=1)


@pytest.mark.asyncio
async def test_event_bus_replays_signaling_events() -> None:
    matrix_event_bus.reset_for_tests()
    event = _invite()
    await matrix_event_bus.publish(event)
    await matrix_event_bus.publish(event)
    subscription = matrix_event_bus.subscribe(4)
    try:
        assert subscription.queue.qsize() == 1
        assert await subscription.get() == event
    finally:
        await subscription.close()


@pytest.mark.asyncio
async def test_outgoing_call_sends_invite_candidates_and_hangup() -> None:
    class FakeMatrix:
        user_id = "@bot:test"
        events: list[tuple[str, dict[str, object]]] = []

        async def turn_server(self) -> dict[str, object]:
            return {}

        async def joined_members(self, room_id: str) -> dict[str, dict[str, object]]:
            assert room_id == "!room:test"
            return {"@bot:test": {}, "@alice:test": {}}

        async def room_is_encrypted(self, room_id: str) -> bool:
            assert room_id == "!room:test"
            return False

        async def send_room_event(
            self,
            room_id: str,
            event_type: str,
            content: dict[str, object],
        ) -> dict[str, str]:
            self.events.append((event_type, content))
            return {"event_id": f"${len(self.events)}"}

        async def aclose(self) -> None:
            return None

    matrix = FakeMatrix()
    transport = MatrixCall(
        matrix,  # type: ignore[arg-type]
        connection_id=4,
        outgoing=True,
    )
    handle = await transport.join("!room:test")
    await transport.leave(handle)

    event_types = [event_type for event_type, _content in matrix.events]
    assert event_types[0] == "m.call.invite"
    assert "m.call.candidates" in event_types
    assert event_types[-1] == "m.call.hangup"
    invite = matrix.events[0][1]
    assert invite["invitee"] == "@alice:test"
    assert invite["version"] == "1"


@pytest.mark.asyncio
async def test_outgoing_call_refuses_encrypted_room() -> None:
    class FakeEncryptedMatrix:
        user_id = "@bot:test"

        async def turn_server(self) -> dict[str, object]:
            return {}

        async def room_is_encrypted(self, room_id: str) -> bool:
            assert room_id == "!encrypted:test"
            return True

        async def aclose(self) -> None:
            return None

    transport = MatrixCall(
        FakeEncryptedMatrix(),  # type: ignore[arg-type]
        connection_id=4,
        outgoing=True,
    )

    with pytest.raises(ValueError, match="encrypted"):
        await transport.join("!encrypted:test")


@pytest.mark.asyncio
async def test_matrix_provider_validates_the_exact_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(
        id=42,
        agent_id=7,
        tool_id=5,
        active=True,
    )
    monkeypatch.setattr(
        connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    monkeypatch.setattr(
        tool_service,
        "get_tool_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                code="custom-matrix",
                messenger=SimpleNamespace(service="matrix"),
            )
        ),
    )
    sees_room = AsyncMock(return_value=True)
    monkeypatch.setattr(
        voice_provider_module,
        "_connection_sees_room",
        sees_room,
    )

    connection_id = await MatrixVoiceProvider().resolve_connection_id(
        agent_id=7,
        connection_id=42,
        room_id="!room:test",
    )

    assert connection_id == 42
    sees_room.assert_awaited_once_with(42, "!room:test")


@pytest.mark.asyncio
async def test_matrix_provider_creates_transport_for_exact_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = object()
    factory = AsyncMock(return_value=transport)
    monkeypatch.setattr(MatrixCall, "from_connection_id", factory)

    result = await MatrixVoiceProvider().create_transport(
        42,
        outgoing=False,
    )

    assert result is transport
    factory.assert_awaited_once_with(42, outgoing=False)
