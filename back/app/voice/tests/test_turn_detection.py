from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.voice.models import AudioFrame
from app.voice.turn_detection import SpeechUtterance, detect_speech_turns

_LOUD = struct.pack("<h", 5000) * 960
_QUIET = struct.pack("<h", 100) * 960
_SILENCE = b"\x00\x00" * 960


async def _frames(
    pcms: list[bytes],
    tail_sleep: float | None = None,
) -> AsyncIterator[AudioFrame]:
    for pcm in pcms:
        yield AudioFrame(pcm=pcm)
    if tail_sleep is not None:
        await asyncio.sleep(tail_sleep)


async def _collect(
    frames: AsyncIterator[AudioFrame],
    **kwargs: Any,
) -> list[SpeechUtterance]:
    return [turn async for turn in detect_speech_turns(frames, **kwargs)]


@pytest.mark.asyncio
async def test_utterance_closes_on_audio_time_silence() -> None:
    turns = await _collect(_frames([_LOUD] * 30 + [_SILENCE] * 45))

    assert len(turns) == 1
    assert turns[0].reason == "silence"
    assert turns[0].voiced_s == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_short_noise_blip_is_dropped() -> None:
    started = AsyncMock()
    turns = await _collect(
        _frames([_LOUD] * 10 + [_SILENCE] * 45),
        on_speech_start=started,
    )

    assert turns == []
    started.assert_not_awaited()


@pytest.mark.asyncio
async def test_natural_pause_does_not_split_one_turn() -> None:
    turns = await _collect(
        _frames(
            [_LOUD] * 20
            + [_SILENCE] * 35  # 700 ms hesitation.
            + [_LOUD] * 20
            + [_SILENCE] * 45
        )
    )

    assert len(turns) == 1
    assert turns[0].reason == "silence"
    assert turns[0].voiced_s == pytest.approx(0.8)


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_samples", [480, 960, 2880])
async def test_pre_roll_preserves_a_quiet_lead_in(frame_samples: int) -> None:
    streamed: list[bytes] = []

    async def stream_audio(pcm: bytes) -> None:
        streamed.append(pcm)

    pcm = _SILENCE * 10 + _QUIET * 25 + _LOUD * 15 + _SILENCE * 45
    turns = await _collect(
        _frames([pcm[offset:offset + frame_samples * 2]
                 for offset in range(0, len(pcm), frame_samples * 2)]),
        on_audio=stream_audio,
        rms_threshold=200,
    )

    assert len(turns) == 1
    assert _QUIET * 25 in turns[0].pcm
    assert b"".join(streamed) == pcm


@pytest.mark.asyncio
async def test_quiet_speech_is_not_left_uncommitted() -> None:
    turns = await _collect(_frames([_QUIET] * 30 + [_SILENCE] * 45))

    assert len(turns) == 1
    assert turns[0].reason == "silence"
    assert turns[0].voiced_s == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_every_frame_reaches_streaming_transcription() -> None:
    streamed: list[bytes] = []

    async def stream_audio(pcm: bytes) -> None:
        streamed.append(pcm)

    turns = await _collect(
        _frames([_SILENCE] * 5 + [_QUIET] * 5),
        on_audio=stream_audio,
    )

    assert turns == []
    assert streamed == [_SILENCE] * 5 + [_QUIET] * 5


@pytest.mark.asyncio
async def test_long_continuous_speech_keeps_one_barge_in() -> None:
    started = AsyncMock()
    turns = await _collect(
        _frames([_LOUD] * 40 + [_SILENCE] * 15),
        on_speech_start=started,
        silence_s=0.2,
        max_utterance_s=0.6,
    )

    assert [turn.reason for turn in turns] == ["max_duration", "silence"]
    assert sum(turn.voiced_s for turn in turns) == pytest.approx(0.8)
    started.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_stream_stall_closes_the_utterance() -> None:
    turns = detect_speech_turns(
        _frames([_LOUD] * 30, tail_sleep=30.0),
        silence_s=0.2,
    )
    first = await asyncio.wait_for(anext(turns), timeout=2.0)
    await turns.aclose()

    assert first.reason == "stream_stall"


@pytest.mark.asyncio
async def test_stream_end_flushes_pending_speech() -> None:
    turns = await _collect(_frames([_LOUD] * 30))

    assert len(turns) == 1
    assert turns[0].reason == "stream_end"


@pytest.mark.asyncio
async def test_speech_start_callback_runs_before_turn_finishes() -> None:
    started = AsyncMock()
    frames = _frames([_LOUD] * 30 + [_SILENCE] * 30)

    turns = await _collect(frames, on_speech_start=started)

    assert len(turns) == 1
    started.assert_awaited_once_with()
