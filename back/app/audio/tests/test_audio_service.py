from __future__ import annotations

import math
import struct
from pathlib import Path

import av
import pytest

from app.audio import audio_service


def _video_with_audio(path: Path, *, duration_seconds: int = 1) -> None:
    """Create a small Matroska video with one PCM audio stream."""
    container = av.open(str(path), mode="w", format="matroska")
    try:
        video = container.add_stream("mpeg4", rate=1)
        video.width = 16
        video.height = 16
        video.pix_fmt = "yuv420p"

        sample_rate = 16_000
        audio = container.add_stream("pcm_s16le", rate=sample_rate)
        audio.layout = "mono"

        video_frame = av.VideoFrame(16, 16, "yuv420p")
        for plane in video_frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in video.encode(video_frame):
            container.mux(packet)
        for packet in video.encode(None):
            container.mux(packet)

        samples = [
            int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            for index in range(sample_rate * duration_seconds)
        ]
        audio_frame = av.AudioFrame(format="s16", layout="mono", samples=len(samples))
        audio_frame.sample_rate = sample_rate
        audio_frame.planes[0].update(struct.pack(f"<{len(samples)}h", *samples))
        for packet in audio.encode(audio_frame):
            container.mux(packet)
        for packet in audio.encode(None):
            container.mux(packet)
    finally:
        container.close()


@pytest.mark.asyncio
async def test_normalization_extracts_video_audio_as_mono_mp3_96k(
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.mkv"
    destination = tmp_path / "meeting.mp3"
    _video_with_audio(source)

    await audio_service.normalize_for_transcription(source, destination)

    assert destination.is_file()
    assert destination.stat().st_size > 0
    normalized = av.open(str(destination), mode="r")
    try:
        assert len(normalized.streams.video) == 0
        assert len(normalized.streams.audio) == 1
        stream = normalized.streams.audio[0]
        assert stream.codec_context.name.startswith("mp3")
        assert stream.codec_context.layout.name == "mono"
        assert stream.codec_context.bit_rate == 96_000
    finally:
        normalized.close()


@pytest.mark.asyncio
async def test_normalization_rejects_video_without_audio(tmp_path: Path) -> None:
    source = tmp_path / "silent.mkv"
    destination = tmp_path / "silent.mp3"
    container = av.open(str(source), mode="w", format="matroska")
    try:
        video = container.add_stream("mpeg4", rate=1)
        video.width = 16
        video.height = 16
        video.pix_fmt = "yuv420p"
        frame = av.VideoFrame(16, 16, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in video.encode(frame):
            container.mux(packet)
        for packet in video.encode(None):
            container.mux(packet)
    finally:
        container.close()

    with pytest.raises(audio_service.AudioConversionFailed, match="no audio stream"):
        await audio_service.normalize_for_transcription(source, destination)

    assert not destination.exists()
    with pytest.raises(audio_service.AudioConversionFailed, match="no audio stream"):
        await audio_service.media_audio_duration(source)
    from app.audio import normalize_for_transcription_chunks_isolated
    for normalize in (audio_service.normalize_for_transcription_chunks, normalize_for_transcription_chunks_isolated):
        chunks_dir = tmp_path / "chunks"
        with pytest.raises(audio_service.AudioConversionFailed, match="no audio stream"):
            await normalize(source, chunks_dir)
        assert not list(chunks_dir.glob("*.mp3"))


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [None, b"", b"not a media container"])
async def test_unusable_media_is_rejected_without_leaving_transcription_output(tmp_path, contents):
    source = tmp_path / "unusable.mkv"
    if contents is not None:
        source.write_bytes(contents)
    with pytest.raises(audio_service.AudioConversionFailed):
        await audio_service.media_audio_duration(source)
    destination = tmp_path / "output.mp3"
    with pytest.raises(audio_service.AudioConversionFailed):
        await audio_service.normalize_for_transcription(source, destination)
    assert not destination.exists()
    chunks_dir = tmp_path / "chunks"
    with pytest.raises(audio_service.AudioConversionFailed):
        await audio_service.normalize_for_transcription_chunks(source, chunks_dir)
    assert not list(chunks_dir.glob("*.mp3"))


@pytest.mark.asyncio
@pytest.mark.parametrize("isolated", [False, True])
async def test_long_media_is_split_into_bounded_mp3_chunks(tmp_path: Path, isolated: bool) -> None:
    source = tmp_path / "long-meeting.mkv"
    chunks_dir = tmp_path / "chunks"
    _video_with_audio(source, duration_seconds=3)

    duration = await audio_service.media_audio_duration(source)
    from app.audio import normalize_for_transcription_chunks_isolated
    normalize = normalize_for_transcription_chunks_isolated if isolated else audio_service.normalize_for_transcription_chunks
    chunks = await normalize(
        source,
        chunks_dir,
        chunk_seconds=1,
    )

    assert duration == pytest.approx(3.0, abs=0.1)
    assert len(chunks) == 3
    assert [chunk.index for chunk in chunks] == [1, 2, 3]
    assert chunks[0].start_seconds == pytest.approx(0.0)
    assert chunks[-1].end_seconds == pytest.approx(3.0, abs=0.1)
    for chunk in chunks:
        assert chunk.end_seconds - chunk.start_seconds <= 1.01
        container = av.open(str(chunk.path), mode="r")
        try:
            assert len(container.streams.audio) == 1
            assert container.streams.audio[0].codec_context.bit_rate == 96_000
        finally:
            container.close()


@pytest.mark.asyncio
async def test_interrupted_isolated_decode_is_stopped_before_cleanup(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from app.audio import isolated_normalization

    process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=asyncio.CancelledError),
                              kill=Mock(), wait=AsyncMock())
    monkeypatch.setattr(isolated_normalization.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await isolated_normalization.normalize_for_transcription_chunks_isolated(tmp_path / "video", tmp_path / "chunks")
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
