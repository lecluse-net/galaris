"""Nextcloud Talk audio-call transport over WebRTC through HPB and Janus videoroom.

MCU publish/subscribe model: the HPB hides Janus and the client exchanges SDP
through signaling ``message`` envelopes rather than directly with Janus.
- The publisher sends our audio through ``pc_pub`` to our own session; the server answers.
- To hear an ``inCall`` participant, the subscriber sends ``requestoffer``, answers
  the server's offer through ``pc_sub``, and feeds the remote track into ``inbound_audio``.

HPB authentication follows ``signaling.py``: ``join_call`` -> WebSocket -> ``hello``.

This implementation follows the spreed-signaling specification but has not been
validated against every real HPB/Janus version. Signaling versus Nextcloud session
IDs, ICE trickling, and Talk-version differences may need adjustment. Detailed
WebSocket logs support live diagnosis.

The wire contract follows the standalone-signaling-api-v1 specification.
"""

from __future__ import annotations

import asyncio
import fractions
import hashlib
import json
import time
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, cast
from urllib.parse import urlparse

import httpx
from loguru import logger

from core.params import runtime_settings
from core.i18n import render_prompt, t
from core.util import as_dict, as_list
from app.voice import AudioFrame, CallTransport
from app.voice.models import DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE

from .client import NextcloudTalkClient
from .credentials import resolve_nextcloud_connection
from .signaling import (
    _SUBPROTOCOL,  # pyright: ignore[reportPrivateUsage]
    build_hello_message,
    build_resume_hello_message,
    build_room_join_message,
    extract_hpb_url,
)

_FRAME_MS = 20

# Talk advertises its audio/video flags before its publisher necessarily reaches
# Janus. Give it a short head start, then avoid stacking requestoffer operations:
# the HPB itself can hold each one for about 10 seconds while awaiting the feed.
_OFFER_INITIAL_DELAY_S = 2.0
_OFFER_MAX_ATTEMPTS = 5
_OFFER_RETRY_INTERVAL_S = 12.0
# TURN can temporarily reject a new allocation while another device or a
# reconnecting peer still owns the account quota. Recreate the subscriber with
# a fresh allocation and keep retrying for the lifetime of the call instead of
# committing a relay-less answer that can only remain in ICE checking.
_SUBSCRIBER_RELAY_RETRY_DELAYS_S = (2.0, 4.0, 8.0, 16.0, 30.0)
_OUTBOUND_SUBSCRIBER_GRACE_S = 2.0
_PUBLISHER_CONNECT_TIMEOUT_S = 10.0
_HPB_PING_INTERVAL_S = 30.0
_HPB_RESUME_DELAYS_S = (1.0, 2.0, 4.0, 8.0, 16.0)
_CLIENT_FEATURES = ("chat-relay",)
# Talk's browser client announces its microphone/camera state several times
# when a participant joins.  The first messages can arrive before the remote
# subscriber peer exists, so a single announcement leaves the UI (and
# sometimes the media element) in an indeterminate/muted state.
_MEDIA_STATE_RETRY_DELAYS_S = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_STATUS_DATA_CHANNEL_LABEL = "status"
_STATUS_DATA_CHANNEL_MESSAGES = (
    '{"type":"audioOn"}',
    '{"type":"stoppedSpeaking"}',
    '{"type":"videoOff"}',
)
_STATUS_SPEAKING_MESSAGE = '{"type":"speaking"}'
_STATUS_STOPPED_SPEAKING_MESSAGE = '{"type":"stoppedSpeaking"}'


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)
_SAMPLES_PER_FRAME = DEFAULT_SAMPLE_RATE * _FRAME_MS // 1000  # 960 @ 48 kHz
_BYTES_PER_SAMPLE = 2
_PCM_FRAME_BYTES = _SAMPLES_PER_FRAME * DEFAULT_CHANNELS * _BYTES_PER_SAMPLE
_ROOM_TYPE = "video"  # Talk negotiates audio with roomType "video", not "screen".
_CALL_FLAG_IN_CALL = 1
_CALL_FLAG_WITH_AUDIO = 2
_CALL_FLAG_WITH_VIDEO = 4
_CALL_MEDIA_FLAGS = _CALL_FLAG_WITH_AUDIO | _CALL_FLAG_WITH_VIDEO
_PARTICIPANT_PERMISSION_PUBLISH_AUDIO = 16


def _host_label(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _pcm_bytes(frame: Any) -> bytes:
    """Return only useful PCM samples, excluding PyAV plane padding."""
    expected = frame.samples * DEFAULT_CHANNELS * _BYTES_PER_SAMPLE
    return bytes(frame.planes[0])[:expected]


def _http_error_details(exc: Exception) -> str:
    if not isinstance(exc, httpx.HTTPStatusError):
        return ""
    response = exc.response
    body = response.text.strip().replace("\n", " ")
    if len(body) > 500:
        body = body[:500] + "..."
    return f"status={response.status_code} url={response.request.url} body={body}"


def _session_fp(value: Any) -> dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"empty": True}
    return {
        "len": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def _room_diag(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": room.get("token"),
        "displayName": room.get("displayName") or room.get("name"),
        "type": room.get("type"),
        "participantType": room.get("participantType"),
        "readOnly": room.get("readOnly"),
    }


def _participant_call_flags(participant: dict[str, Any]) -> int:
    """Return Talk's ``inCall`` bit field without confusing presence with media.

    Since Talk 24, ``inCall=1`` only means that the participant is connected.
    The MCU can provide an offer only after audio (2) or video (4) is present.
    """
    raw = participant.get("inCall")
    if isinstance(raw, bool):
        return _CALL_FLAG_IN_CALL if raw else 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return _CALL_FLAG_IN_CALL
        try:
            return int(normalized)
        except ValueError:
            return 0
    return 0


def _participant_has_media_stream(participant: dict[str, Any]) -> bool:
    return bool(_participant_call_flags(participant) & _CALL_MEDIA_FLAGS)


def _build_out_track(
    on_speaking_changed: Callable[[bool], None] | None = None,
) -> Any:
    """Build an outbound audio track fed by a queue, emitting silence when empty."""
    import av
    from aiortc.mediastreams import MediaStreamTrack

    class _OutTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._queue: "asyncio.Queue[tuple[int, bytes]]" = asyncio.Queue(maxsize=100)
            self._generation = 0
            self._buffer = bytearray()
            self._pts = 0
            self._silence = b"\x00" * _PCM_FRAME_BYTES
            self._speaking = False
            self._drained = asyncio.Event()
            self._drained.set()

        def _update_speaking(self, speaking: bool) -> None:
            if speaking == self._speaking:
                return
            self._speaking = speaking
            if on_speaking_changed is not None:
                on_speaking_changed(speaking)

        async def push(self, pcm: bytes) -> None:
            if len(pcm) % _BYTES_PER_SAMPLE:
                pcm = pcm[: -(len(pcm) % _BYTES_PER_SAMPLE)]
            if not pcm:
                return
            generation = self._generation
            for offset in range(0, len(pcm), _PCM_FRAME_BYTES):
                if generation != self._generation or self.readyState == "ended":
                    return
                async with asyncio.timeout(10):
                    await self._queue.put((generation, pcm[offset:offset + _PCM_FRAME_BYTES]))
                if generation == self._generation:
                    self._drained.clear()

        def clear(self) -> int:
            """Drop buffered and queued speech immediately after a barge-in."""
            cleared_bytes = len(self._buffer)
            self._generation += 1
            self._buffer.clear()
            self._update_speaking(False)
            while True:
                try:
                    cleared_bytes += len(self._queue.get_nowait()[1])
                except asyncio.QueueEmpty:
                    self._drained.set()
                    return (
                        cleared_bytes + _PCM_FRAME_BYTES - 1
                    ) // _PCM_FRAME_BYTES

        async def wait_drained(self) -> None:
            await self._drained.wait()

        def stop(self) -> None:
            super().stop()
            self.clear()

        def _next_pcm_frame(self) -> bytes:
            while len(self._buffer) < _PCM_FRAME_BYTES:
                try:
                    generation, pcm = self._queue.get_nowait()
                    if generation == self._generation:
                        self._buffer.extend(pcm)
                except asyncio.QueueEmpty:
                    break
            if len(self._buffer) >= _PCM_FRAME_BYTES:
                pcm = bytes(self._buffer[:_PCM_FRAME_BYTES])
                del self._buffer[:_PCM_FRAME_BYTES]
                return pcm
            if self._buffer:
                pcm = bytes(self._buffer)
                self._buffer.clear()
                return pcm + (b"\x00" * (_PCM_FRAME_BYTES - len(pcm)))
            return self._silence

        async def recv(self) -> "av.AudioFrame":
            pcm = self._next_pcm_frame()
            self._update_speaking(any(pcm))
            frame = av.AudioFrame(format="s16", layout="mono", samples=_SAMPLES_PER_FRAME)
            frame.sample_rate = DEFAULT_SAMPLE_RATE
            frame.pts = self._pts
            frame.time_base = fractions.Fraction(1, DEFAULT_SAMPLE_RATE)
            frame.planes[0].update(pcm)
            self._pts += frame.samples
            await asyncio.sleep(_FRAME_MS / 1000)  # Do not run ahead of real time.
            if not self._buffer and self._queue.empty():
                self._drained.set()
            return frame

    return _OutTrack()


def _has_turn_server(ice_servers: List[Any]) -> bool:
    """Return whether at least one configured ICE server is a TURN relay."""
    for server in ice_servers:
        urls = cast(Any, getattr(server, "urls", None))
        candidates = cast(list[Any], urls) if isinstance(urls, list) else [urls]
        if any(isinstance(url, str) and url.startswith("turn") for url in candidates):
            return True
    return False


def _install_turn_failure_logging() -> None:
    """Expose TURN allocation failures which aioice otherwise discards.

    ``aioice.Connection.get_component_candidates`` deliberately ignores failed
    STUN/TURN tasks.  That makes a missing relay candidate indistinguishable
    from an allocation quota, authentication failure or network timeout.  Wrap
    only the relay factory and keep credentials out of the diagnostic.
    """
    import aioice.ice

    original = aioice.ice.relayed_candidate
    if getattr(original, "_galaris_logs_turn_failure", False):
        return

    async def _logged_relayed_candidate(*args: Any, **kwargs: Any) -> Any:
        try:
            return await original(*args, **kwargs)
        except Exception as exc:
            turn_server = kwargs.get("turn_server")
            turn_transport = kwargs.get("turn_transport", "unknown")
            logger.warning(
                "Talk call: TURN candidate gathering failed server={} "
                "transport={} error={}: {}",
                turn_server,
                turn_transport,
                type(exc).__name__,
                exc,
            )
            raise

    setattr(_logged_relayed_candidate, "_galaris_logs_turn_failure", True)
    aioice.ice.relayed_candidate = _logged_relayed_candidate


def _subscriber_ice_strategy(sdp: str, retries: int) -> tuple[int, bool]:
    """Choose a TURN endpoint and bundle policy for a Janus subscriber offer.

    Talk's browser publisher offers audio, video and data even when the camera
    is disabled. With aiortc's BALANCED policy this creates three ICE gatherers
    and can exhaust the TURN allocation quota before any relay candidate is
    retained. Android normally offers only audio and data, for which BALANCED
    remains the most compatible policy. Alternate policies on browser retries
    so MAX_BUNDLE candidate-gathering failures still have a safe fallback.
    """
    lines = tuple(line.strip() for line in sdp.splitlines())
    media_count = sum(line.startswith("m=") for line in lines)
    bundled = any(line.startswith("a=group:BUNDLE ") for line in lines)
    prefer_max_bundle = bundled and media_count >= 3
    if not prefer_max_bundle:
        return retries, False
    return retries // 2, retries % 2 == 0


def _subscriber_offer_profile(sdp: str) -> dict[str, Any]:
    """Return a non-sensitive SDP shape for browser/Android diagnostics."""
    bundle: list[str] = []
    media: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in sdp.splitlines():
        line = raw_line.strip()
        if line.startswith("a=group:BUNDLE "):
            bundle = line.split()[1:]
        elif line.startswith("m="):
            fields = line[2:].split()
            current = {
                "kind": fields[0] if fields else "",
                "port": fields[1] if len(fields) > 1 else "",
                "mid": "",
                "direction": "",
                "rtcp_mux": False,
            }
            media.append(current)
        elif current is not None and line.startswith("a=mid:"):
            current["mid"] = line.removeprefix("a=mid:")
        elif current is not None and line in {
            "a=inactive",
            "a=recvonly",
            "a=sendonly",
            "a=sendrecv",
        }:
            current["direction"] = line.removeprefix("a=")
        elif current is not None and line == "a=rtcp-mux":
            current["rtcp_mux"] = True
    return {"bundle": bundle, "media": media}


def _log_local_candidates(label: str, pc: Any) -> dict[str, int]:
    """Expose gathered candidate types; relay=0 means the TURN allocation failed.

    The remote side advertises a private host candidate here, so without a
    relay candidate the media leg usually cannot connect at all.
    """
    sdp = pc.localDescription.sdp if pc.localDescription else ""
    counts = {kind: sdp.count(f" typ {kind}") for kind in ("host", "srflx", "relay")}
    log = logger.warning if counts["relay"] == 0 else logger.info
    log("Talk call: {} local candidates {}", label, counts)
    return counts


def _send_status_data_channel_state(channel: Any) -> bool:
    """Broadcast the local Talk media state over an open WebRTC data channel.

    Talk's MCU forwards publisher data-channel messages to every subscriber.
    The Android client uses these exact messages to clear its muted microphone
    indicator; the signaling ``unmute`` message alone does not update that UI.
    """
    if channel is None or getattr(channel, "readyState", "") != "open":
        return False
    for message in _STATUS_DATA_CHANNEL_MESSAGES:
        channel.send(message)
    return True


def _send_data_channel_message(channel: Any, message: str) -> bool:
    """Send one Talk JSON message when the in-band status channel is open."""
    if channel is None or getattr(channel, "readyState", "") != "open":
        return False
    channel.send(message)
    return True


async def _wait_ice_complete(pc: Any) -> None:
    """Wait for ICE gathering because aiortc does not trickle outbound candidates.

    The final ``localDescription`` then contains every candidate before SDP is sent.
    """
    # aiortc 1.14's setLocalDescription() awaits all active gatherers and only
    # then exposes localDescription. With MAX_BUNDLE its aggregate state may
    # nevertheless remain ``new`` because discarded gatherers are not reflected
    # consistently, so the ready local SDP is the authoritative signal.
    if getattr(pc, "localDescription", None) is not None:
        return
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def _on_state() -> None:  # pyright: ignore[reportUnusedFunction]
        if pc.iceGatheringState == "complete":
            done.set()

    # Gathering can complete between the initial check and callback
    # registration (especially with MAX_BUNDLE and a warm TURN allocation).
    # Recheck after installing the listener so the completion cannot be lost.
    if pc.iceGatheringState == "complete":
        done.set()
    try:
        await asyncio.wait_for(done.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "Talk call: ICE gathering state did not become complete; using the available local SDP"
        )


class _CallHandle:
    def __init__(self) -> None:
        self.ws: Any = None
        self.pc_pub: Any = None
        self.subs: Dict[str, Any] = {}                       # Remote session ID -> pc_sub.
        self.pending_offers: set[str] = set()
        self.in_queue: "asyncio.Queue[AudioFrame]" = asyncio.Queue()
        self.inbound_ready = asyncio.Event()
        self.in_frames = 0
        self.in_signal_frames = 0
        self.out_frames = 0
        self.sig_session: str = ""                           # Our signaling session (hello).
        self.nc_session: str = ""                            # Our Nextcloud session (join_call).
        self.hpb_url: str = ""
        self.resume_id: str = ""
        self.server_features: set[str] = set()
        self.ws_ready = asyncio.Event()
        self.ws_send_lock = asyncio.Lock()
        self.pending_signaling_messages: List[Dict[str, Any]] = []
        self.tasks: List["asyncio.Task[None]"] = []
        self.ice_servers: List[Any] = []
        self.out_track: Any = None                           # Outbound publisher audio track.
        self.out_status_channel: Any = None                  # MCU status broadcast channel.
        self.pending_status_messages: List[str] = []
        self.speaking = False
        self.self_display_name = ""
        self.pub_sid: str = ""                               # Publisher WebRTC session ID.
        self.publisher_ready = asyncio.Event()
        self.publisher_connected = asyncio.Event()
        self.audio_advertised_at: float | None = None
        self.join_completed = False
        self.call_ended = asyncio.Event()
        self.remote_seen = False
        self.remote_actor_ids: set[str] = set()
        self.remote_call_flags: Dict[str, int] = {}
        self.sub_relay_retries: Dict[str, int] = {}           # Session -> renegotiations without relay.
        self.sub_status_channels: Dict[str, Any] = {}         # Session -> local status channel.
        self.sub_sids: Dict[str, str] = {}
        self.pending_remote_candidates: Dict[
            tuple[str, str], List[Dict[str, Any] | None]
        ] = {}
        self.media_state_tasks: Dict[str, "asyncio.Task[None]"] = {}


class TalkCall(CallTransport):
    kind = "nextcloud_talk"

    def __init__(
        self,
        client: NextcloudTalkClient,
        self_id: str,
        nextcloud_url: str,
        hpb_url: str,
        *,
        connection_id: int | None = None,
        start_call: bool = False,
        ring_attempts: int = 1,
        ring_interval_s: float = 8.0,
    ) -> None:
        self._client = client
        self._self_id = self_id
        self._nextcloud_url = nextcloud_url.rstrip("/")
        self._hpb_url = hpb_url
        self._connection_id = connection_id
        self._room_id = ""
        self._start_call = start_call
        self._ring_attempts = max(1, ring_attempts)
        self._ring_interval_s = max(1.0, ring_interval_s)

    @classmethod
    async def from_connection_id(
        cls,
        connection_id: int,
        hpb_url: str = "",
        *,
        start_call: bool = False,
        ring_attempts: int = 1,
        ring_interval_s: float = 8.0,
    ) -> "TalkCall":
        """Build call transport from a Nextcloud Talk connection.

        This mirrors ``NextcloudTalkMessenger.from_connection_id`` and resolves
        the HPB URL from an explicit override, connection settings, then Talk
        signaling settings. Calls require an HPB; internal mode has no WebRTC.
        """
        from .signaling import extract_hpb_url, normalize_hpb_url

        config = await resolve_nextcloud_connection(connection_id)

        logger.info(
            "Talk call: configuration connection={} nextcloud_host={} login={} self_id={} authenticated={}",
            connection_id,
            _host_label(config.base_url),
            config.login,
            config.self_id,
            bool(config.password),
        )

        client = NextcloudTalkClient(
            base_url=config.base_url,
            login=config.login,
            password=config.password,
        )
        hpb_url = (
            normalize_hpb_url(hpb_url)
            or normalize_hpb_url(runtime_settings.MESSENGER_NEXTCLOUD_TALK_HPB_URL)
        )
        if not hpb_url:
            try:
                signaling_settings = await client.get_signaling_settings()
                hpb_url = extract_hpb_url(signaling_settings)
                logger.debug(
                    "Talk call: HPB discovery settings_keys={} hpb={}",
                    sorted(signaling_settings.keys()),
                    hpb_url or "<empty>",
                )
            except Exception:
                logger.opt(exception=True).debug("Talk call: HPB discovery failed")
                hpb_url = ""
        if not hpb_url:
            raise ValueError(_error("talk_hpb_required"))

        return cls(
            client=client,
            self_id=config.self_id,
            nextcloud_url=config.base_url,
            hpb_url=hpb_url,
            connection_id=connection_id,
            start_call=start_call,
            ring_attempts=ring_attempts,
            ring_interval_s=ring_interval_s,
        )

    # -- Lifecycle -------------------------------------------------------------

    async def join(self, room_id: str) -> _CallHandle:
        """Join a Talk call and clean up partial signaling sessions on failure."""
        self._room_id = room_id
        handle = _CallHandle()
        try:
            return await self._join(handle, room_id)
        except BaseException:
            await self.leave(handle)
            raise

    async def _join(self, handle: _CallHandle, room_id: str) -> _CallHandle:
        import websockets

        # 1. Create an active Talk session before /call/{token}.
        session = await self._client.join_call(room_id)
        handle.nc_session = session.get("sessionId", "")
        if not handle.nc_session:
            raise RuntimeError(_error("session_missing", room_id=room_id))
        logger.info("Talk call: session Nextcloud active room={} session={}", room_id, _session_fp(handle.nc_session))

        settings = await self._client.get_signaling_settings(room_id)
        handle.ice_servers = self._ice_servers_from_settings(settings)
        await self._assert_can_publish_audio(room_id)
        room_hpb_url = extract_hpb_url(settings) or self._hpb_url
        handle.hpb_url = room_hpb_url
        handle.self_display_name = self._self_id
        if room_hpb_url != self._hpb_url:
            logger.info("Talk call: room-specific HPB room={} hpb={}", room_id, room_hpb_url)

        # 2. Connect to the HPB and obtain our signaling session through hello.
        handle.ws = await websockets.connect(room_hpb_url, subprotocols=[_SUBPROTOCOL])  # type: ignore[list-item]
        await self._send_direct(handle, build_hello_message(
            self._nextcloud_url,
            settings,
            legacy_room_token=room_id,
            legacy_session_id=handle.nc_session,
            legacy_user_id=self._self_id,
            client_features=_CLIENT_FEATURES,
        ))
        hello_resp = await self._recv_until(handle, "hello", timeout=10.0)
        hello = as_dict(hello_resp.get("hello"))
        handle.sig_session = str(hello.get("sessionid") or "")
        handle.resume_id = str(hello.get("resumeid") or "")
        handle.server_features = {
            str(feature)
            for feature in as_list(as_dict(hello.get("server")).get("features"))
            if feature
        }
        if "mcu" not in handle.server_features:
            raise RuntimeError(_error("talk_mcu_required"))
        logger.info(
            "Talk call: session signaling={} nextcloud={} resume={} features={}",
            _session_fp(handle.sig_session),
            _session_fp(handle.nc_session),
            bool(handle.resume_id),
            sorted(handle.server_features),
        )

        # 3. Join the signaling room before /call/{token} so the HPB associates
        # inCall state with this WebSocket and later permits requestoffer.
        room_join = build_room_join_message(room_id, handle.nc_session, settings)
        federation = as_dict(as_dict(room_join.get("room")).get("federation"))
        logger.info(
            "Talk call: join room HPB room={} self_id={} settings_user={} settings_keys={} federation_keys={}",
            room_id,
            self._self_id,
            as_dict(settings).get("userId"),
            sorted(as_dict(settings).keys()),
            sorted(federation.keys()),
        )
        await self._send_direct(handle, room_join)
        visible_prejoined = False
        try:
            await self._recv_until(handle, "room", timeout=10.0)
        except RuntimeError as exc:
            if "no_such_room" in str(exc):
                visible_prejoined = await self._retry_room_join_after_call_api(
                    handle,
                    room_id,
                    settings,
                )
                if visible_prejoined:
                    logger.info("Talk call: HPB room join succeeded after entering the Call API first")
                else:
                    await self._log_room_membership_diagnostic(room_id, settings, handle.nc_session)
                    raise
            else:
                raise

        # 4. From this point regular messages can be queued while an HPB
        # session is being resumed, just like Android's WebSocketInstance.
        handle.ws_ready.set()
        handle.tasks.append(asyncio.create_task(self._signaling_loop(handle), name="talk_call_sig"))
        handle.tasks.append(asyncio.create_task(self._keep_alive(handle), name="talk_call_ping"))

        # 5. Create the Janus feed before becoming visible in the Talk call,
        # then join once with WITH_AUDIO already set. Android only creates an
        # MCU subscriber for a *newly joined* participant that already carries
        # an audio/video flag; joining with flags=1 and later updating to 3
        # leaves that participant permanently muted on Android.
        await self._resolve_self_display_name(handle, room_id)
        visible = await self._publish_before_call_api_entry(
            handle,
            room_id,
            visible_prejoined=visible_prejoined,
            silent=not self._start_call,
        )
        handle.tasks.append(asyncio.create_task(
            self._broadcast_nick(handle),
            name="talk_call_nick",
        ))
        if self._start_call:
            handle.tasks.append(asyncio.create_task(
                self._ring_room_participants(room_id, only_if_visible=visible),
                name="talk_call_ring",
            ))
        handle.tasks.append(asyncio.create_task(
            self._monitor_remote_participants(handle, room_id),
            name="talk_call_participants_monitor",
        ))
        handle.join_completed = True
        return handle

    async def _publish_before_call_api_entry(
        self,
        handle: _CallHandle,
        room_id: str,
        *,
        visible_prejoined: bool,
        silent: bool,
    ) -> bool:
        """Publish first, then expose one Android-compatible flags=3 join event."""
        await self._publish(handle)
        try:
            await asyncio.wait_for(handle.publisher_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Talk call: publisher answer timed out before Call API entry"
            )
        if handle.publisher_ready.is_set():
            try:
                await asyncio.wait_for(
                    handle.publisher_connected.wait(),
                    timeout=_PUBLISHER_CONNECT_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Talk call: publisher transport did not connect within {}s "
                    "(connection={}, ice={}); advertising audio as a fallback",
                    _PUBLISHER_CONNECT_TIMEOUT_S,
                    getattr(handle.pc_pub, "connectionState", "unknown"),
                    getattr(handle.pc_pub, "iceConnectionState", "unknown"),
                )
        visible = visible_prejoined or await self._join_media_call_visible(
            room_id,
            silent=silent,
            flags=_CALL_FLAG_IN_CALL | _CALL_FLAG_WITH_AUDIO,
        )
        if visible:
            handle.audio_advertised_at = time.monotonic()
        return visible

    async def leave(self, handle: _CallHandle) -> None:
        await self._leave(handle, all_participants=False)

    async def terminate(self, handle: _CallHandle) -> None:
        """Terminate the whole Talk call after an explicit agent hangup."""

        await self._leave(handle, all_participants=True)

    async def _leave(
        self,
        handle: _CallHandle,
        *,
        all_participants: bool,
    ) -> None:
        if (
            all_participants
            and handle.join_completed
            and self._connection_id is not None
            and self._room_id
        ):
            from .call_listener import suppress_auto_answer

            suppress_auto_answer(
                self._connection_id,
                self._room_id,
                handle.remote_actor_ids,
            )
        handle.call_ended.set()
        handle.ws_ready.clear()
        if handle.ws is not None:
            try:
                await self._send_direct(handle, {"type": "bye", "bye": {}})
            except Exception as exc:
                logger.debug("Talk call: bye send failed during cleanup: {}", type(exc).__name__)
        for task in handle.tasks:
            task.cancel()
        if handle.tasks:
            await asyncio.gather(*handle.tasks, return_exceptions=True)
        for pc in [handle.pc_pub, *handle.subs.values()]:
            if pc is not None:
                try:
                    await pc.close()
                except Exception as exc:
                    logger.debug(
                        "Talk call: peer connection close failed during cleanup: {}",
                        type(exc).__name__,
                    )
        if handle.ws is not None:
            try:
                await handle.ws.close()
            except Exception as exc:
                logger.debug(
                    "Talk call: signaling websocket close failed during cleanup: {}",
                    type(exc).__name__,
                )
        try:
            await self._leave_media_call_visible(
                all_participants=all_participants,
            )
        finally:
            await self._client.aclose()

    # -- Audio stream (CallTransport interface) --------------------------------

    def inbound_audio(self, handle: _CallHandle) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            while True:
                yield await handle.in_queue.get()
        return _gen()

    async def wait_ended(self, handle: _CallHandle) -> None:
        await handle.call_ended.wait()

    async def send_audio(self, handle: _CallHandle, frames: AsyncIterator[AudioFrame]) -> None:
        async for frame in frames:
            if handle.out_track is not None:
                await handle.out_track.push(frame.pcm)
                handle.out_frames += 1
                if handle.out_frames == 1 or handle.out_frames % 250 == 0:
                    logger.info(
                        "Talk call: queued outbound audio frames={} bytes_in={} frame_bytes={}",
                        handle.out_frames,
                        len(frame.pcm),
                        _PCM_FRAME_BYTES,
                    )

    async def interrupt_output(self, handle: _CallHandle) -> None:
        if handle.out_track is not None:
            cleared_frames = handle.out_track.clear()
            logger.info(
                "Talk call: outbound audio interrupted; cleared {} queued frame(s)",
                cleared_frames,
            )

    async def wait_output_ready(self, handle: _CallHandle) -> None:
        """Let Talk subscribers attach before emitting the first greeting."""
        advertised_at = handle.audio_advertised_at
        if advertised_at is None:
            return
        remaining = _OUTBOUND_SUBSCRIBER_GRACE_S - (
            time.monotonic() - advertised_at
        )
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(handle.call_ended.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            pass

    async def wait_input_ready(self, handle: _CallHandle) -> None:
        """Do not invite speech until the MCU subscriber yields remote PCM."""
        ready = asyncio.create_task(handle.inbound_ready.wait())
        ended = asyncio.create_task(handle.call_ended.wait())
        try:
            await asyncio.wait(
                (ready, ended),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            ready.cancel()
            ended.cancel()
            await asyncio.gather(ready, ended, return_exceptions=True)
        if not handle.inbound_ready.is_set():
            raise ConnectionError(
                "Talk call ended before the remote audio stream became available"
            )

    async def wait_output_drained(self, handle: _CallHandle) -> None:
        if handle.out_track is not None:
            await handle.out_track.wait_drained()

    # -- Publisher -------------------------------------------------------------

    async def _publish(self, handle: _CallHandle) -> None:
        from aiortc import RTCPeerConnection

        pc: Any = None
        out_track: Any = None
        status_channel: Any = None
        # TURN allocations fail transiently, and without a relay candidate the
        # media leg is usually doomed; regather once before sending the offer.
        for attempt in (1, 2):
            pc = RTCPeerConnection(
                self._rtc_config(
                    handle,
                    turn_attempt=attempt - 1,
                    max_bundle=True,
                )
            )
            out_track = _build_out_track(
                lambda speaking: self._set_local_speaking(handle, speaking)
            )
            pc.addTrack(out_track)
            # Talk clients always negotiate an in-band "status" channel before
            # creating their publisher offer. Janus broadcasts messages sent on
            # this channel to all subscriber peer connections.
            status_channel = pc.createDataChannel(_STATUS_DATA_CHANNEL_LABEL)
            await pc.setLocalDescription(await pc.createOffer())
            await _wait_ice_complete(pc)
            counts = _log_local_candidates("publisher", pc)
            if counts["relay"] > 0 or not _has_turn_server(handle.ice_servers) or attempt == 2:
                break
            logger.warning("Talk call: publisher gathered no TURN relay candidate; regathering")
            try:
                await pc.close()
            except Exception as exc:
                logger.debug(
                    "Talk call: publisher regather close failed: {}",
                    type(exc).__name__,
                )
        handle.pc_pub = pc
        handle.out_track = out_track
        handle.out_status_channel = status_channel
        self._broadcast_local_data_state(handle)

        @pc.on("connectionstatechange")
        def _on_publisher_connection_state() -> None:  # pyright: ignore[reportUnusedFunction]
            state = pc.connectionState
            logger.info(
                "Talk call: publisher connection state={} ice={}",
                state,
                pc.iceConnectionState,
            )
            if state == "connected":
                handle.publisher_connected.set()

        @pc.on("iceconnectionstatechange")
        def _on_publisher_ice_state() -> None:  # pyright: ignore[reportUnusedFunction]
            state = pc.iceConnectionState
            logger.info("Talk call: publisher ICE state={}", state)
            if state in {"connected", "completed"}:
                handle.publisher_connected.set()

        @status_channel.on("open")
        def _on_status_channel_open() -> None:  # pyright: ignore[reportUnusedFunction]
            if handle.out_status_channel is not status_channel:
                return
            pending = handle.pending_status_messages
            handle.pending_status_messages = []
            for message in pending:
                status_channel.send(message)
            logger.info(
                "Talk call: publisher data channel opened; flushed {} status message(s)",
                len(pending),
            )

        @status_channel.on("close")
        def _on_status_channel_close() -> None:  # pyright: ignore[reportUnusedFunction]
            logger.info("Talk call: publisher data channel closed")

        sid = uuid.uuid4().hex
        handle.pub_sid = sid
        await self._send(handle, {
            "type": "message",
            "message": {
                "recipient": {"type": "session", "sessionid": handle.sig_session},
                "data": {
                    "to": handle.sig_session, "type": "offer", "sid": sid, "roomType": _ROOM_TYPE,
                    "payload": {"type": "offer", "sdp": pc.localDescription.sdp},
                },
            },
        })
        logger.info("Talk call: sent publisher offer (sid={})", sid)

    def _send_or_queue_status(self, handle: _CallHandle, message: str) -> None:
        """Mirror Android's reliable queue for the publisher status channel."""
        if _send_data_channel_message(handle.out_status_channel, message):
            return
        handle.pending_status_messages.append(message)

    def _broadcast_local_data_state(self, handle: _CallHandle) -> None:
        if not handle.speaking and _send_status_data_channel_state(
            handle.out_status_channel
        ):
            return
        messages = (
            _STATUS_DATA_CHANNEL_MESSAGES[0],
            _STATUS_SPEAKING_MESSAGE
            if handle.speaking
            else _STATUS_STOPPED_SPEAKING_MESSAGE,
            _STATUS_DATA_CHANNEL_MESSAGES[2],
        )
        for message in messages:
            self._send_or_queue_status(handle, message)

    def _set_local_speaking(self, handle: _CallHandle, speaking: bool) -> None:
        if speaking == handle.speaking:
            return
        handle.speaking = speaking
        self._send_or_queue_status(
            handle,
            _STATUS_SPEAKING_MESSAGE if speaking else _STATUS_STOPPED_SPEAKING_MESSAGE,
        )

    async def _broadcast_nick(self, handle: _CallHandle) -> None:
        """Publish the local display name every second, as Talk Android does."""
        try:
            await handle.publisher_connected.wait()
            message = json.dumps(
                {
                    "type": "nickChanged",
                    "payload": {
                        "userid": self._self_id,
                        "name": handle.self_display_name or self._self_id,
                    },
                },
                separators=(",", ":"),
            )
            while not handle.call_ended.is_set():
                await asyncio.sleep(1.0)
                self._send_or_queue_status(handle, message)
        except asyncio.CancelledError:
            raise

    # -- Subscriber (hearing a participant) ------------------------------------

    async def _request_offer(self, handle: _CallHandle, publisher_session: str) -> None:
        await self._send(handle, {
            "type": "message",
            "message": {
                "recipient": {"type": "session", "sessionid": publisher_session},
                "data": {"type": "requestoffer", "roomType": _ROOM_TYPE},
            },
        })
        logger.info("Talk call: requestoffer → {}", _session_fp(publisher_session))

    async def _send_media_state(
        self,
        handle: _CallHandle,
        participant_session: str,
    ) -> None:
        """Tell a Talk client that this publisher has audio but no video.

        Talk normally sends these signaling messages from
        ``LocalStateBroadcasterMcu`` in addition to the Call API flags and its
        publisher data channel. Signaling keeps older clients compatible; the
        data channel drives the current Android microphone indicator.
        """
        self._broadcast_local_data_state(handle)
        for message_type, media_name in (("unmute", "audio"), ("mute", "video")):
            await self._send(handle, {
                "type": "message",
                "message": {
                    "recipient": {
                        "type": "session",
                        "sessionid": participant_session,
                    },
                    "data": {
                        "to": participant_session,
                        "type": message_type,
                        "roomType": _ROOM_TYPE,
                        "payload": {"name": media_name},
                    },
                },
            })

    def _ensure_media_state_broadcast(
        self,
        handle: _CallHandle,
        participant_session: str,
    ) -> None:
        if (
            not participant_session
            or participant_session == handle.sig_session
            or participant_session in handle.media_state_tasks
        ):
            return
        task = asyncio.create_task(
            self._broadcast_media_state(handle, participant_session),
            name="talk_call_media_state",
        )
        handle.media_state_tasks[participant_session] = task
        handle.tasks.append(task)

    async def _broadcast_media_state(
        self,
        handle: _CallHandle,
        participant_session: str,
    ) -> None:
        # Wait until our publisher is real whenever possible.  The timeout
        # mirrors the publisher-answer fallback in ``_join`` so older HPBs
        # still receive the compatibility announcements.
        try:
            await asyncio.wait_for(handle.publisher_ready.wait(), timeout=10.5)
        except asyncio.TimeoutError:
            pass

        for delay in _MEDIA_STATE_RETRY_DELAYS_S:
            if delay:
                await asyncio.sleep(delay)
            if (
                handle.call_ended.is_set()
                or not handle.remote_call_flags.get(participant_session, 0)
            ):
                return
            await self._send_media_state(handle, participant_session)
            logger.debug(
                "Talk call: advertised local media state audio=on video=off to {}",
                _session_fp(participant_session),
            )

    def _ensure_subscriber_offer(
        self,
        handle: _CallHandle,
        publisher_session: str,
        *,
        initial_delay_s: float | None = None,
    ) -> None:
        if (
            not publisher_session
            or publisher_session == handle.sig_session
            or publisher_session in handle.subs
            or publisher_session in handle.pending_offers
        ):
            return
        handle.pending_offers.add(publisher_session)
        handle.tasks.append(asyncio.create_task(
            self._request_offer_retries(
                handle,
                publisher_session,
                initial_delay_s=initial_delay_s,
            ),
            name="talk_call_request_offer",
        ))

    async def _request_offer_retries(
        self,
        handle: _CallHandle,
        publisher_session: str,
        *,
        initial_delay_s: float | None = None,
    ) -> None:
        try:
            # Media bits become visible as soon as Talk has local tracks, which
            # can precede the browser-to-Janus ICE connection. Rapid retries
            # only queue more work behind the HPB's pending subscriber join.
            await asyncio.sleep(
                _OFFER_INITIAL_DELAY_S
                if initial_delay_s is None
                else initial_delay_s
            )
            for attempt in range(1, _OFFER_MAX_ATTEMPTS + 1):
                if (
                    handle.ws is None
                    or handle.call_ended.is_set()
                    or publisher_session in handle.subs
                    or not (handle.remote_call_flags.get(publisher_session, 0) & _CALL_MEDIA_FLAGS)
                ):
                    return
                await self._request_offer(handle, publisher_session)
                if attempt < _OFFER_MAX_ATTEMPTS:
                    await asyncio.sleep(_OFFER_RETRY_INTERVAL_S)
            logger.warning(
                "Talk call: no subscriber offer after {} requestoffer attempts to {}",
                _OFFER_MAX_ATTEMPTS,
                _session_fp(publisher_session),
            )
        finally:
            handle.pending_offers.discard(publisher_session)

    async def _retry_subscriber_without_relay(
        self,
        handle: _CallHandle,
        participant_session: str,
        pc: Any,
        retries: int,
    ) -> None:
        retry_number = retries + 1
        delay = _SUBSCRIBER_RELAY_RETRY_DELAYS_S[
            min(retries, len(_SUBSCRIBER_RELAY_RETRY_DELAYS_S) - 1)
        ]
        logger.warning(
            "Talk call: no TURN relay candidate for subscriber {}; "
            "renegotiating attempt={} in {:.0f}s",
            _session_fp(participant_session),
            retry_number,
            delay,
        )
        # aiortc schedules its private connect coroutine from
        # setLocalDescription(). Let it enter RTCIceTransport.start() before
        # closing; otherwise the detached coroutine starts on a closed
        # transport and reports an unhandled InvalidStateError.
        await asyncio.sleep(0)
        if handle.subs.get(participant_session) is pc:
            await self._remove_subscriber(handle, participant_session)
        else:
            try:
                await pc.close()
            except Exception as exc:
                logger.debug(
                    "Talk call: discarded subscriber close failed: {}",
                    type(exc).__name__,
                )
        handle.sub_relay_retries[participant_session] = retry_number
        self._ensure_subscriber_offer(
            handle,
            participant_session,
            initial_delay_s=delay,
        )

    async def _refresh_subscriber_ice_servers(
        self,
        handle: _CallHandle,
    ) -> List[Any]:
        """Get a fresh TURN username for the subscriber media leg.

        Talk's TURN REST username changes between settings requests. Browser
        clients can consume the same short-lived username as the bot publisher
        when both join at nearly the same time. With a Coturn ``user-quota`` of
        two, the subscriber allocation is then rejected with error 486. Fetch
        settings again immediately before subscribing so this independent
        PeerConnection has an independent allocation quota.
        """
        try:
            settings = await self._client.get_signaling_settings(self._room_id)
            refreshed = self._ice_servers_from_settings(settings)
            if refreshed:
                logger.info("Talk call: refreshed ICE credentials for subscriber")
                return refreshed
            logger.warning(
                "Talk call: refreshed signaling settings contained no ICE servers; "
                "using join credentials"
            )
        except Exception as exc:
            logger.warning(
                "Talk call: could not refresh subscriber ICE credentials "
                "({}: {}); using join credentials",
                type(exc).__name__,
                exc,
            )
        return handle.ice_servers

    async def _on_remote_offer(self, handle: _CallHandle, frm: str, sid: str, sdp: str) -> None:
        from aiortc import RTCPeerConnection, RTCSessionDescription

        if not frm or not sdp:
            logger.debug("Talk call: ignored incomplete subscriber offer")
            return
        stale = handle.subs.pop(frm, None)
        handle.sub_status_channels.pop(frm, None)
        previous_sid = handle.sub_sids.pop(frm, "")
        if previous_sid and previous_sid != sid:
            handle.pending_remote_candidates.pop((frm, previous_sid), None)
        handle.sub_sids[frm] = sid
        retries = handle.sub_relay_retries.get(frm, 0)
        turn_attempt, max_bundle = _subscriber_ice_strategy(sdp, retries)
        subscriber_ice_servers = await self._refresh_subscriber_ice_servers(handle)
        pc = RTCPeerConnection(
            self._rtc_config(
                handle,
                turn_attempt=turn_attempt,
                max_bundle=max_bundle,
                ice_servers=subscriber_ice_servers,
            )
        )
        logger.info(
            "Talk call: subscriber ICE strategy remote={} media={} bundle={} offer={}",
            _session_fp(frm),
            sum(line.strip().startswith("m=") for line in sdp.splitlines()),
            "max-bundle" if max_bundle else "balanced",
            _subscriber_offer_profile(sdp),
        )
        handle.subs[frm] = pc
        if stale is not None:
            try:
                await stale.close()
            except Exception as exc:
                logger.debug(
                    "Talk call: stale subscriber close failed: {}",
                    type(exc).__name__,
                )

        @pc.on("datachannel")
        def _on_remote_data_channel(channel: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            logger.info(
                "Talk call: subscriber remote data channel label={} from {}",
                channel.label,
                _session_fp(frm),
            )

            @channel.on("message")
            def _on_data_message(message: Any) -> None:  # pyright: ignore[reportUnusedFunction]
                logger.debug(
                    "Talk call: subscriber data message from {} payload={}",
                    _session_fp(frm),
                    message,
                )

        @pc.on("track")
        def _on_track(track: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            if track.kind == "audio":
                logger.info(
                    "Talk call: received remote audio track from {}",
                    _session_fp(frm),
                )
                handle.tasks.append(asyncio.create_task(self._drain_inbound(track, handle)))

        @pc.on("connectionstatechange")
        async def _on_connection_state() -> None:  # pyright: ignore[reportUnusedFunction]
            logger.info(
                "Talk call: subscriber connection state={} ice={} remote={}",
                pc.connectionState,
                pc.iceConnectionState,
                _session_fp(frm),
            )
            # All media flows through TURN here; a failed subscriber leg means
            # dead air, so drop the connection and negotiate a fresh offer.
            if pc.connectionState != "failed" or handle.call_ended.is_set():
                return
            logger.warning(
                "Talk call: subscriber connection to {} failed; requesting a fresh offer",
                _session_fp(frm),
            )
            if handle.subs.get(frm) is pc:
                await self._remove_subscriber(handle, frm)
            else:
                try:
                    await pc.close()
                except Exception as exc:
                    logger.debug(
                        "Talk call: failed subscriber close failed: {}",
                        type(exc).__name__,
                    )
            self._ensure_subscriber_offer(handle, frm)

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        # Janus already offers an application m-line. Reuse the SCTP transport
        # aiortc created from that offer instead of creating one before BUNDLE
        # selects its primary transport. The premature transport leaves browser
        # audio+video+data offers without a usable TURN gatherer.
        local_status_channel = pc.createDataChannel(_STATUS_DATA_CHANNEL_LABEL)
        handle.sub_status_channels[frm] = local_status_channel

        @local_status_channel.on("open")
        def _on_local_status_channel_open() -> None:  # pyright: ignore[reportUnusedFunction]
            logger.info(
                "Talk call: subscriber local data channel opened for {}",
                _session_fp(frm),
            )

        await self._flush_remote_candidates(handle, frm, sid, pc)
        await pc.setLocalDescription(await pc.createAnswer())
        await _wait_ice_complete(pc)
        counts = _log_local_candidates("subscriber", pc)
        if counts["relay"] == 0 and _has_turn_server(subscriber_ice_servers):
            await self._retry_subscriber_without_relay(
                handle,
                frm,
                pc,
                retries,
            )
            return
        handle.sub_relay_retries.pop(frm, None)
        await self._send(handle, {
            "type": "message",
            "message": {
                "recipient": {"type": "session", "sessionid": frm},
                "data": {
                    "to": frm, "type": "answer", "sid": sid, "roomType": _ROOM_TYPE,
                    "payload": {"type": "answer", "sdp": pc.localDescription.sdp},
                },
            },
        })
        logger.info(
            "Talk call: answer subscriber → {} (sid={})",
            _session_fp(frm),
            sid,
        )

    async def _drain_inbound(self, track: Any, handle: _CallHandle) -> None:
        import av
        from aiortc.mediastreams import MediaStreamError

        resampler = av.AudioResampler(format="s16", layout="mono", rate=DEFAULT_SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                for r in resampler.resample(frame):
                    pcm = _pcm_bytes(r)
                    handle.in_frames += 1
                    if any(pcm):
                        handle.in_signal_frames += 1
                    if handle.in_frames == 1 or handle.in_frames % 250 == 0:
                        logger.info(
                            "Talk call: inbound audio frames={} signal_frames={} bytes={} queue={}",
                            handle.in_frames,
                            handle.in_signal_frames,
                            len(pcm),
                            handle.in_queue.qsize(),
                        )
                    handle.inbound_ready.set()
                    handle.in_queue.put_nowait(AudioFrame(pcm=pcm))
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            logger.debug("Talk call: inbound media track ended")
        except Exception:
            logger.opt(exception=True).debug("Talk call: inbound stream ended")

    # -- Signaling loop --------------------------------------------------------

    async def _signaling_loop(self, handle: _CallHandle) -> None:
        while not handle.call_ended.is_set():
            try:
                await self._signaling_loop_inner(handle)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                handle.ws_ready.clear()
                logger.warning(
                    "Talk call: signaling connection lost ({}: {}); "
                    "attempting HPB session resume",
                    type(exc).__name__,
                    exc,
                )
                if await self._resume_signaling(handle):
                    continue
                logger.warning(
                    "Talk call: HPB session could not be resumed; ending call"
                )
                handle.call_ended.set()
                return

    async def _resume_signaling(self, handle: _CallHandle) -> bool:
        """Resume the existing HPB session without rebuilding working WebRTC legs."""
        if not handle.resume_id or not handle.hpb_url:
            return False

        import websockets

        old_ws = handle.ws
        if old_ws is not None:
            try:
                await old_ws.close()
            except Exception as exc:
                logger.debug(
                    "Talk call: old signaling websocket close failed: {}",
                    type(exc).__name__,
                )

        expected_session = handle.sig_session
        for delay in _HPB_RESUME_DELAYS_S:
            if handle.call_ended.is_set():
                return False
            await asyncio.sleep(delay)
            try:
                ws = await websockets.connect(
                    handle.hpb_url,
                    subprotocols=[_SUBPROTOCOL],  # type: ignore[list-item]
                )
                handle.ws = ws
                await self._send_direct(
                    handle,
                    build_resume_hello_message(
                        handle.resume_id,
                        client_features=_CLIENT_FEATURES,
                    ),
                )
                hello_resp = await self._recv_until(handle, "hello", timeout=10.0)
                hello = as_dict(hello_resp.get("hello"))
                resumed_session = str(hello.get("sessionid") or "")
                if resumed_session != expected_session:
                    raise RuntimeError(
                        "HPB resume returned a different signaling session"
                    )
                handle.resume_id = str(hello.get("resumeid") or handle.resume_id)
                features = {
                    str(feature)
                    for feature in as_list(
                        as_dict(hello.get("server")).get("features")
                    )
                    if feature
                }
                if features:
                    handle.server_features = features
                handle.ws_ready.set()
                queued_count = len(handle.pending_signaling_messages)
                await self._flush_signaling_messages(handle)
                logger.info(
                    "Talk call: resumed HPB signaling session={} queued_messages={}",
                    _session_fp(handle.sig_session),
                    queued_count,
                )
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                handle.ws_ready.clear()
                if "no_such_session" in str(exc):
                    handle.resume_id = ""
                    return False
                logger.warning(
                    "Talk call: HPB resume attempt after {}s failed ({}: {})",
                    delay,
                    type(exc).__name__,
                    exc,
                )
                if handle.ws is not None:
                    try:
                        await handle.ws.close()
                    except Exception as close_exc:
                        logger.debug(
                            "Talk call: failed resume websocket close failed: {}",
                            type(close_exc).__name__,
                        )
        return False

    async def _signaling_loop_inner(self, handle: _CallHandle) -> None:
        from aiortc import RTCSessionDescription

        while handle.ws is not None:
            raw = await handle.ws.recv()
            try:
                evt = json.loads(raw)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "Talk call: ignored malformed signaling frame error={}",
                    type(exc).__name__,
                )
                continue
            mtype = evt.get("type")
            logger.debug("Talk call WS ← {}", mtype)

            if mtype in {"welcome", "pong", "hello"}:
                continue

            if mtype == "bye":
                logger.info("Talk call: HPB ended the signaling session")
                handle.call_ended.set()
                return

            if mtype == "room":
                room = as_dict(evt.get("room"))
                logger.debug("Talk call room event: roomid={} properties_keys={}", room.get("roomid"), sorted(as_dict(room.get("properties")).keys()))
                continue

            if mtype == "event":
                ev = as_dict(evt.get("event"))
                logger.debug("Talk call event: target={} type={} keys={}", ev.get("target"), ev.get("type"), sorted(ev.keys()))
                if ev.get("target") == "participants" and ev.get("type") == "update":
                    updates_raw = ev.get("update")
                    updates = [as_dict(updates_raw)] if isinstance(updates_raw, dict) else as_list(updates_raw)
                    for upd_item in updates:
                        upd = as_dict(upd_item)
                        applies_to_all = upd.get("all") is True or str(
                            upd.get("all") or ""
                        ).lower() == "true"
                        if applies_to_all:
                            # Android ignores malformed/global updates that do
                            # not explicitly carry the lower-case ``incall``
                            # field; they are not a call-ended notification.
                            if "incall" not in upd:
                                continue
                            all_flags = _participant_call_flags(
                                {"inCall": upd.get("incall")}
                            )
                            if all_flags == 0:
                                logger.info(
                                    "Talk call: moderator ended the call for all"
                                )
                                await self._remove_all_subscribers(handle)
                                handle.call_ended.set()
                            continue
                        users_raw = upd.get("users")
                        users = [as_dict(users_raw)] if isinstance(users_raw, dict) else as_list(users_raw)
                        logger.debug(
                            "Talk call participants update: roomid={} changed={} users={}",
                            upd.get("roomid"),
                            upd.get("changed"),
                            [
                                {
                                    "sessionId": _session_fp(
                                        u.get("sessionId") or u.get("sessionid")
                                    ),
                                    "nextcloudSessionId": _session_fp(
                                        u.get("nextcloudSessionId")
                                    ),
                                    "userid": u.get("userid") or u.get("userId"),
                                    "inCall": u.get("inCall"),
                                    "flags": u.get("flags"),
                                }
                                for u in users
                            ],
                        )
                        for u in users:
                            sess = str(
                                u.get("sessionId") or u.get("sessionid") or ""
                            )
                            if not sess or sess == handle.sig_session:
                                continue
                            call_flags = _participant_call_flags(u)
                            previous_flags = handle.remote_call_flags.get(sess)
                            handle.remote_call_flags[sess] = call_flags
                            if sess and previous_flags != call_flags:
                                logger.info(
                                    "Talk call: remote media state actor={} session={} "
                                    "flags={} audio={} video={}",
                                    u.get("userid") or u.get("userId") or u.get("actorId"),
                                    _session_fp(sess),
                                    call_flags,
                                    bool(call_flags & _CALL_FLAG_WITH_AUDIO),
                                    bool(call_flags & _CALL_FLAG_WITH_VIDEO),
                                )
                            if call_flags:
                                self._ensure_media_state_broadcast(handle, sess)
                            else:
                                state_task = handle.media_state_tasks.pop(sess, None)
                                if state_task is not None:
                                    state_task.cancel()
                                await self._remove_subscriber(handle, sess)
                            if _participant_has_media_stream(u):
                                self._ensure_subscriber_offer(handle, sess)
                            elif sess in handle.subs:
                                await self._remove_subscriber(handle, sess)
                continue

            if mtype == "message":
                message = as_dict(evt.get("message"))
                data = as_dict(message.get("data"))
                dtype = data.get("type")
                frm = str(
                    data.get("from")
                    or as_dict(message.get("sender")).get("sessionid", "")
                )
                sid = str(data.get("sid") or "")
                room_type = str(data.get("roomType") or _ROOM_TYPE)
                payload = as_dict(data.get("payload"))
                if room_type != _ROOM_TYPE and dtype in {
                    "offer",
                    "answer",
                    "candidate",
                    "endOfCandidates",
                }:
                    logger.debug(
                        "Talk call: ignored {} for roomType={} from {}",
                        dtype,
                        room_type,
                        _session_fp(frm),
                    )
                    continue
                if (
                    dtype == "answer"
                    and handle.pc_pub is not None
                    and frm == handle.sig_session
                    and (not sid or sid == handle.pub_sid)
                ):
                    await handle.pc_pub.setRemoteDescription(
                        RTCSessionDescription(sdp=payload.get("sdp", ""), type="answer")
                    )
                    await self._flush_remote_candidates(
                        handle,
                        frm,
                        sid or handle.pub_sid,
                        handle.pc_pub,
                    )
                    handle.publisher_ready.set()
                    logger.info("Talk call: received publisher answer")
                elif dtype == "offer":
                    await self._on_remote_offer(
                        handle,
                        frm,
                        sid,
                        str(payload.get("sdp") or ""),
                    )
                elif dtype == "candidate":
                    await self._add_candidate(
                        handle,
                        frm,
                        sid,
                        as_dict(payload.get("candidate")),
                    )
                elif dtype == "endOfCandidates":
                    await self._add_candidate(handle, frm, sid, None)
                else:
                    logger.debug(
                        "Talk call message ignored: type={} from={} data_keys={} payload_keys={}",
                        dtype,
                        frm,
                        sorted(data.keys()),
                        sorted(payload.keys()),
                    )
                continue

            if mtype == "error":
                error = as_dict(evt.get("error"))
                if str(error.get("code") or "") in {
                    "no_such_session",
                    "hello_expected",
                }:
                    raise RuntimeError(_error("hpb_error", error=error or evt))
                logger.warning("Talk call WS error: {}", error or evt)
                continue

    async def _monitor_remote_participants(self, handle: _CallHandle, room_id: str) -> None:
        """Watch the Call API and end the call once every human has left."""
        try:
            while not handle.call_ended.is_set():
                await self._refresh_remote_participants(handle, room_id)
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).debug("Talk call: participant monitor stopped")

    async def _refresh_remote_participants(self, handle: _CallHandle, room_id: str) -> None:
        participants = await self._client.get_call_participants(room_id)
        remote_actor_ids = {
            str(p.get("actorId") or p.get("userId") or "")
            for p in participants
            if str(p.get("actorId") or p.get("userId") or "")
            and str(p.get("actorId") or p.get("userId") or "") != self._self_id
        }
        if remote_actor_ids != handle.remote_actor_ids:
            logger.info(
                "Talk call: active remote participants room={} actors={}",
                room_id,
                sorted(remote_actor_ids),
            )
            handle.remote_actor_ids = remote_actor_ids
        if remote_actor_ids:
            handle.remote_seen = True
            return
        if handle.remote_seen:
            logger.info("Talk call: no remote participants remain; detected call end")
            handle.call_ended.set()

    async def _resolve_self_display_name(
        self,
        handle: _CallHandle,
        room_id: str,
    ) -> None:
        """Resolve the name used in Android's periodic ``nickChanged`` message."""
        try:
            participants = await self._client.get_room_participants(room_id)
        except Exception:
            logger.opt(exception=True).debug(
                "Talk call: unable to resolve local display name"
            )
            return
        for participant in participants:
            actor_id = str(
                participant.get("actorId") or participant.get("userId") or ""
            )
            if actor_id != self._self_id:
                continue
            handle.self_display_name = str(
                participant.get("displayName")
                or participant.get("name")
                or self._self_id
            )
            return

    async def _assert_can_publish_audio(self, room_id: str) -> None:
        """Honor Talk's PUBLISH_AUDIO participant permission before advertising it."""
        try:
            rooms = await self._client.get_rooms()
        except Exception:
            logger.opt(exception=True).debug(
                "Talk call: unable to check publish-audio permission"
            )
            return
        room = next(
            (
                candidate
                for candidate in rooms
                if str(candidate.get("token") or "") == room_id
            ),
            None,
        )
        if room is None or room.get("permissions") is None:
            return
        try:
            permissions = int(room["permissions"])
        except (TypeError, ValueError):
            return
        # Older Talk versions expose the model default (0) without supporting
        # conversation permissions; Android treats audio as allowed there.
        if permissions == 0:
            return
        if permissions & _PARTICIPANT_PERMISSION_PUBLISH_AUDIO:
            return
        raise PermissionError(_error("talk_publish_audio_forbidden"))

    async def _log_room_membership_diagnostic(
        self,
        room_id: str,
        settings: Dict[str, Any],
        session_id: str,
    ) -> None:
        try:
            rooms = await self._client.get_rooms()
            known_room = next((room for room in rooms if str(room.get("token") or "") == room_id), None)
            participants: list[dict[str, Any]] = []
            if known_room is not None:
                try:
                    participants = await self._client.get_room_participants(room_id)
                except Exception:
                    participants = []
            logger.error(
                "Talk call: HPB rejected room join room={} self_id={} settings_user={} "
                "known_room={} rooms_count={} participants={} refused_session={}",
                room_id,
                self._self_id,
                settings.get("userId"),
                _room_diag(known_room) if known_room is not None else None,
                len(rooms),
                [
                    {
                        "actorId": p.get("actorId") or p.get("userId"),
                        "actorType": p.get("actorType"),
                        "attendeeId": p.get("attendeeId"),
                        "displayName": p.get("displayName") or p.get("name"),
                        "inCall": p.get("inCall"),
                        "lastPing": p.get("lastPing"),
                        "sessionIds": [_session_fp(s) for s in as_list(p.get("sessionIds"))],
                        "sessionId": _session_fp(p.get("sessionId")),
                    }
                    for p in participants
                ],
                _session_fp(session_id),
            )
        except Exception as diag_exc:
            logger.warning(
                "Talk call: room-membership diagnostic failed room={} ({}: {})",
                room_id,
                type(diag_exc).__name__,
                diag_exc,
            )

    async def _retry_room_join_after_call_api(
        self,
        handle: _CallHandle,
        room_id: str,
        settings: Dict[str, Any],
    ) -> bool:
        if not self._start_call:
            return False
        logger.warning(
            "Talk call: HPB returned no_such_room before Call API room={}; entering Call API then retrying",
            room_id,
        )
        # This path only starts a previously nonexistent HPB room. No remote
        # participant can request the feed yet, so joining directly with audio
        # is safe and ensures later Android participants see flags=3 initially.
        if not await self._join_media_call_visible(
            room_id,
            silent=False,
            flags=_CALL_FLAG_IN_CALL | _CALL_FLAG_WITH_AUDIO,
        ):
            return False
        session = await self._client.join_call(room_id)
        session_id = session.get("sessionId", "")
        if not session_id:
            logger.warning("Talk call: HPB retry unavailable; no sessionId after Call API room={}", room_id)
            return False
        handle.nc_session = session_id
        retry_join = build_room_join_message(room_id, handle.nc_session, settings)
        await self._send_direct(handle, retry_join)
        try:
            await self._recv_until(handle, "room", timeout=10.0)
            return True
        except Exception as exc:
            logger.warning(
                "Talk call: HPB room-join retry after Call API failed room={} ({}: {})",
                room_id,
                type(exc).__name__,
                exc,
            )
            return False

    async def _remove_subscriber(
        self,
        handle: _CallHandle,
        participant_session: str,
    ) -> None:
        pc = handle.subs.pop(participant_session, None)
        handle.sub_status_channels.pop(participant_session, None)
        handle.sub_sids.pop(participant_session, None)
        handle.sub_relay_retries.pop(participant_session, None)
        handle.pending_offers.discard(participant_session)
        for key in tuple(handle.pending_remote_candidates):
            if key[0] == participant_session:
                handle.pending_remote_candidates.pop(key, None)
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                logger.opt(exception=True).debug(
                    "Talk call: ignored subscriber close failure"
                )

    async def _remove_all_subscribers(self, handle: _CallHandle) -> None:
        for participant_session in tuple(handle.subs):
            await self._remove_subscriber(handle, participant_session)

    def _candidate_peer(
        self,
        handle: _CallHandle,
        frm: str,
        sid: str,
    ) -> Any:
        if frm == handle.sig_session:
            if sid and sid != handle.pub_sid:
                return None
            return handle.pc_pub
        current_sid = handle.sub_sids.get(frm)
        if current_sid is None or (sid and current_sid and sid != current_sid):
            return None
        return handle.subs.get(frm)

    async def _add_candidate(
        self,
        handle: _CallHandle,
        frm: str,
        sid: str,
        cand: Dict[str, Any] | None,
    ) -> None:
        """Apply or buffer a remote candidate until its SDP has been installed."""
        if frm == handle.sig_session and sid and sid != handle.pub_sid:
            logger.debug("Talk call: ignored candidate for stale publisher sid={}", sid)
            return
        current_sid = handle.sub_sids.get(frm)
        if current_sid is not None and sid and current_sid and sid != current_sid:
            logger.debug(
                "Talk call: ignored candidate for stale subscriber sid={} from {}",
                sid,
                _session_fp(frm),
            )
            return
        pc = self._candidate_peer(handle, frm, sid)
        if pc is None or getattr(pc, "remoteDescription", None) is None:
            handle.pending_remote_candidates.setdefault((frm, sid), []).append(cand)
            return
        await self._apply_candidate(pc, cand)

    async def _flush_remote_candidates(
        self,
        handle: _CallHandle,
        frm: str,
        sid: str,
        pc: Any,
    ) -> None:
        # Older signaling servers omitted sid, so drain both the exact session
        # bucket and the legacy one once the remote description is available.
        for key in dict.fromkeys(((frm, sid), (frm, ""))):
            candidates = handle.pending_remote_candidates.pop(key, [])
            for candidate in candidates:
                await self._apply_candidate(pc, candidate)

    async def _apply_candidate(
        self,
        pc: Any,
        cand: Dict[str, Any] | None,
    ) -> None:
        if cand is None:
            await pc.addIceCandidate(None)
            return

        # The upstream documentation once misspelled "candidate" as
        # "candiate"; Android accepts the actual wire spelling and we keep the
        # historical alias for older HPBs.
        from aiortc.sdp import candidate_from_sdp

        cand_str = str(cand.get("candidate") or cand.get("candiate") or "")
        if not cand_str:
            return
        try:
            ice = candidate_from_sdp(
                cand_str.split(":", 1)[1]
                if cand_str.startswith("candidate:")
                else cand_str
            )
            ice.sdpMid = cand.get("sdpMid")
            ice.sdpMLineIndex = cand.get("sdpMLineIndex")
            await pc.addIceCandidate(ice)
        except Exception:
            logger.opt(exception=True).debug("Talk call: ignored candidate")

    # -- Helpers ---------------------------------------------------------------

    async def _join_media_call_visible(
        self,
        room_id: str,
        *,
        silent: bool,
        flags: int = _CALL_FLAG_IN_CALL,
    ) -> bool:
        """Ask Talk to display this account, initially without promised media."""
        try:
            res = await self._client.join_media_call(room_id, flags=flags, silent=silent)
            logger.info(
                "Talk call: entered Call API (silent={}, flags={}, {})",
                silent,
                flags,
                type(res).__name__,
            )
            participants = await self._client.get_call_participants(room_id)
            logger.debug("Talk call: Call API participants after join={}", [
                {
                    "actorType": p.get("actorType"),
                    "actorId": p.get("actorId"),
                    "displayName": p.get("displayName"),
                    "sessionId": _session_fp(p.get("sessionId")),
                    "participantFlags": p.get("participantFlags"),
                    "flags": p.get("flags"),
                }
                for p in participants
            ])
            return True
        except Exception as exc:
            logger.warning(
                "Talk call: visible Call API entry rejected ({}: {}); HPB media continues",
                type(exc).__name__,
                exc,
            )
            logger.opt(exception=True).debug("Talk call: visible Call API entry rejection details")
            return False

    async def _ring_room_participants(self, room_id: str, *, only_if_visible: bool) -> None:
        """Try to ring the room's other participants."""
        if not only_if_visible:
            logger.warning(
                "Talk call: skipping ring because Call API entry was rejected"
            )
            return
        for attempt in range(1, self._ring_attempts + 1):
            if attempt > 1:
                await asyncio.sleep(self._ring_interval_s)
            try:
                participants = await self._client.get_room_participants(room_id)
                call_participants = await self._client.get_call_participants(room_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Talk call: could not load participants for ringing ({}: {})",
                    type(exc).__name__,
                    exc,
                )
                logger.opt(exception=True).debug("Talk call: participant lookup failure details")
                return

            in_call_actor_ids = {
                str(p.get("actorId") or p.get("userId") or "")
                for p in call_participants
                if p.get("actorId") or p.get("userId")
            }
            targets: List[Dict[str, Any]] = []
            for participant in participants:
                actor_id = str(participant.get("actorId") or participant.get("userId") or "")
                actor_type = str(participant.get("actorType") or "")
                attendee_id = (
                    participant.get("attendeeId")
                    or participant.get("attendee_id")
                    or participant.get("participantId")
                    or participant.get("id")
                )
                if actor_id and actor_id == self._self_id:
                    continue
                if actor_type == "bots":
                    continue
                if isinstance(attendee_id, str) and attendee_id.isdigit():
                    attendee_id = int(attendee_id)
                if isinstance(attendee_id, int):
                    targets.append({
                        "attendeeId": attendee_id,
                        "actorId": actor_id,
                        "alreadyInCall": actor_id in in_call_actor_ids,
                        "displayName": participant.get("displayName") or participant.get("name") or "",
                    })

            if not targets:
                logger.info(
                    "Talk call: no ringable participant room={} participants={} call_participants={}",
                    room_id,
                    [
                        {
                            "actorId": p.get("actorId") or p.get("userId"),
                            "actorType": p.get("actorType"),
                            "attendeeId": p.get("attendeeId") or p.get("attendee_id") or p.get("participantId") or p.get("id"),
                            "displayName": p.get("displayName") or p.get("name"),
                        }
                        for p in participants
                    ],
                    [
                        {
                            "actorId": p.get("actorId") or p.get("userId"),
                            "sessionId": p.get("sessionId"),
                            "displayName": p.get("displayName") or p.get("name"),
                        }
                        for p in call_participants
                    ],
                )
                return

            logger.info(
                "Talk call: ring attempt {}/{} room={} targets={}",
                attempt,
                self._ring_attempts,
                room_id,
                targets,
            )
            for target in targets:
                attendee_id = int(target["attendeeId"])
                try:
                    await self._client.ring_call_participant(room_id, attendee_id)
                    logger.info("Talk call: sent call notification to attendee_id={}", attendee_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    details = _http_error_details(exc)
                    logger.warning(
                        "Talk call: call notification rejected room={} attendee_id={} actor={} "
                        "already_in_call={} ({}: {}){}",
                        room_id,
                        attendee_id,
                        target.get("actorId"),
                        target.get("alreadyInCall"),
                        type(exc).__name__,
                        exc,
                        f" details={details}" if details else "",
                    )
                    logger.opt(exception=True).debug("Talk call: call notification rejection details")

    async def _leave_media_call_visible(
        self,
        *,
        all_participants: bool,
    ) -> None:
        if not self._room_id:
            return
        try:
            await self._client.leave_media_call(
                self._room_id,
                all_participants=all_participants,
            )
            logger.info(
                "Talk call: {} Call API",
                "terminated" if all_participants else "left",
            )
        except Exception:
            logger.opt(exception=True).debug("Talk call: ignored Call API leave failure")

    def _rtc_config(
        self,
        handle: _CallHandle,
        *,
        turn_attempt: int = 0,
        max_bundle: bool = False,
        ice_servers: List[Any] | None = None,
    ) -> Any:
        from aiortc import RTCBundlePolicy, RTCConfiguration

        _install_turn_failure_logging()

        # aiortc supports only one TURN URL per ICE gatherer. Rotate the
        # flattened Android-style list between attempts so a failed UDP/TCP
        # endpoint does not get selected repeatedly.
        regular_servers: List[Any] = []
        turn_servers: List[Any] = []
        for server in handle.ice_servers if ice_servers is None else ice_servers:
            raw_server_urls: Any = getattr(server, "urls", "")
            values: List[Any] = (
                cast(List[Any], raw_server_urls)
                if isinstance(raw_server_urls, list)
                else [raw_server_urls]
            )
            if any(
                isinstance(url, str) and url.startswith(("turn:", "turns:"))
                for url in values
            ):
                turn_servers.append(server)
            else:
                regular_servers.append(server)
        if turn_servers:
            offset = turn_attempt % len(turn_servers)
            turn_servers = turn_servers[offset:] + turn_servers[:offset]

        # For our publisher, the local offer is created before Janus can bundle
        # audio and data. MAX_BUNDLE avoids a transient TURN allocation per
        # m-line. BALANCED remains the compatibility fallback for subscribers
        # whose Janus offer cannot use MAX_BUNDLE.
        return RTCConfiguration(
            iceServers=regular_servers + turn_servers,
            bundlePolicy=(
                RTCBundlePolicy.MAX_BUNDLE
                if max_bundle
                else RTCBundlePolicy.BALANCED
            ),
        )

    def _ice_servers_from_settings(self, settings: Dict[str, Any]) -> List[Any]:
        from aiortc import RTCIceServer
        servers: List[Any] = []
        for key in ("stunservers", "turnservers"):
            for s_item in as_list(settings.get(key)):
                s = as_dict(s_item)
                raw_urls = s.get("urls") or s.get("url")
                urls: List[Any] = (
                    cast(List[Any], raw_urls)
                    if isinstance(raw_urls, list)
                    else [raw_urls]
                )
                # Android creates one IceServer per URL. Keep the same shape so
                # _rtc_config can rotate the single TURN endpoint aiortc uses.
                for url in urls:
                    if not isinstance(url, str) or not url:
                        continue
                    servers.append(cast(Any, RTCIceServer(
                        urls=url,
                        username=s.get("username"),
                        credential=s.get("credential"),
                    )))
        return servers

    async def _send(self, handle: _CallHandle, obj: Dict[str, Any]) -> None:
        """Send now or queue until Android-style HPB session resume completes."""
        async with handle.ws_send_lock:
            if not handle.ws_ready.is_set() or handle.ws is None:
                handle.pending_signaling_messages.append(obj)
                return
            try:
                await self._send_direct(handle, obj)
            except Exception:
                handle.pending_signaling_messages.append(obj)
                handle.ws_ready.clear()
                try:
                    await handle.ws.close()
                except Exception as close_exc:
                    logger.debug(
                        "Talk call: failed websocket close failed: {}",
                        type(close_exc).__name__,
                    )

    async def _send_direct(
        self,
        handle: _CallHandle,
        obj: Dict[str, Any],
    ) -> None:
        if handle.ws is None:
            raise RuntimeError(_error("hpb_connection_closed"))
        await handle.ws.send(json.dumps(obj, separators=(",", ":")))

    async def _flush_signaling_messages(self, handle: _CallHandle) -> None:
        async with handle.ws_send_lock:
            pending = handle.pending_signaling_messages
            handle.pending_signaling_messages = []
            for index, message in enumerate(pending):
                try:
                    await self._send_direct(handle, message)
                except Exception:
                    handle.pending_signaling_messages.extend(pending[index:])
                    handle.ws_ready.clear()
                    raise

    async def _keep_alive(self, handle: _CallHandle) -> None:
        try:
            while not handle.call_ended.is_set():
                await asyncio.sleep(_HPB_PING_INTERVAL_S)
                if handle.ws_ready.is_set():
                    await self._send(handle, {"type": "ping"})
        except asyncio.CancelledError:
            raise

    async def _recv_until(self, handle: _CallHandle, mtype: str, timeout: float) -> Dict[str, Any]:
        async def _loop() -> Dict[str, Any]:
            while True:
                raw = await handle.ws.recv()
                try:
                    evt = json.loads(raw)
                except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
                    logger.warning(
                        "Talk call: ignored malformed frame while awaiting {} error={}",
                        mtype,
                        type(exc).__name__,
                    )
                    continue
                if evt.get("type") == mtype:
                    return evt
                if evt.get("type") == "error":
                    error = as_dict(evt.get("error"))
                    code = str(error.get("code") or "")
                    if mtype == "room" and code == "already_joined":
                        return evt
                    raise RuntimeError(_error("hpb_error", error=error))
        return await asyncio.wait_for(_loop(), timeout=timeout)

    def remote_user_ids(self, handle: Any) -> tuple[str, ...]:
        if not isinstance(handle, _CallHandle):
            return ()
        return tuple(sorted(value for value in handle.remote_actor_ids if value))

    def call_external_id(self, handle: Any) -> str:
        if not isinstance(handle, _CallHandle):
            return ""
        return handle.nc_session
