"""Low-latency speech turn detection over canonical PCM call frames."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from .audio import BYTES_PER_SECOND, pcm_rms
from .models import AudioFrame, DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE


@dataclass(frozen=True, slots=True)
class SpeechUtterance:
    """One completed human speech turn in canonical PCM."""

    pcm: bytes
    duration_s: float
    voiced_s: float
    reason: str
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS


async def detect_speech_turns(
    frames: AsyncIterator[AudioFrame],
    *,
    on_speech_start: Callable[[], Awaitable[None]] | None = None,
    on_audio: Callable[[bytes], Awaitable[None]] | None = None,
    rms_threshold: int = 80,
    min_speech_s: float = 0.25,
    speech_start_s: float = 0.24,
    silence_s: float = 0.8,
    max_utterance_s: float = 20.0,
    pre_roll_s: float = 0.8,
) -> AsyncIterator[SpeechUtterance]:
    """Segment a full-duplex inbound stream and signal barge-in immediately.

    Durations are measured from received audio rather than wall-clock time. A
    stalled WebRTC track while speech is active also closes the current turn.
    Long uninterrupted turns are emitted as contiguous ``max_duration``
    chunks while remaining active, so consumers can reassemble them without
    treating the same speaker as a new barge-in.

    ``on_audio`` receives every PCM frame exactly once, including silence and
    audio that the local endpoint detector does not classify as speech. The
    transcription provider therefore sees the complete input stream; the
    detector only decides when to commit a turn.
    """
    active = False
    continuing = False
    buffer = bytearray()
    voiced_bytes = 0
    buffered_at_last_voice = 0
    onset_voiced_bytes = 0
    speech_start_bytes = max(1, round(speech_start_s * BYTES_PER_SECOND))
    pre_roll_limit = max(speech_start_bytes, round(pre_roll_s * BYTES_PER_SECOND))
    pre_roll: deque[bytes] = deque()
    pre_roll_bytes = 0

    def finish(
        reason: str,
        *,
        continue_turn: bool = False,
    ) -> SpeechUtterance | None:
        nonlocal active, continuing
        nonlocal voiced_bytes, buffered_at_last_voice, onset_voiced_bytes
        voiced_s = voiced_bytes / BYTES_PER_SECOND
        duration_s = len(buffer) / BYTES_PER_SECOND
        pcm = bytes(buffer)
        has_speech = voiced_s >= min_speech_s or continuing
        active = continue_turn
        continuing = continue_turn
        buffer.clear()
        voiced_bytes = 0
        buffered_at_last_voice = 0
        onset_voiced_bytes = 0
        if not has_speech:
            return None
        return SpeechUtterance(
            pcm=pcm,
            duration_s=duration_s,
            voiced_s=voiced_s,
            reason=reason,
        )

    iterator = aiter(frames)
    next_frame: asyncio.Task[AudioFrame] | None = None
    try:
        while True:
            if next_frame is None:
                next_frame = asyncio.ensure_future(anext(iterator))
            done, _ = await asyncio.wait(
                {next_frame},
                timeout=silence_s if active else None,
            )
            if not done:
                utterance = finish("stream_stall")
                if utterance is not None:
                    yield utterance
                continue

            try:
                frame = next_frame.result()
            except StopAsyncIteration:
                utterance = finish("stream_end")
                if utterance is not None:
                    yield utterance
                return
            next_frame = None

            if on_audio is not None:
                await on_audio(frame.pcm)
            pre_roll.append(frame.pcm)
            pre_roll_bytes += len(frame.pcm)
            # Transports need not deliver 20 ms frames. Retain audio duration,
            # otherwise smaller packets shorten the quiet lead-in we preserve.
            while pre_roll_bytes > pre_roll_limit:
                excess = pre_roll_bytes - pre_roll_limit
                first = pre_roll.popleft()
                removed = min(excess, len(first))
                pre_roll_bytes -= removed
                if removed < len(first):
                    pre_roll.appendleft(first[removed:])
            voiced = pcm_rms(frame.pcm) >= rms_threshold
            started_now = False
            if not active:
                # A single loud frame (keyboard, click, comfort noise...) must
                # not cancel an answer already being spoken. Confirm a short,
                # continuous voice onset before declaring a human barge-in.
                onset_voiced_bytes = (
                    onset_voiced_bytes + len(frame.pcm) if voiced else 0
                )
                if onset_voiced_bytes < speech_start_bytes:
                    continue
                active = True
                buffer.extend(b"".join(pre_roll))
                voiced_bytes = onset_voiced_bytes
                buffered_at_last_voice = len(buffer)
                onset_voiced_bytes = 0
                started_now = True
                if on_speech_start is not None:
                    await on_speech_start()
            else:
                buffer.extend(frame.pcm)

            if not active:
                continue
            if voiced and not started_now:
                voiced_bytes += len(frame.pcm)
                buffered_at_last_voice = len(buffer)

            duration_s = len(buffer) / BYTES_PER_SECOND
            trailing_silence_s = (
                len(buffer) - buffered_at_last_voice
            ) / BYTES_PER_SECOND
            reason = ""
            if duration_s >= max_utterance_s:
                reason = "max_duration"
            elif trailing_silence_s >= silence_s:
                reason = "silence"
            if reason:
                utterance = finish(
                    reason,
                    continue_turn=reason == "max_duration",
                )
                if utterance is not None:
                    yield utterance
    finally:
        if next_frame is not None:
            next_frame.cancel()
            await asyncio.gather(next_frame, return_exceptions=True)
