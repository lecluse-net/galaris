"""Shared bounded media normalization for native voice-note transports."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Protocol, cast

import av


class _AudioOutputStream(Protocol):
    layout: str
    bit_rate: int

    def encode(
        self, frame: av.AudioFrame | None = None
    ) -> list[av.Packet[av.AudioStream]]: ...


class _OutputContainer(Protocol):
    def mux(self, packet: av.Packet[av.AudioStream]) -> None: ...


class MediaValidationError(ValueError):
    """Raised when an input media file exceeds a configured safety limit."""


def _transcode_ogg_opus(
    source: Path,
    destination: Path,
    *,
    max_duration_seconds: int,
) -> None:
    with av.open(str(source), mode="r") as input_container:
        audio_stream = next(
            (stream for stream in input_container.streams if stream.type == "audio"),
            None,
        )
        if audio_stream is None:
            raise MediaValidationError("The media file contains no audio stream.")
        duration = input_container.duration
        if duration is not None and duration / av.time_base > max_duration_seconds:
            raise MediaValidationError(
                f"The audio duration exceeds {max_duration_seconds} seconds."
            )

        with av.open(str(destination), mode="w", format="ogg") as output_container:
            output_stream = cast(
                _AudioOutputStream,
                output_container.add_stream(  # pyright: ignore[reportUnknownMemberType]
                    "libopus", rate=48_000
                ),
            )
            typed_output_container = cast(_OutputContainer, output_container)
            output_stream.layout = "mono"
            output_stream.bit_rate = 32_000
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=48_000)
            normalized_samples = 0
            max_samples = max_duration_seconds * 48_000
            for frame in input_container.decode(audio=0):
                for normalized in resampler.resample(frame):
                    normalized_samples += normalized.samples
                    if normalized_samples > max_samples:
                        raise MediaValidationError(
                            f"The audio duration exceeds {max_duration_seconds} seconds."
                        )
                    for packet in output_stream.encode(normalized):
                        typed_output_container.mux(packet)
            for normalized in resampler.resample(None):
                normalized_samples += normalized.samples
                if normalized_samples > max_samples:
                    raise MediaValidationError(
                        f"The audio duration exceeds {max_duration_seconds} seconds."
                    )
                for packet in output_stream.encode(normalized):
                    typed_output_container.mux(packet)
            for packet in output_stream.encode(None):
                typed_output_container.mux(packet)


@asynccontextmanager
async def normalized_voice_note(
    source: Path,
    *,
    max_input_bytes: int,
    max_output_bytes: int,
    max_duration_seconds: int,
) -> AsyncGenerator[Path]:
    """Yield a temporary OGG/Opus voice note and always remove it afterwards."""
    size = source.stat().st_size
    if size > max_input_bytes:
        raise MediaValidationError(
            f"The source audio exceeds the {max_input_bytes}-byte limit."
        )
    descriptor, raw_path = tempfile.mkstemp(prefix="galaris-voice-", suffix=".ogg")
    os.close(descriptor)
    destination = Path(raw_path)
    try:
        await asyncio.to_thread(
            _transcode_ogg_opus,
            source,
            destination,
            max_duration_seconds=max_duration_seconds,
        )
        if destination.stat().st_size > max_output_bytes:
            raise MediaValidationError(
                f"The normalized audio exceeds the {max_output_bytes}-byte limit."
            )
        yield destination
    finally:
        destination.unlink(missing_ok=True)
