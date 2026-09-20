from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock

import av  # pyright: ignore[reportMissingTypeStubs]
import pytest
from aiortc import (  # pyright: ignore[reportMissingTypeStubs]
    RTCPeerConnection,
    RTCSessionDescription,
)
from pydantic import SecretStr

# pyright: reportPrivateUsage=false

from app.chat.webrtc import (
    _PCM_FRAME_BYTES,
    _OutgoingAudioTrack,
    BrowserCallTransport,
    browser_answer_with_embedded_relay_alias,
    browser_answer_network_available,
    browser_call_network_available,
    browser_ice_servers,
    browser_rtc_configuration,
)
from app.voice.models import AudioFrame
from core.settings import settings


@pytest.mark.asyncio
async def test_slow_permission_refresh_does_not_pause_call_audio(monkeypatch):
    from core import user as user_api
    from core import authorize as authorization

    refreshing = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def get_user(_user_id):
        nonlocal calls
        calls += 1
        if calls > 1:
            refreshing.set()
            await release.wait()
        return object()

    monkeypatch.setattr(user_api, "get_user_record", get_user)
    monkeypatch.setattr(authorization, "check_privilege", AsyncMock(return_value=True))
    transport = BrowserCallTransport("user:1", user_id=1)
    source = av.AudioFrame(format="s16", layout="mono", samples=960)
    source.sample_rate = 48_000
    source.planes[0].update(b"\x01\x00" * 960)

    class IncomingTrack:
        async def recv(self):
            return source

    transport._incoming_track = IncomingTrack()
    transport._incoming_track_ready.set()
    inbound = transport.inbound_audio(transport)

    async def frames():
        yield AudioFrame(pcm=b"\x02\x00" * 960)

    try:
        await transport.join("room")
        await anext(inbound)
        # Expire the authorization refresh, as during a running call.
        await asyncio.sleep(1.05)
        receiving = asyncio.create_task(anext(inbound))
        await asyncio.wait_for(refreshing.wait(), timeout=1.5)
        frame = await asyncio.wait_for(receiving, timeout=0.2)
        await asyncio.wait_for(transport.send_audio(transport, frames()), timeout=0.2)
        assert frame.pcm == b"\x01\x00" * 960
        assert transport._outgoing_track._queue.qsize() == 1
    finally:
        release.set()
        await inbound.aclose()
        await transport.leave(transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["denied", "error", "timeout"])
async def test_permission_refresh_failure_closes_idle_call(monkeypatch, failure):
    from core import user as user_api
    from core import authorize as authorization

    calls = 0

    async def check(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return True
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure == "error":
            raise RuntimeError("database unavailable")
        return False

    monkeypatch.setattr(user_api, "get_user_record", AsyncMock(return_value=object()))
    monkeypatch.setattr(authorization, "check_privilege", check)
    transport = BrowserCallTransport("user:1", user_id=1)

    async def frames():
        yield AudioFrame(pcm=b"\x01\x00" * 960)

    try:
        await transport.join("room")
        await transport.send_audio(transport, frames())
        inbound = transport.inbound_audio(transport)
        receiving = asyncio.create_task(anext(inbound))
        await asyncio.wait_for(transport._ended.wait(), timeout=3.0)
        with pytest.raises(ConnectionError, match="inbound track"):
            await asyncio.wait_for(receiving, timeout=0.2)
        await transport._permission_task
        assert transport._peer.connectionState == "closed"
        assert transport._outgoing_track._queue.empty()
    finally:
        await transport.leave(transport)


@pytest.mark.asyncio
async def test_audio_only_requires_call_privilege_and_stops_when_revoked(db):
    from uuid import uuid4
    from sqlalchemy import select
    from core.authorize import Assignment, Privilege, Role
    from core.user import UserModel

    user = UserModel(email=f"voice-{uuid4()}@example.com", hashed_password="unused", is_active=True)
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "CHAT_CALL"))
    role = Role(code=f"voice-{uuid4().hex}", display_name="Voice", privileges=[privilege])
    db.add_all([user, role])
    await db.flush()
    assignment = Assignment(user_id=user.id, role_id=role.id)
    db.add(assignment)
    await db.commit()
    transport = BrowserCallTransport(f"user:{user.id}", user_id=user.id)

    async def frames():
        yield AudioFrame(pcm=b"\x00" * _PCM_FRAME_BYTES, sample_rate=48000, channels=1)

    try:
        # No team, agent-management privilege or dialogue grant is needed.
        await transport.send_audio(transport, frames())
        assert transport._outgoing_track._queue.qsize() == 1
        await db.delete(assignment)
        await db.commit()
        # Revocation closes even an idle call, without waiting for another frame.
        await asyncio.wait_for(transport._ended.wait(), timeout=2.5)
        if transport._permission_task is not None:
            await transport._permission_task
        with pytest.raises(PermissionError, match="privilege has been revoked"):
            await transport.send_audio(transport, frames())
        assert transport._peer.connectionState == "closed"
        assert transport._outgoing_track._queue.empty()
    finally:
        await transport.leave(transport)


def _pcm(frame: Any) -> bytes:
    return bytes(frame.planes[0])[:_PCM_FRAME_BYTES]


def test_turn_rest_credentials_are_short_lived_and_match_aiortc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "external")
    monkeypatch.setattr(
        settings,
        "WEBRTC_ICE_URLS",
        "stun:turn.example.test:3478,turn:turn.example.test:3478?transport=udp",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("shared-secret"),
    )
    monkeypatch.setattr(settings, "WEBRTC_TURN_TTL_SECONDS", 600)

    servers = browser_ice_servers("user:17", now=1_000)

    assert servers[0].urls == ("stun:turn.example.test:3478",)
    assert servers[0].username is None
    assert servers[1].username == "1600:galaris:user:17"
    assert servers[1].credential is not None
    assert base64.b64decode(servers[1].credential) == hmac.new(
        b"shared-secret",
        b"1600:galaris:user:17",
        hashlib.sha1,
    ).digest()

    configuration = browser_rtc_configuration("user:17")
    assert len(configuration.iceServers) == 2
    assert configuration.iceServers[1].username is not None
    assert configuration.iceServers[1].credential is not None


def test_default_ice_servers_use_the_galaris_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "embedded")
    monkeypatch.setattr(settings, "APP_HOST", "https://galaris.example.test")
    monkeypatch.setattr(settings, "WEBRTC_ICE_URLS", "")
    monkeypatch.setattr(settings, "WEBRTC_TURN_HOST", "auto")
    monkeypatch.setattr(settings, "WEBRTC_TURN_PORT", 3_479)
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_RELAY_IP_RESOLVED",
        "192.168.50.12",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("shared-secret"),
    )

    servers = browser_ice_servers("user:17", now=1_000)

    assert [server.urls[0] for server in servers] == [
        "stun:galaris.example.test:3479",
        "turn:galaris.example.test:3479?transport=udp",
        "turn:galaris.example.test:3479?transport=tcp",
        "stun:192.168.50.12:3479",
        "turn:192.168.50.12:3479?transport=udp",
        "turn:192.168.50.12:3479?transport=tcp",
    ]

    backend_configuration = browser_rtc_configuration("user:17")
    assert [server.urls[0] for server in backend_configuration.iceServers] == [
        "stun:host.docker.internal:3479",
        "turn:host.docker.internal:3479?transport=udp",
        "turn:host.docker.internal:3479?transport=tcp",
    ]
    assert backend_configuration.iceServers[1].username is not None
    assert backend_configuration.iceServers[1].credential is not None


def test_explicit_ice_urls_do_not_inherit_the_embedded_lan_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "embedded")
    monkeypatch.setattr(
        settings,
        "WEBRTC_ICE_URLS",
        "turn:turn.example.test:3478?transport=tcp",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_RELAY_IP_RESOLVED",
        "192.168.50.12",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("shared-secret"),
    )

    servers = browser_ice_servers("user:17", now=1_000)

    assert [server.urls[0] for server in servers] == [
        "turn:turn.example.test:3478?transport=tcp"
    ]


def test_production_does_not_invent_turn_when_it_is_explicitly_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "disabled")
    monkeypatch.setattr(
        settings,
        "WEBRTC_ICE_URLS",
        "turn:should-not-be-used.example.test:3478",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("generated-but-unused-secret"),
    )

    assert browser_ice_servers("user:17", now=1_000) == ()
    assert browser_call_network_available() is False


def test_embedded_calls_wait_for_the_automatically_generated_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "embedded")
    monkeypatch.setattr(settings, "WEBRTC_ICE_URLS", "")
    monkeypatch.setattr(settings, "WEBRTC_TURN_HOST", "auto")
    monkeypatch.setattr(settings, "APP_HOST", "https://galaris.example.test")
    monkeypatch.setattr(settings, "WEBRTC_TURN_SHARED_SECRET", SecretStr(""))

    assert browser_call_network_available() is False

    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("generated-secret"),
    )

    assert browser_call_network_available() is True


@pytest.mark.parametrize("environment", ["prod", "pp", "test", "demo", "custom"])
def test_production_browser_calls_require_an_authenticated_turn_relay(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", environment)
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "external")
    monkeypatch.setattr(
        settings,
        "WEBRTC_ICE_URLS",
        "stun:stun.l.google.com:19302",
    )
    monkeypatch.setattr(settings, "WEBRTC_TURN_SHARED_SECRET", SecretStr(""))

    assert browser_call_network_available() is False

    monkeypatch.setattr(
        settings,
        "WEBRTC_ICE_URLS",
        "stun:turn.example.test:3478,turn:turn.example.test:3478?transport=udp",
    )
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_SHARED_SECRET",
        SecretStr("shared-secret"),
    )

    assert browser_call_network_available() is True


@pytest.mark.parametrize("environment", ["prod", "pp", "test", "demo", "custom"])
def test_production_answer_requires_a_gathered_relay_candidate(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", environment)

    assert browser_answer_network_available(
        "v=0\r\na=candidate:1 1 UDP 1 172.20.0.2 5000 typ host\r\n"
    ) is False
    assert browser_answer_network_available(
        "v=0\r\na=candidate:2 1 UDP 1 203.0.113.7 5001 typ relay raddr 0.0.0.0\r\n"
    ) is True

    monkeypatch.setattr(settings, "APP_ENV", "dev")
    assert browser_answer_network_available("v=0\r\n") is True


def test_embedded_answer_exposes_public_and_lan_relay_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "embedded")
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_RELAY_IP_RESOLVED",
        "192.168.50.12",
    )
    public_candidate = (
        "a=candidate:1c0a4dcf00baa053b75ef9230c6e0912 1 udp 16777215 "
        "203.0.113.7 47011 typ relay raddr 172.20.0.2 rport 56960"
    )
    sdp = f"v=0\r\n{public_candidate}\r\n"

    answer = browser_answer_with_embedded_relay_alias(sdp)

    candidates = [
        line for line in answer.splitlines() if line.startswith("a=candidate:")
    ]
    assert len(candidates) == 2
    assert " 192.168.50.12 47011 typ relay " in f" {candidates[0]} "
    assert candidates[1] == public_candidate
    assert candidates[0].split()[0] != candidates[1].split()[0]
    assert answer.endswith("\r\n")


def test_external_answer_does_not_invent_a_lan_relay_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEBRTC_TURN_MODE", "external")
    monkeypatch.setattr(
        settings,
        "WEBRTC_TURN_RELAY_IP_RESOLVED",
        "192.168.50.12",
    )
    sdp = (
        "v=0\r\na=candidate:relay 1 udp 16777215 203.0.113.7 47011 "
        "typ relay\r\n"
    )

    assert browser_answer_with_embedded_relay_alias(sdp) == sdp


@pytest.mark.asyncio
async def test_outgoing_track_prerolls_silence_and_preserves_all_pcm() -> None:
    track = _OutgoingAudioTrack()

    silence = await track.recv()
    assert _pcm(silence) == b"\x00" * _PCM_FRAME_BYTES

    speech = bytes(index % 251 + 1 for index in range(_PCM_FRAME_BYTES * 2))
    track.push(AudioFrame(pcm=speech))

    first = await track.recv()
    second = await track.recv()

    assert _pcm(first) + _pcm(second) == speech
    await asyncio.wait_for(track.wait_drained(), timeout=0.1)


@pytest.mark.asyncio
async def test_browser_output_waits_for_peer_connection() -> None:
    transport = BrowserCallTransport("user:1")
    waiting = asyncio.create_task(transport.wait_output_ready(transport))
    await asyncio.sleep(0)

    assert not waiting.done()

    transport._connected.set()
    await asyncio.wait_for(waiting, timeout=0.1)
    await transport.leave(transport)


@pytest.mark.asyncio
async def test_browser_input_waits_for_first_pcm_frame() -> None:
    transport = BrowserCallTransport("user:1")
    source = av.AudioFrame(format="s16", layout="mono", samples=960)
    source.sample_rate = 48_000
    source.planes[0].update(b"\x01\x00" * 960)

    class _IncomingTrack:
        async def recv(self) -> Any:
            return source

    transport._incoming_track = _IncomingTrack()
    transport._incoming_track_ready.set()
    waiting = asyncio.create_task(transport.wait_input_ready(transport))
    inbound = transport.inbound_audio(transport)
    await asyncio.sleep(0)

    assert not waiting.done()

    frame = await anext(inbound)
    await asyncio.wait_for(waiting, timeout=0.1)
    assert frame.pcm == b"\x01\x00" * 960
    await inbound.aclose()
    await transport.leave(transport)


@pytest.mark.asyncio
async def test_browser_call_accepts_trickled_mobile_ice_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = BrowserCallTransport("user:1")
    add_candidate = AsyncMock()
    monkeypatch.setattr(transport._peer, "addIceCandidate", add_candidate)

    await transport.add_remote_candidate(
        "candidate:1 1 udp 2122260223 192.0.2.10 50000 typ host",
        sdp_mid="0",
        sdp_m_line_index=0,
    )
    await transport.add_remote_candidate(
        None,
        sdp_mid=None,
        sdp_m_line_index=None,
    )

    parsed = add_candidate.await_args_list[0].args[0]
    assert parsed.ip == "192.0.2.10"
    assert parsed.port == 50_000
    assert parsed.sdpMid == "0"
    assert parsed.sdpMLineIndex == 0
    assert add_candidate.await_args_list[1].args == (None,)
    await transport.leave(transport)


@pytest.mark.asyncio
async def test_trickled_offer_establishes_a_real_peer_connection() -> None:
    browser = RTCPeerConnection()
    browser.addTrack(_OutgoingAudioTrack())
    transport = BrowserCallTransport("user:1")
    try:
        offer = await browser.createOffer()
        await browser.setLocalDescription(offer)

        answer_sdp, answer_type = await transport.accept_offer(
            offer.sdp,
            str(offer.type),
        )
        await browser.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type=answer_type)
        )
        for line in str(browser.localDescription.sdp).splitlines():
            if not line.startswith("a=candidate:"):
                continue
            await transport.add_remote_candidate(
                line.removeprefix("a="),
                sdp_mid="0",
                sdp_m_line_index=0,
            )
        await transport.add_remote_candidate(
            None,
            sdp_mid=None,
            sdp_m_line_index=None,
        )

        await asyncio.wait_for(transport._connected.wait(), timeout=3.0)
        assert browser.connectionState == "connected"
    finally:
        await browser.close()
        await transport.leave(transport)
