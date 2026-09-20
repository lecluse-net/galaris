"""Matrix VoIP v1 signaling and WebRTC audio transport."""

from __future__ import annotations

import asyncio
import fractions
import uuid
from typing import Any, AsyncIterator

import av
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack
from aiortc.sdp import candidate_from_sdp
from loguru import logger

from app.voice import AudioFrame, CallTransport
from app.voice.models import DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE
from core.util import as_dict, as_list

from .client import Matrix
from .events import MatrixEventSubscription, MatrixRoomEvent, matrix_event_bus

_FRAME_MS = 20
_SAMPLES_PER_FRAME = DEFAULT_SAMPLE_RATE * _FRAME_MS // 1_000
_BYTES_PER_SAMPLE = 2
_PCM_FRAME_BYTES = _SAMPLES_PER_FRAME * DEFAULT_CHANNELS * _BYTES_PER_SAMPLE
_INVITE_LIFETIME_MS = 60_000


def _pcm_bytes(frame: Any) -> bytes:
    expected = frame.samples * DEFAULT_CHANNELS * _BYTES_PER_SAMPLE
    return bytes(frame.planes[0])[:expected]


class _OutboundAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = bytearray()
        self._pts = 0
        self._drained = asyncio.Event()
        self._drained.set()

    def push(self, pcm: bytes) -> None:
        if len(pcm) % _BYTES_PER_SAMPLE:
            pcm = pcm[: -(len(pcm) % _BYTES_PER_SAMPLE)]
        if pcm:
            self._drained.clear()
            self._queue.put_nowait(pcm)

    def clear(self) -> int:
        cleared = len(self._buffer)
        self._buffer.clear()
        while True:
            try:
                cleared += len(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                self._drained.set()
                return (cleared + _PCM_FRAME_BYTES - 1) // _PCM_FRAME_BYTES

    async def wait_drained(self) -> None:
        await self._drained.wait()

    def _next_frame(self) -> bytes:
        while len(self._buffer) < _PCM_FRAME_BYTES:
            try:
                self._buffer.extend(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        pcm = bytes(self._buffer[:_PCM_FRAME_BYTES])
        del self._buffer[:_PCM_FRAME_BYTES]
        return pcm.ljust(_PCM_FRAME_BYTES, b"\x00")

    async def recv(self) -> av.AudioFrame:
        frame = av.AudioFrame(format="s16", layout="mono", samples=_SAMPLES_PER_FRAME)
        frame.sample_rate = DEFAULT_SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, DEFAULT_SAMPLE_RATE)
        frame.planes[0].update(self._next_frame())
        self._pts += frame.samples
        await asyncio.sleep(_FRAME_MS / 1_000)
        if not self._buffer and self._queue.empty():
            self._drained.set()
        return frame


class _MatrixCallHandle:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id
        self.call_id = ""
        self.local_party_id = uuid.uuid4().hex
        self.remote_party_id = ""
        self.remote_user_id = ""
        self.pc: RTCPeerConnection | None = None
        self.out_track = _OutboundAudioTrack()
        self.in_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        self.inbound_ready = asyncio.Event()
        self.subscription: MatrixEventSubscription | None = None
        self.tasks: list[asyncio.Task[None]] = []
        self.pending_candidates: list[dict[str, Any]] = []
        self.connected = asyncio.Event()
        self.ended = asyncio.Event()
        self.remote_ended = False


def _sdp_candidates(sdp: str) -> list[dict[str, Any]]:
    """Extract Matrix candidate objects from aiortc's gathered local SDP."""
    candidates: list[dict[str, Any]] = []
    mline = -1
    mid: str | None = None
    for raw_line in sdp.splitlines():
        line = raw_line.strip()
        if line.startswith("m="):
            mline += 1
            mid = None
        elif line.startswith("a=mid:"):
            mid = line.removeprefix("a=mid:")
        elif line.startswith("a=candidate:"):
            candidates.append(
                {
                    "candidate": line.removeprefix("a="),
                    "sdpMid": mid,
                    "sdpMLineIndex": mline,
                }
            )
    return candidates


class MatrixCall(CallTransport):
    """One classic Matrix 1:1 VoIP call using room events for signaling."""

    kind = "matrix"

    def __init__(
        self,
        matrix: Matrix,
        *,
        connection_id: int,
        outgoing: bool,
        initial_event: MatrixRoomEvent | None = None,
    ) -> None:
        self._matrix = matrix
        self._connection_id = connection_id
        self._self_id = matrix.user_id
        self._outgoing = outgoing
        self._initial_event = initial_event

    @classmethod
    async def from_connection_id(
        cls,
        connection_id: int,
        *,
        outgoing: bool,
        initial_event: MatrixRoomEvent | None = None,
    ) -> "MatrixCall":
        return cls(
            await Matrix.from_connection_id(connection_id),
            connection_id=connection_id,
            outgoing=outgoing,
            initial_event=initial_event,
        )

    async def _rtc_configuration(self) -> RTCConfiguration:
        turn = await self._matrix.turn_server()
        uris = [str(item) for item in turn.get("uris", []) if item]
        if not uris:
            return RTCConfiguration()
        return RTCConfiguration(
            iceServers=[
                RTCIceServer(
                    urls=uris,
                    username=str(turn.get("username") or ""),
                    credential=str(turn.get("password") or ""),
                )
            ]
        )

    async def _send_event(
        self,
        handle: _MatrixCallHandle,
        event_type: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        content: dict[str, Any] = {
            "call_id": handle.call_id,
            "party_id": handle.local_party_id,
            "version": "1",
        }
        if extra:
            content.update(extra)
        await self._matrix.send_room_event(handle.room_id, event_type, content)

    def _install_peer_handlers(self, handle: _MatrixCallHandle) -> None:
        pc = handle.pc
        if pc is None:
            return

        @pc.on("track")
        def _on_track(track: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            if track.kind == "audio":
                handle.tasks.append(
                    asyncio.create_task(
                        self._drain_inbound(track, handle),
                        name=f"matrix_call_audio:{handle.call_id}",
                    )
                )

        @pc.on("connectionstatechange")
        def _on_connection_state() -> None:  # pyright: ignore[reportUnusedFunction]
            logger.info(
                "Matrix call connection state={} room={}",
                pc.connectionState,
                handle.room_id,
            )
            if pc.connectionState == "connected":
                handle.connected.set()
            elif pc.connectionState in {"failed", "closed"}:
                handle.ended.set()

    async def join(self, room_id: str) -> _MatrixCallHandle:
        handle = _MatrixCallHandle(room_id)
        handle.subscription = matrix_event_bus.subscribe(self._connection_id)
        try:
            handle.pc = RTCPeerConnection(await self._rtc_configuration())
            handle.pc.addTrack(handle.out_track)
            self._install_peer_handlers(handle)
            if self._outgoing:
                await self._start_outgoing(handle)
            else:
                await self._answer_incoming(handle)
            handle.tasks.append(
                asyncio.create_task(
                    self._signaling_loop(handle),
                    name=f"matrix_call_signal:{handle.call_id}",
                )
            )
            return handle
        except Exception:
            await self._cleanup(handle, send_hangup=False)
            raise

    async def _start_outgoing(self, handle: _MatrixCallHandle) -> None:
        pc = handle.pc
        if pc is None:
            raise RuntimeError("Matrix peer connection was not created")
        if await self._matrix.room_is_encrypted(handle.room_id):
            raise ValueError("Matrix voice mode does not support encrypted rooms")
        members = await self._matrix.joined_members(handle.room_id)
        remote = [user_id for user_id in members if user_id != self._self_id]
        if len(remote) != 1:
            raise ValueError("Matrix voice mode supports unencrypted 1:1 rooms only")
        handle.remote_user_id = remote[0]
        handle.call_id = uuid.uuid4().hex
        await pc.setLocalDescription(await pc.createOffer())
        local = pc.localDescription
        await self._send_event(
            handle,
            "m.call.invite",
            {
                "lifetime": _INVITE_LIFETIME_MS,
                "invitee": handle.remote_user_id,
                "offer": {"type": "offer", "sdp": local.sdp},
            },
        )
        await self._send_local_candidates(handle)
        logger.info("Matrix call invited room={}", handle.room_id)

    async def _answer_incoming(self, handle: _MatrixCallHandle) -> None:
        pc = handle.pc
        event = self._initial_event
        if pc is None or event is None or event.room_id != handle.room_id:
            raise ValueError("Matrix incoming call is missing its invite event")
        content = event.content
        offer = as_dict(content.get("offer"))
        if str(offer.get("type") or "") != "offer" or not offer.get("sdp"):
            raise ValueError("Matrix incoming call has no valid WebRTC offer")
        handle.call_id = str(content.get("call_id") or "")
        handle.remote_party_id = str(content.get("party_id") or "")
        handle.remote_user_id = event.sender
        if not handle.call_id:
            raise ValueError("Matrix incoming call has no call_id")
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=str(offer["sdp"]), type="offer")
        )
        await pc.setLocalDescription(await pc.createAnswer())
        local = pc.localDescription
        await self._send_event(
            handle,
            "m.call.answer",
            {"answer": {"type": "answer", "sdp": local.sdp}},
        )
        await self._send_local_candidates(handle)
        logger.info("Matrix call answered room={}", handle.room_id)

    async def _send_local_candidates(self, handle: _MatrixCallHandle) -> None:
        pc = handle.pc
        if pc is None:
            return
        local = pc.localDescription
        candidates = _sdp_candidates(local.sdp)
        if candidates:
            await self._send_event(
                handle,
                "m.call.candidates",
                {"candidates": candidates},
            )

    async def _set_remote_description(
        self,
        handle: _MatrixCallHandle,
        description: dict[str, Any],
    ) -> None:
        pc = handle.pc
        desc_type = str(description.get("type") or "")
        sdp = str(description.get("sdp") or "")
        if pc is None or desc_type not in {"offer", "answer"} or not sdp:
            return
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=desc_type))
        pending = handle.pending_candidates
        handle.pending_candidates = []
        await self._apply_candidates(handle, pending)

    async def _apply_candidates(
        self,
        handle: _MatrixCallHandle,
        candidates: list[dict[str, Any]],
    ) -> None:
        pc = handle.pc
        if pc is None:
            return
        if getattr(pc, "remoteDescription", None) is None:
            handle.pending_candidates.extend(candidates)
            return
        for raw in candidates:
            value = str(raw.get("candidate") or "")
            if not value:
                continue
            try:
                candidate = candidate_from_sdp(
                    value.split(":", 1)[1] if value.startswith("candidate:") else value
                )
                candidate.sdpMid = raw.get("sdpMid")
                candidate.sdpMLineIndex = raw.get("sdpMLineIndex")
                await pc.addIceCandidate(candidate)
            except Exception:
                logger.opt(exception=True).debug("Matrix call ignored invalid ICE candidate")

    async def _signaling_loop(self, handle: _MatrixCallHandle) -> None:
        subscription = handle.subscription
        if subscription is None:
            return
        while not handle.ended.is_set():
            event = await subscription.get()
            if (
                event.room_id != handle.room_id
                or event.sender == self._self_id
                or str(event.content.get("call_id") or "") != handle.call_id
            ):
                continue
            event_party = str(event.content.get("party_id") or "")
            if event.type == "m.call.answer" and self._outgoing:
                answer = as_dict(event.content.get("answer"))
                if not answer:
                    continue
                handle.remote_party_id = event_party
                handle.remote_user_id = event.sender
                await self._set_remote_description(handle, answer)
                await self._send_event(
                    handle,
                    "m.call.select_answer",
                    {"selected_party_id": handle.remote_party_id},
                )
            elif event.type == "m.call.select_answer" and not self._outgoing:
                selected = str(event.content.get("selected_party_id") or "")
                if selected and selected != handle.local_party_id:
                    handle.remote_ended = True
                    handle.ended.set()
            elif event.type == "m.call.candidates":
                candidates = [
                    as_dict(item)
                    for item in as_list(event.content.get("candidates"))
                    if isinstance(item, dict)
                ]
                await self._apply_candidates(handle, candidates)
            elif event.type == "m.call.negotiate":
                description = as_dict(event.content.get("description"))
                if not description:
                    continue
                if description.get("type") == "offer":
                    await self._set_remote_description(handle, description)
                    pc = handle.pc
                    if pc is not None:
                        await pc.setLocalDescription(await pc.createAnswer())
                        await self._send_event(
                            handle,
                            "m.call.negotiate",
                            {
                                "description": {
                                    "type": "answer",
                                    "sdp": pc.localDescription.sdp,
                                }
                            },
                        )
                elif description.get("type") == "answer":
                    await self._set_remote_description(handle, description)
            elif event.type in {"m.call.hangup", "m.call.reject"}:
                handle.remote_ended = True
                handle.ended.set()

    async def _drain_inbound(self, track: Any, handle: _MatrixCallHandle) -> None:
        resampler = av.AudioResampler(
            format="s16", layout="mono", rate=DEFAULT_SAMPLE_RATE
        )
        try:
            while not handle.ended.is_set():
                frame = await track.recv()
                for normalized in resampler.resample(frame):
                    handle.inbound_ready.set()
                    handle.in_queue.put_nowait(AudioFrame(pcm=_pcm_bytes(normalized)))
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            logger.debug("Matrix call remote audio track ended")
        except Exception:
            logger.opt(exception=True).debug("Matrix call inbound audio failed")

    def inbound_audio(self, handle: _MatrixCallHandle) -> AsyncIterator[AudioFrame]:
        async def _frames() -> AsyncIterator[AudioFrame]:
            while not handle.ended.is_set():
                try:
                    yield await asyncio.wait_for(handle.in_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

        return _frames()

    async def send_audio(
        self,
        handle: _MatrixCallHandle,
        frames: AsyncIterator[AudioFrame],
    ) -> None:
        async for frame in frames:
            handle.out_track.push(frame.pcm)

    async def interrupt_output(self, handle: _MatrixCallHandle) -> None:
        cleared = handle.out_track.clear()
        logger.info("Matrix call cleared {} outbound audio frame(s)", cleared)

    async def wait_output_ready(self, handle: _MatrixCallHandle) -> None:
        connected = asyncio.create_task(handle.connected.wait())
        ended = asyncio.create_task(handle.ended.wait())
        try:
            await asyncio.wait(
                [connected, ended], timeout=15.0, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            connected.cancel()
            ended.cancel()
            await asyncio.gather(connected, ended, return_exceptions=True)
        if not handle.connected.is_set():
            if handle.ended.is_set():
                raise ConnectionError("Matrix call ended before WebRTC connected")
            raise TimeoutError("Matrix WebRTC did not connect within 15 seconds")

    async def wait_input_ready(self, handle: _MatrixCallHandle) -> None:
        ready = asyncio.create_task(handle.inbound_ready.wait())
        ended = asyncio.create_task(handle.ended.wait())
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
                "Matrix call ended before the remote audio stream became available"
            )

    async def wait_output_drained(self, handle: _MatrixCallHandle) -> None:
        await handle.out_track.wait_drained()

    async def wait_ended(self, handle: _MatrixCallHandle) -> None:
        await handle.ended.wait()

    async def leave(self, handle: _MatrixCallHandle) -> None:
        await self._cleanup(handle, send_hangup=not handle.remote_ended)

    async def _cleanup(
        self,
        handle: _MatrixCallHandle,
        *,
        send_hangup: bool,
    ) -> None:
        if send_hangup and handle.call_id:
            try:
                await self._send_event(
                    handle,
                    "m.call.hangup",
                    {"reason": "user_hangup"},
                )
            except Exception:
                logger.opt(exception=True).debug("Matrix call hangup event failed")
        handle.ended.set()
        for task in handle.tasks:
            task.cancel()
        if handle.tasks:
            await asyncio.gather(*handle.tasks, return_exceptions=True)
        if handle.pc is not None:
            await handle.pc.close()
        if handle.subscription is not None:
            await handle.subscription.close()
        await self._matrix.aclose()

    def remote_user_ids(self, handle: Any) -> tuple[str, ...]:
        if not isinstance(handle, _MatrixCallHandle):
            return ()
        user_id = handle.remote_user_id.strip()
        return (user_id,) if user_id else ()

    def call_external_id(self, handle: Any) -> str:
        if not isinstance(handle, _MatrixCallHandle):
            return ""
        return handle.call_id
