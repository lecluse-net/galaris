"""OpenAI WebSocket transcription with Galaris-owned turn boundaries."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from app.llm.facade import ProviderConnection, RealtimeTranscriber

from .realtime import decode_realtime_event, raise_realtime_error, websocket_url


_MODELS = frozenset({
    "gpt-live-transcribe", "gpt-transcribe", "gpt-realtime-whisper", "whisper-1", "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe-2025-12-15", "gpt-4o-transcribe-diarize",
})
_TRANSCRIPTION_EVENT = "conversation.item.input_audio_transcription"
_MIN_AUDIO_BYTES = 4_800  # 100 ms of 24 kHz mono PCM16.
_MAX_AUDIO_BYTES = 15_000_000


class OpenAITranscription:
    async def create_realtime_transcriber(
        self, connection: ProviderConnection, *, model: str, language: str, sample_rate: int,
        channels: int, on_partial: Callable[[str], Awaitable[None]] | None = None,
    ) -> RealtimeTranscriber | None:
        if model not in _MODELS or sample_rate not in {24_000, 48_000} or channels != 1:
            return None
        if not connection.api_key:
            raise ValueError(f"provider {connection.name} requires an API key")
        socket = await connect(
            websocket_url(connection.base_url, None),
            additional_headers={"Authorization": f"Bearer {connection.api_key}"},
            open_timeout=10, close_timeout=2, max_size=65_536, max_queue=128,
        )
        try:
            async with asyncio.timeout(10):
                await _expect(socket, "session.created")
                transcription = {"model": model}
                language_code = language.split("-")[0].lower()
                if len(language_code) == 2 and language_code.isascii() and language_code.isalpha():
                    transcription["language"] = language_code
                await socket.send(json.dumps({"type": "session.update", "session": {
                    "type": "transcription", "audio": {"input": {
                        "format": {"type": "audio/pcm", "rate": 24_000},
                        "transcription": transcription, "turn_detection": None,
                    }},
                }}))
                await _expect(socket, "session.updated")
        except BaseException:
            await asyncio.shield(socket.close())
            raise
        return _OpenAITranscriber(socket, sample_rate=sample_rate, on_partial=on_partial)


async def _expect(socket: ClientConnection, kind: str) -> None:
    event = decode_realtime_event(await socket.recv())
    if event.get("type") != kind:
        raise_realtime_error(event, f"OpenAI Realtime did not send {kind}")


class _OpenAITranscriber:
    def __init__(
        self, socket: ClientConnection, *, sample_rate: int, on_partial: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        self._socket = socket
        self._downsample = sample_rate == 48_000
        self._on_partial = on_partial
        self._audio_bytes = 0
        self._sample_offset = 0
        self._last_item: str | None = None

    async def send_audio(self, pcm: bytes, *, speech_detected: bool = True) -> None:
        if not pcm or (not speech_detected and not self._audio_bytes):
            return
        if len(pcm) % 2:
            raise ValueError("PCM audio ended with an incomplete sample")
        if self._downsample:
            samples = memoryview(pcm).cast("H")
            pcm = samples[self._sample_offset::2].tobytes()
            self._sample_offset = (self._sample_offset + len(samples)) % 2
        await self._append(pcm)

    async def _append(self, pcm: bytes) -> None:
        if not pcm:
            return
        if self._audio_bytes + len(pcm) > _MAX_AUDIO_BYTES:
            raise RuntimeError("OpenAI Realtime audio exceeds the input buffer limit")
        await self._socket.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}))
        self._audio_bytes += len(pcm)

    async def commit(self) -> str:
        if not self._audio_bytes:
            return ""
        if self._audio_bytes < _MIN_AUDIO_BYTES:
            await self._append(bytes(_MIN_AUDIO_BYTES - self._audio_bytes))
        await self._socket.send(json.dumps({"type": "input_audio_buffer.commit"}))
        async with asyncio.timeout(15):
            text = await self._receive_transcript()
        self._audio_bytes = 0
        self._sample_offset = 0
        return text

    async def _receive_transcript(self) -> str:
        item_id: str | None = None
        pending: list[dict[str, Any]] = []
        partial = ""
        while True:
            event = decode_realtime_event(await self._socket.recv())
            kind = event.get("type")
            if kind == "error":
                raise_realtime_error(event, "OpenAI Realtime transcription failed")
            if not isinstance(identifier := event.get("item_id"), str) or identifier == self._last_item:
                continue
            if kind == "input_audio_buffer.committed":
                item_id = identifier
                events, pending = pending, []
            elif isinstance(kind, str) and kind.startswith(_TRANSCRIPTION_EVENT):
                if item_id is None:
                    if len(pending) >= 256:
                        raise RuntimeError("OpenAI Realtime did not acknowledge the committed audio")
                    pending.append(event)
                    continue
                events = [event]
            else:
                continue
            for received in events:
                if received.get("item_id") != item_id:
                    continue
                event_type = received.get("type")
                if event_type == f"{_TRANSCRIPTION_EVENT}.completed":
                    if not isinstance(text := received.get("transcript"), str):
                        raise RuntimeError("OpenAI Realtime returned an invalid transcript")
                    self._last_item = item_id
                    return text.strip()
                if event_type == f"{_TRANSCRIPTION_EVENT}.failed":
                    raise_realtime_error({"type": "error", "error": received.get("error")},
                                         "OpenAI Realtime could not transcribe the committed audio")
                if event_type == f"{_TRANSCRIPTION_EVENT}.delta" and isinstance(delta := received.get("delta"), str):
                    partial = (partial + delta)[:65_536]
                    if self._on_partial is not None:
                        await self._on_partial(partial)

    async def close(self) -> None:
        await self._socket.close()
