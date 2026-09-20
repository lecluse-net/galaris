import asyncio
import struct
import threading
from itertools import islice
from unittest.mock import Mock

import pytest
from app.voice import audio
from core.util import buffered_io_budget


@pytest.mark.asyncio
async def test_encoded_audio_is_decoded_in_batches_and_releases_budget_on_close(monkeypatch):
    advanced = 0
    closed = False
    def decode(_content):
        nonlocal advanced, closed
        try:
            for _ in range(1000):
                advanced += 1
                yield b"\x01\x00" * 960
        finally:
            closed = True
    monkeypatch.setattr(audio, "_decode_audio", decode)
    frames = audio.encoded_audio_frames(b"encoded")
    await anext(frames)
    assert advanced == 50 and buffered_io_budget.active == 1
    await frames.aclose()
    assert closed and buffered_io_budget.active == 0


def test_real_wav_decoder_preserves_samples_and_final_partial_frame():
    pcm = b"\x01\x00" * (960 * 4 + 30)
    frames = list(audio._decode_audio(audio.pcm_to_wav(pcm)))
    assert len(frames) == 5
    decoded = b"".join(frames)
    assert decoded[:len(pcm)] == pcm
    assert not any(decoded[len(pcm):])


def test_encoded_24khz_audio_preserves_duration_and_amplitude_at_playback_rate():
    pcm = struct.pack("<h", 1000) * 1000
    decoded = b"".join(audio._decode_audio(audio.pcm_to_wav(pcm, sample_rate=24_000)))
    samples = [value for (value,) in struct.iter_unpack("<h", decoded)]
    assert len(samples) == 3 * 960
    assert all(abs(value - 1000) <= 1 for value in samples[:2000])
    assert not any(samples[2000:])


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_rate", [24_000, 48_000])
async def test_empty_pcm_stream_does_not_invent_a_silent_frame(sample_rate):
    async def chunks():
        yield b""
    assert [frame async for frame in audio.pcm_audio_frames(chunks(), sample_rate=sample_rate)] == []


@pytest.mark.parametrize("convert", [audio.downsample_pcm_48k_to_24k, audio.upsample_pcm_24k_to_48k])
def test_incomplete_pcm_sample_is_rejected_without_silent_corruption(convert):
    with pytest.raises(ValueError, match="incomplete sample"):
        convert(b"\x01")
    assert convert(b"") == b""


def test_pcm_conversion_preserves_signed_amplitudes_and_interpolates_adjacent_samples():
    source = struct.pack("<hhh", -1000, 1000, 3000)
    assert struct.unpack("<hhhhhh", audio.upsample_pcm_24k_to_48k(source)) == (-1000, 0, 1000, 2000, 3000, 3000)
    assert audio.downsample_pcm_48k_to_24k(audio.upsample_pcm_24k_to_48k(source)) == source
    assert audio.pcm_rms(b"") == 0
    assert audio.pcm_rms(struct.pack("<hh", -1000, 1000)) == 1000


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_rate", [24_000, 48_000])
@pytest.mark.parametrize("chunk_size", [1, 7, 4096])
async def test_network_chunk_boundaries_do_not_change_decoded_speech(sample_rate, chunk_size):
    source = struct.pack("<h", 321) * 2000
    async def chunks():
        for offset in range(0, len(source), chunk_size):
            yield source[offset:offset + chunk_size]
    frames = [frame async for frame in audio.pcm_audio_frames(chunks(), sample_rate=sample_rate)]
    expected = source if sample_rate == 48_000 else audio.upsample_pcm_24k_to_48k(source)
    decoded = b"".join(frame.pcm for frame in frames)
    assert decoded[:len(expected)] == expected
    assert not any(decoded[len(expected):])
    assert all(len(frame.pcm) == audio.FRAME_BYTES for frame in frames)


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_rate,channels", [(16_000, 1), (48_000, 2)])
async def test_unsupported_live_audio_format_fails_before_consuming_stream(sample_rate, channels):
    async def chunks():
        pytest.fail("Unsupported audio must not be consumed")
        yield b""
    with pytest.raises(ValueError, match="mono"):
        await anext(audio.pcm_audio_frames(chunks(), sample_rate=sample_rate, channels=channels))


@pytest.mark.asyncio
async def test_incomplete_24k_stream_is_not_padded_as_a_valid_sample():
    async def chunks():
        yield b"\x01"
    with pytest.raises(ValueError, match="incomplete sample"):
        await anext(audio.pcm_audio_frames(chunks(), sample_rate=24_000))


@pytest.mark.asyncio
async def test_real_encoded_audio_completes_and_releases_decoder_budget():
    pcm = b"\x01\x00" * 1000
    frames = [frame async for frame in audio.encoded_audio_frames(audio.pcm_to_wav(pcm))]
    decoded = b"".join(frame.pcm for frame in frames)
    assert decoded[:len(pcm)] == pcm and not any(decoded[len(pcm):])
    assert buffered_io_budget.used == buffered_io_budget.active == 0


@pytest.mark.asyncio
async def test_cancel_during_decoder_work_waits_before_closing_iterator(monkeypatch):
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    def decode(content):
        try:
            started.set()
            assert release.wait(5)
            yield b"\x00" * audio.FRAME_BYTES
        finally:
            closed.set()
    monkeypatch.setattr(audio, "_decode_audio", decode)
    frames = audio.encoded_audio_frames(b"encoded")
    operation = asyncio.create_task(anext(frames))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        operation.cancel()
        await asyncio.sleep(0)
        assert not closed.is_set() and buffered_io_budget.active == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        await frames.aclose()
    assert closed.is_set() and buffered_io_budget.used == 0
