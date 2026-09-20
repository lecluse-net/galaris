"""Disk-backed audio normalization for batch transcription."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TRANSCRIPTION_BIT_RATE = 96_000
_TRANSCRIPTION_SAMPLE_RATE = 32_000
TRANSCRIPTION_CHUNK_SECONDS = 10 * 60


class AudioConversionFailed(RuntimeError):
    """Raised when a media file cannot be normalized for transcription."""


@dataclass(frozen=True)
class AudioChunk:
    """One normalized MP3 segment and its approximate source time range."""

    path: Path
    index: int
    start_seconds: float
    end_seconds: float


async def normalize_for_transcription(source: Path, destination: Path) -> None:
    """Convert the first audio stream to a mono MP3 at 96 kbit/s."""
    await asyncio.to_thread(_normalize_for_transcription_sync, source, destination)


async def media_audio_duration(source: Path) -> float | None:
    """Return a cheap metadata duration estimate for the first audio stream."""
    return await asyncio.to_thread(_media_audio_duration_sync, source)


async def normalize_for_transcription_chunks(
    source: Path,
    destination_dir: Path,
    *,
    chunk_seconds: int = TRANSCRIPTION_CHUNK_SECONDS,
) -> list[AudioChunk]:
    """Convert media to mono MP3 segments without loading full audio into memory."""
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive")
    return await asyncio.to_thread(
        _normalize_for_transcription_chunks_sync,
        source,
        destination_dir,
        chunk_seconds,
    )


def _media_audio_duration_sync(source: Path) -> float | None:
    """Inspect container metadata without decoding the complete media."""
    import av

    if not source.is_file() or source.stat().st_size <= 0:
        raise AudioConversionFailed("the source media file is empty or missing")
    try:
        with av.open(str(source), mode="r") as container:
            if not container.streams.audio:
                raise AudioConversionFailed("the source media file contains no audio stream")
            stream = container.streams.audio[0]
            if stream.duration is not None and stream.time_base is not None:
                return max(0.0, float(stream.duration * stream.time_base))
            if container.duration is not None:
                return max(0.0, float(container.duration / av.time_base))
            return None
    except AudioConversionFailed:
        raise
    except Exception as exc:
        raise AudioConversionFailed(f"could not inspect the media file: {exc}") from exc


def _open_mp3_output(path: Path) -> tuple[Any, Any]:
    import av

    container: Any = av.open(str(path), mode="w", format="mp3")
    stream: Any = container.add_stream("libmp3lame", rate=_TRANSCRIPTION_SAMPLE_RATE)
    stream.bit_rate = _TRANSCRIPTION_BIT_RATE
    stream.layout = "mono"
    return container, stream


def _close_mp3_output(container: Any, stream: Any) -> None:
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def _normalize_for_transcription_chunks_sync(
    source: Path,
    destination_dir: Path,
    chunk_seconds: int,
) -> list[AudioChunk]:
    """Decode once and rotate MP3 encoders at approximately fixed durations."""
    import av

    if not source.is_file() or source.stat().st_size <= 0:
        raise AudioConversionFailed("the source media file is empty or missing")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target_samples = chunk_seconds * _TRANSCRIPTION_SAMPLE_RATE
    input_container: Any = None
    output_container: Any = None
    output_stream: Any = None
    chunks: list[AudioChunk] = []
    chunk_index = 1
    chunk_samples = 0
    total_samples = 0
    chunk_start_sample = 0

    def open_chunk(index: int) -> tuple[Path, Any, Any]:
        path = destination_dir / f"chunk-{index:04d}.mp3"
        container, stream = _open_mp3_output(path)
        return path, container, stream

    def finish_chunk(path: Path) -> None:
        nonlocal output_container, output_stream, chunk_samples, chunk_start_sample
        if output_container is None or output_stream is None or chunk_samples <= 0:
            return
        _close_mp3_output(output_container, output_stream)
        output_container = None
        output_stream = None
        if not path.is_file() or path.stat().st_size <= 0:
            raise AudioConversionFailed("an encoded transcription chunk is empty")
        chunks.append(
            AudioChunk(
                path=path,
                index=len(chunks) + 1,
                start_seconds=chunk_start_sample / _TRANSCRIPTION_SAMPLE_RATE,
                end_seconds=(chunk_start_sample + chunk_samples)
                / _TRANSCRIPTION_SAMPLE_RATE,
            )
        )
        chunk_start_sample += chunk_samples
        chunk_samples = 0

    current_path: Path | None = None
    try:
        input_container = av.open(str(source), mode="r")
        if not input_container.streams.audio:
            raise AudioConversionFailed("the source media file contains no audio stream")
        resampler = av.AudioResampler(
            format="fltp",
            layout="mono",
            rate=_TRANSCRIPTION_SAMPLE_RATE,
        )
        current_path, output_container, output_stream = open_chunk(chunk_index)

        def encode_frame(frame: Any) -> None:
            nonlocal current_path, output_container, output_stream
            nonlocal chunk_index, chunk_samples, total_samples
            frame_samples = int(frame.samples)
            raw_plane = bytes(frame.planes[0])
            offset = 0
            while offset < frame_samples:
                if chunk_samples >= target_samples:
                    assert current_path is not None
                    finish_chunk(current_path)
                    chunk_index += 1
                    current_path, output_container, output_stream = open_chunk(chunk_index)
                take = min(target_samples - chunk_samples, frame_samples - offset)
                if offset == 0 and take == frame_samples:
                    encoded_frame = frame
                else:
                    encoded_frame = av.AudioFrame(
                        format="fltp",
                        layout="mono",
                        samples=take,
                    )
                    encoded_frame.sample_rate = _TRANSCRIPTION_SAMPLE_RATE
                    byte_start = offset * 4
                    encoded_frame.planes[0].update(
                        raw_plane[byte_start : byte_start + take * 4]
                    )
                encoded_frame.pts = None
                assert output_container is not None and output_stream is not None
                for packet in output_stream.encode(encoded_frame):
                    output_container.mux(packet)
                chunk_samples += take
                total_samples += take
                offset += take

        for decoded in input_container.decode(audio=0):
            for resampled in resampler.resample(decoded):
                encode_frame(resampled)
        for resampled in resampler.resample(None):
            encode_frame(resampled)

        if total_samples == 0:
            raise AudioConversionFailed("the source media file contains no decodable audio")
        finish_chunk(current_path)
        input_container.close()
        input_container = None
        return chunks
    except AudioConversionFailed:
        raise
    except Exception as exc:
        raise AudioConversionFailed(f"could not split the media file into MP3 chunks: {exc}") from exc
    finally:
        if input_container is not None:
            input_container.close()
        if output_container is not None:
            output_container.close()
        if not chunks:
            for path in destination_dir.glob("chunk-*.mp3"):
                path.unlink(missing_ok=True)


def _normalize_for_transcription_sync(source: Path, destination: Path) -> None:
    """Run the PyAV decode/resample/encode pipeline without loading the whole file."""
    import av

    if not source.is_file() or source.stat().st_size <= 0:
        raise AudioConversionFailed("the source media file is empty or missing")

    input_container: Any = None
    output_container: Any = None
    completed = False
    try:
        input_container = av.open(str(source), mode="r")
        if not input_container.streams.audio:
            raise AudioConversionFailed("the source media file contains no audio stream")

        output_container = av.open(str(destination), mode="w", format="mp3")
        output_stream = output_container.add_stream(
            "libmp3lame",
            rate=_TRANSCRIPTION_SAMPLE_RATE,
        )
        output_stream.bit_rate = _TRANSCRIPTION_BIT_RATE
        output_stream.layout = "mono"
        resampler = av.AudioResampler(
            format="fltp",
            layout="mono",
            rate=_TRANSCRIPTION_SAMPLE_RATE,
        )

        frame_count = 0
        for decoded in input_container.decode(audio=0):
            for frame in resampler.resample(decoded):
                frame_count += 1
                for packet in output_stream.encode(frame):
                    output_container.mux(packet)
        for frame in resampler.resample(None):
            frame_count += 1
            for packet in output_stream.encode(frame):
                output_container.mux(packet)
        for packet in output_stream.encode(None):
            output_container.mux(packet)

        if frame_count == 0:
            raise AudioConversionFailed("the source media file contains no decodable audio")
        output_container.close()
        output_container = None
        input_container.close()
        input_container = None
        completed = True
    except AudioConversionFailed:
        raise
    except Exception as exc:
        raise AudioConversionFailed(f"could not convert the media file to MP3: {exc}") from exc
    finally:
        if input_container is not None:
            input_container.close()
        if output_container is not None:
            output_container.close()
        if not completed:
            destination.unlink(missing_ok=True)
