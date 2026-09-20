"""Browser WebRTC audio transport for native Messenger calls."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, AsyncIterator
from urllib.parse import urlsplit
from uuid import uuid4

import av  # pyright: ignore[reportMissingTypeStubs]
from aiortc import (  # pyright: ignore[reportMissingTypeStubs]
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.sdp import candidate_from_sdp  # pyright: ignore[reportMissingTypeStubs]

from app.voice import (
    AudioFrame,
    CallTransport,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
)
from core.settings import settings


_FRAME_MS = 20
_BYTES_PER_SAMPLE = 2
_SAMPLES_PER_FRAME = DEFAULT_SAMPLE_RATE * _FRAME_MS // 1_000
_PCM_FRAME_BYTES = _SAMPLES_PER_FRAME * DEFAULT_CHANNELS * _BYTES_PER_SAMPLE
_STUN_SCHEMES = frozenset({"stun", "stuns"})
_TURN_SCHEMES = frozenset({"turn", "turns"})
_EMBEDDED_BACKEND_HOST = "host.docker.internal"


@dataclass(frozen=True, slots=True)
class BrowserIceServer:
    """One authenticated ICE server safe to expose to an authorized browser."""

    urls: tuple[str, ...]
    username: str | None = None
    credential: str | None = None


def _default_ice_urls(host: str) -> tuple[str, ...]:
    if not host:
        return ()
    uri_host = f"[{host}]" if ":" in host else host
    port = settings.WEBRTC_TURN_PORT
    return (
        f"stun:{uri_host}:{port}",
        f"turn:{uri_host}:{port}?transport=udp",
        f"turn:{uri_host}:{port}?transport=tcp",
    )


def _configured_ice_urls(*, backend: bool = False) -> tuple[str, ...]:
    if settings.WEBRTC_TURN_MODE == "disabled":
        return ()
    configured = settings.WEBRTC_ICE_URLS.strip()
    if not configured:
        if settings.WEBRTC_TURN_MODE == "external":
            return ()
        if backend:
            return _default_ice_urls(_EMBEDDED_BACKEND_HOST)
        host = settings.WEBRTC_TURN_HOST.strip()
        if host.lower() == "auto":
            host = urlsplit(settings.APP_HOST).hostname or ""
        urls = list(_default_ice_urls(host))
        relay_ip = settings.WEBRTC_TURN_RELAY_IP_RESOLVED.strip()
        if relay_ip and relay_ip != host:
            urls.extend(_default_ice_urls(relay_ip))
        return tuple(dict.fromkeys(urls))
    urls = tuple(
        dict.fromkeys(
            item.strip()
            for item in configured.split(",")
            if item.strip()
        )
    )
    for url in urls:
        scheme, separator, address = url.partition(":")
        if (
            not separator
            or not address.strip()
            or scheme.lower() not in _STUN_SCHEMES | _TURN_SCHEMES
        ):
            raise ValueError(f"Unsupported WebRTC ICE server URL: {url!r}")
    return urls


def _turn_credentials(subject: str, now: int | None) -> tuple[str, str] | None:
    secret = settings.WEBRTC_TURN_SHARED_SECRET.get_secret_value()
    if not secret:
        return None
    current_time = int(time.time()) if now is None else now
    username = (
        f"{current_time + settings.WEBRTC_TURN_TTL_SECONDS}:galaris:{subject}"
    )
    digest = hmac.new(
        secret.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return username, base64.b64encode(digest).decode("ascii")


def _ice_servers_for_urls(
    subject: str,
    urls: tuple[str, ...],
    *,
    now: int | None = None,
) -> tuple[BrowserIceServer, ...]:
    credentials = _turn_credentials(subject, now)
    servers: list[BrowserIceServer] = []
    for url in urls:
        scheme = url.partition(":")[0].lower()
        if scheme in _STUN_SCHEMES:
            servers.append(BrowserIceServer(urls=(url,)))
        elif credentials is not None:
            username, credential = credentials
            servers.append(
                BrowserIceServer(
                    urls=(url,),
                    username=username,
                    credential=credential,
                )
            )
    return tuple(servers)


def browser_ice_servers(
    subject: str,
    *,
    now: int | None = None,
) -> tuple[BrowserIceServer, ...]:
    """Return public ICE servers and short-lived TURN credentials for one user."""

    return _ice_servers_for_urls(subject, _configured_ice_urls(), now=now)


def browser_call_network_available() -> bool:
    """Require an authenticated relay in production-like environments."""

    urls = _configured_ice_urls()
    has_turn_url = any(
        url.partition(":")[0].lower() in _TURN_SCHEMES for url in urls
    )
    has_turn_secret = bool(settings.WEBRTC_TURN_SHARED_SECRET.get_secret_value())
    if settings.WEBRTC_TURN_MODE == "embedded":
        return has_turn_url and has_turn_secret
    if not settings.is_dev:
        return has_turn_url and has_turn_secret
    return bool(urls)


def browser_answer_network_available(sdp: str) -> bool:
    """Require proof that aiortc gathered a usable relay in production."""

    if settings.is_dev:
        return True
    return any(
        line.startswith("a=candidate:") and " typ relay " in f" {line.strip()} "
        for line in sdp.splitlines()
    )


def browser_answer_with_embedded_relay_alias(sdp: str) -> str:
    """Expose the embedded relay's LAN address beside its public NAT address."""

    if settings.WEBRTC_TURN_MODE != "embedded":
        return sdp
    relay_ip = settings.WEBRTC_TURN_RELAY_IP_RESOLVED.strip()
    if not relay_ip:
        return sdp

    separator = "\r\n" if "\r\n" in sdp else "\n"
    trailing_separator = sdp.endswith(("\r\n", "\n"))
    lines = sdp.splitlines()
    expanded: list[str] = []
    known = set(lines)
    for line in lines:
        fields = line.split()
        if (
            line.startswith("a=candidate:")
            and len(fields) >= 8
            and fields[2].lower() == "udp"
            and fields[6].lower() == "typ"
            and fields[7].lower() == "relay"
            and fields[4] != relay_ip
        ):
            public_foundation = fields[0].partition(":")[2]
            alias_foundation = hashlib.sha256(
                f"{public_foundation}:{relay_ip}".encode("ascii")
            ).hexdigest()[:32]
            fields[0] = f"a=candidate:{alias_foundation}"
            fields[4] = relay_ip
            alias = " ".join(fields)
            if alias not in known:
                expanded.append(alias)
                known.add(alias)
        expanded.append(line)

    result = separator.join(expanded)
    if trailing_separator:
        result += separator
    return result


def browser_rtc_configuration(subject: str) -> RTCConfiguration:
    """Build aiortc ICE config, using the host gateway for embedded TURN."""

    ice_servers = [
        RTCIceServer(
            urls=list(server.urls),
            username=server.username,
            credential=server.credential,
        )
        for server in _ice_servers_for_urls(
            subject,
            _configured_ice_urls(backend=True),
        )
    ]
    return RTCConfiguration(iceServers=ice_servers)


class _OutgoingAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = bytearray()
        self._pts = 0
        self._drained = asyncio.Event()
        self._drained.set()

    def push(self, frame: AudioFrame) -> None:
        if (
            frame.sample_rate != DEFAULT_SAMPLE_RATE
            or frame.channels != DEFAULT_CHANNELS
        ):
            raise ValueError("Browser calls require canonical 48 kHz mono PCM")
        pcm = frame.pcm
        if len(pcm) % _BYTES_PER_SAMPLE:
            pcm = pcm[: -(len(pcm) % _BYTES_PER_SAMPLE)]
        if not pcm:
            return
        self._drained.clear()
        self._queue.put_nowait(pcm)

    def clear(self) -> int:
        cleared_bytes = len(self._buffer)
        self._buffer.clear()
        while True:
            try:
                cleared_bytes += len(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                self._drained.set()
                return (
                    cleared_bytes + _PCM_FRAME_BYTES - 1
                ) // _PCM_FRAME_BYTES

    async def wait_drained(self) -> None:
        await self._drained.wait()

    def _next_pcm_frame(self) -> bytes:
        while len(self._buffer) < _PCM_FRAME_BYTES:
            try:
                self._buffer.extend(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        pcm = bytes(self._buffer[:_PCM_FRAME_BYTES])
        del self._buffer[:_PCM_FRAME_BYTES]
        return pcm.ljust(_PCM_FRAME_BYTES, b"\x00")

    async def recv(self) -> Any:
        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=_SAMPLES_PER_FRAME,
        )
        frame.sample_rate = DEFAULT_SAMPLE_RATE
        frame.planes[0].update(self._next_pcm_frame())
        frame.pts = self._pts
        frame.time_base = Fraction(1, DEFAULT_SAMPLE_RATE)
        self._pts += frame.samples
        # MediaStreamTrack.recv() owns pacing. Without this delay aiortc drains
        # complete utterances before the browser's RTP jitter buffer is ready,
        # which clips the beginning of speech.
        await asyncio.sleep(_FRAME_MS / 1_000)
        if not self._buffer and self._queue.empty():
            self._drained.set()
        return frame


class BrowserCallTransport(CallTransport):
    """One peer connection carrying PCM between a browser and VoiceSession."""

    kind = "internal"

    def __init__(
        self,
        remote_user_id: str,
        *,
        configuration: RTCConfiguration | None = None,
        user_id: int | None = None,
    ) -> None:
        self._peer = RTCPeerConnection(configuration=configuration)
        self._remote_user_id = remote_user_id
        self._user_id = user_id
        self._permission_lock = asyncio.Lock()
        self._permission_task: asyncio.Task[None] | None = None
        self._permission_error: Exception | None = None
        self._call_external_id = f"internal:call:{uuid4()}"
        self._incoming_track: Any | None = None
        self._incoming_track_ready = asyncio.Event()
        self._incoming_audio_ready = asyncio.Event()
        self._connected = asyncio.Event()
        self._ended = asyncio.Event()
        self._outgoing_track = _OutgoingAudioTrack()
        self._peer.addTrack(self._outgoing_track)

        @self._peer.on("track")
        def on_track(track: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            if getattr(track, "kind", None) == "audio":
                self._incoming_track = track
                self._incoming_track_ready.set()

        @self._peer.on("connectionstatechange")
        async def on_connection_state_change() -> None:  # pyright: ignore[reportUnusedFunction]
            state = self._peer.connectionState
            if state == "connected":
                self._connected.set()
            elif state in {"closed", "failed", "disconnected"}:
                self._ended.set()

    async def accept_offer(self, sdp: str, description_type: str) -> tuple[str, str]:
        if description_type != "offer":
            raise ValueError("A WebRTC offer is required.")
        await self._peer.setRemoteDescription(
            RTCSessionDescription(sdp=sdp, type=description_type)
        )
        answer = await self._peer.createAnswer()
        await self._peer.setLocalDescription(answer)
        local = self._peer.localDescription
        return str(local.sdp), str(local.type)

    async def add_remote_candidate(
        self,
        candidate: str | None,
        *,
        sdp_mid: str | None,
        sdp_m_line_index: int | None,
    ) -> None:
        """Apply one browser ICE candidate after the initial SDP offer.

        Mobile WebRTC clients gather host, server-reflexive and relay routes
        asynchronously. Keeping this channel open mirrors native clients and
        prevents later TURN candidates from being lost behind the first host
        candidate embedded in the offer.
        """
        if candidate is None:
            await self._peer.addIceCandidate(None)
            return
        parsed = candidate_from_sdp(
            candidate.split(":", 1)[1]
            if candidate.startswith("candidate:")
            else candidate
        )
        parsed.sdpMid = sdp_mid
        parsed.sdpMLineIndex = sdp_m_line_index
        await self._peer.addIceCandidate(parsed)

    async def join(self, room_id: str) -> "BrowserCallTransport":
        del room_id
        await self._ensure_permission_monitor()
        return self

    async def leave(self, handle: Any) -> None:
        del handle
        self._ended.set()
        monitor = self._permission_task
        if monitor is not None and monitor is not asyncio.current_task():
            # A failed monitor already owns peer closure; do not cancel that
            # closure when the media consumer observes the ended event.
            if self._permission_error is None:
                monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self._outgoing_track.clear()
        await self._peer.close()

    async def terminate(self, handle: Any) -> None:
        await self.leave(handle)

    async def _inbound(self) -> AsyncIterator[AudioFrame]:
        await self._ensure_permission_monitor()
        await self._wait_ready(self._incoming_track_ready, "inbound track")
        track = self._incoming_track
        if track is None:
            return
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=DEFAULT_SAMPLE_RATE,
        )
        while not self._ended.is_set():
            try:
                source = await track.recv()
            except Exception:
                self._ended.set()
                return
            if self._ended.is_set():
                return
            self._incoming_audio_ready.set()
            frames = resampler.resample(source)
            for frame in frames:
                size = int(frame.samples) * 2
                yield AudioFrame(
                    pcm=bytes(frame.planes[0])[:size],
                    sample_rate=DEFAULT_SAMPLE_RATE,
                    channels=DEFAULT_CHANNELS,
                )

    def inbound_audio(self, handle: Any) -> AsyncIterator[AudioFrame]:
        del handle
        return self._inbound()

    async def send_audio(
        self, handle: Any, frames: AsyncIterator[AudioFrame]
    ) -> None:
        del handle
        await self._ensure_permission_monitor()
        async for frame in frames:
            if self._permission_error is not None:
                raise self._permission_error
            if self._ended.is_set():
                return
            self._outgoing_track.push(frame)

    async def interrupt_output(self, handle: Any) -> None:
        del handle
        self._outgoing_track.clear()

    async def _ensure_permission_monitor(self) -> None:
        if self._permission_error is not None:
            raise self._permission_error
        if self._user_id is None:
            return
        async with self._permission_lock:
            if self._permission_task is not None or self._ended.is_set():
                return
            try:
                await self._check_call_privilege()
            except Exception as exc:
                self._permission_error = exc
                await self.leave(self)
                raise
            if not self._ended.is_set():
                self._permission_task = asyncio.create_task(
                    self._monitor_call_privilege(), name="browser_call_authorization",
                )

    async def _check_call_privilege(self) -> None:
        from core.database import get_db_session
        from core.authorize import Privileges, check_privilege
        from core.user import get_user_record

        assert self._user_id is not None
        # A slow database must neither stall PCM nor keep an unchecked call alive.
        async with asyncio.timeout(1.0):
            async with get_db_session() as db:
                user = await get_user_record(self._user_id)
                if not await check_privilege(user, Privileges.CHAT_CALL, db):
                    raise PermissionError("Voice call privilege has been revoked")

    async def _monitor_call_privilege(self) -> None:
        while not self._ended.is_set():
            try:
                await asyncio.wait_for(self._ended.wait(), timeout=1.0)
                return
            except TimeoutError:
                pass
            try:
                await self._check_call_privilege()
            except Exception as exc:
                self._permission_error = exc
                await self.leave(self)
                return

    async def _wait_ready(self, event: asyncio.Event, label: str) -> None:
        ready = asyncio.create_task(event.wait())
        ended = asyncio.create_task(self._ended.wait())
        try:
            await asyncio.wait(
                (ready, ended),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            ready.cancel()
            ended.cancel()
            await asyncio.gather(ready, ended, return_exceptions=True)
        if not event.is_set():
            raise ConnectionError(
                f"Browser call ended before {label} became available"
            )

    async def wait_output_ready(self, handle: Any) -> None:
        del handle
        await self._wait_ready(self._connected, "outbound audio")

    async def wait_input_ready(self, handle: Any) -> None:
        del handle
        await self._wait_ready(self._incoming_audio_ready, "inbound audio")

    async def wait_output_drained(self, handle: Any) -> None:
        del handle
        await self._outgoing_track.wait_drained()

    async def wait_ended(self, handle: Any) -> None:
        del handle
        await self._ended.wait()

    def remote_user_ids(self, handle: Any) -> tuple[str, ...]:
        del handle
        return (self._remote_user_id,)

    def call_external_id(self, handle: Any) -> str:
        del handle
        return self._call_external_id


__all__ = [
    "BrowserCallTransport",
    "BrowserIceServer",
    "browser_answer_with_embedded_relay_alias",
    "browser_answer_network_available",
    "browser_call_network_available",
    "browser_ice_servers",
    "browser_rtc_configuration",
]
