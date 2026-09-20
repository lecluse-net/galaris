from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import av
import pytest

from app.messenger.media import MediaValidationError, normalized_voice_note


def _write_wav(path: Path, duration: float = 0.1) -> None:
    sample_rate = 16_000
    samples = int(sample_rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(
            b"".join(
                struct.pack("<h", int(4_000 * math.sin(index / 20)))
                for index in range(samples)
            )
        )


@pytest.mark.asyncio
async def test_voice_note_is_normalized_to_ogg_opus(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)
    generated: Path | None = None
    async with normalized_voice_note(
        source,
        max_input_bytes=1_000_000,
        max_output_bytes=1_000_000,
        max_duration_seconds=10,
    ) as output:
        generated = output
        assert output.suffix == ".ogg"
        with av.open(str(output)) as container:
            stream = next(item for item in container.streams if item.type == "audio")
            assert stream.codec_context.name == "opus"
    assert generated is not None and not generated.exists()


@pytest.mark.asyncio
async def test_voice_note_rejects_oversized_source(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _write_wav(source)
    with pytest.raises(MediaValidationError):
        async with normalized_voice_note(
            source,
            max_input_bytes=10,
            max_output_bytes=1_000_000,
            max_duration_seconds=10,
        ):
            pass


@pytest.mark.asyncio
async def test_voice_note_rejects_excessive_duration(tmp_path: Path) -> None:
    source = tmp_path / "long.wav"
    _write_wav(source, duration=1.2)
    with pytest.raises(MediaValidationError, match="duration"):
        async with normalized_voice_note(
            source,
            max_input_bytes=1_000_000,
            max_output_bytes=1_000_000,
            max_duration_seconds=1,
        ):
            pass
