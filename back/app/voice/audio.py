"""Canonical PCM conversion helpers shared by every call transport."""

from __future__ import annotations

import asyncio
import io
from itertools import islice
import math
import struct
import wave
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, cast

from .models import AudioFrame, DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE

if TYPE_CHECKING:
    import av


class _AudioPacket(Protocol):
    def decode(self) -> list["av.AudioFrame"]: ...


class _InputContainer(Protocol):
    def demux(self, **kwargs: int) -> Iterator[_AudioPacket]: ...
    def close(self) -> None: ...

FRAME_MS = 20
BYTES_PER_SAMPLE = 2
FRAME_BYTES = (
    DEFAULT_SAMPLE_RATE
    * DEFAULT_CHANNELS
    * BYTES_PER_SAMPLE
    * FRAME_MS
    // 1000
)
BYTES_PER_SECOND = DEFAULT_SAMPLE_RATE * DEFAULT_CHANNELS * BYTES_PER_SAMPLE


def pcm_rms(pcm: bytes) -> int:
    """Return the RMS amplitude of signed little-endian 16-bit PCM."""
    sample_count = len(pcm) // BYTES_PER_SAMPLE
    if sample_count == 0:
        return 0
    total = sum(
        sample * sample
        for (sample,) in struct.iter_unpack(
            "<h",
            pcm[: sample_count * BYTES_PER_SAMPLE],
        )
    )
    return int(math.sqrt(total / sample_count))


def pcm_to_wav(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> bytes:
    """Wrap raw canonical PCM in an in-memory WAV container."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(BYTES_PER_SAMPLE)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def downsample_pcm_48k_to_24k(pcm: bytes) -> bytes:
    """Downsample canonical mono PCM by retaining every other sample."""

    if len(pcm) % BYTES_PER_SAMPLE:
        raise ValueError("PCM audio ended with an incomplete sample")
    samples = struct.iter_unpack("<h", pcm)
    return b"".join(
        struct.pack("<h", sample)
        for index, (sample,) in enumerate(samples)
        if index % 2 == 0
    )


def upsample_pcm_24k_to_48k(pcm: bytes) -> bytes:
    """Upsample mono PCM with a linear midpoint between source samples."""

    if len(pcm) % BYTES_PER_SAMPLE:
        raise ValueError("PCM audio ended with an incomplete sample")
    samples = [sample for (sample,) in struct.iter_unpack("<h", pcm)]
    if not samples:
        return b""
    output = bytearray()
    for index, sample in enumerate(samples):
        following = samples[index + 1] if index + 1 < len(samples) else sample
        output.extend(struct.pack("<hh", sample, int((sample + following) / 2)))
    return bytes(output)


def _pcm_bytes(frame: Any) -> bytes:
    expected = frame.samples * DEFAULT_CHANNELS * BYTES_PER_SAMPLE
    return bytes(frame.planes[0])[:expected]


def _decode_audio(content: bytes) -> Iterator[bytes]:
    """Decode incrementally; retain at most one decoder packet and one PCM frame."""
    import av

    carry = bytearray()
    resampler = av.AudioResampler(format="s16", layout="mono", rate=DEFAULT_SAMPLE_RATE)
    container = cast(_InputContainer, av.open(io.BytesIO(content), mode="r"))
    try:
        for packet in container.demux(audio=0):
            for frame in packet.decode():
                for resampled in resampler.resample(frame):
                    carry.extend(_pcm_bytes(resampled))
                    while len(carry) >= FRAME_BYTES:
                        yield bytes(carry[:FRAME_BYTES])
                        del carry[:FRAME_BYTES]
        for resampled in resampler.resample(None):
            carry.extend(_pcm_bytes(resampled))
        while len(carry) >= FRAME_BYTES:
            yield bytes(carry[:FRAME_BYTES])
            del carry[:FRAME_BYTES]
        if carry:
            carry.extend(b"\x00" * (FRAME_BYTES - len(carry)))
            yield bytes(carry)
    finally:
        container.close()


async def encoded_audio_frames(content: bytes) -> AsyncIterator[AudioFrame]:
    """Decode off-loop in bounded batches and close the decoder on interruption."""
    from core.util import buffered_io_budget
    from uuid import uuid4

    # Encoded input is already owned by the TTS response. Account for its decoder
    # copy and bounded output, without reserving the full decoded duration.
    async with buffered_io_budget.reserve(2 * len(content) + 1024 * 1024, owner=f"voice:{uuid4()}"):
        iterator = _decode_audio(content)
        try:
            while True:
                pending = asyncio.create_task(asyncio.to_thread(lambda: list(islice(iterator, 50))))
                try:
                    batch = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    # Never close a generator while its decoder thread is running.
                    await pending
                    raise
                if not batch:
                    break
                for pcm in batch:
                    yield AudioFrame(pcm=pcm)
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                await asyncio.to_thread(close)


async def pcm_audio_frames(
    chunks: AsyncIterator[bytes],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> AsyncIterator[AudioFrame]:
    """Frame raw PCM, resampling 24 kHz speech incrementally when necessary."""
    if sample_rate not in {24_000, DEFAULT_SAMPLE_RATE} or channels != DEFAULT_CHANNELS:
        raise ValueError("streaming PCM must use 24 or 48 kHz mono audio")

    carry = bytearray()
    source_carry = bytearray()
    previous_sample: int | None = None
    async for chunk in chunks:
        if sample_rate == DEFAULT_SAMPLE_RATE:
            carry.extend(chunk)
        else:
            source_carry.extend(chunk)
            complete_bytes = len(source_carry) - len(source_carry) % BYTES_PER_SAMPLE
            for (sample,) in struct.iter_unpack(
                "<h",
                source_carry[:complete_bytes],
            ):
                if previous_sample is not None:
                    midpoint = int((previous_sample + sample) / 2)
                    carry.extend(struct.pack("<hh", previous_sample, midpoint))
                previous_sample = sample
            del source_carry[:complete_bytes]

        while len(carry) >= FRAME_BYTES:
            yield AudioFrame(pcm=bytes(carry[:FRAME_BYTES]))
            del carry[:FRAME_BYTES]

    if source_carry:
        raise ValueError("streaming PCM ended with an incomplete sample")
    if sample_rate == 24_000 and previous_sample is not None:
        carry.extend(struct.pack("<hh", previous_sample, previous_sample))

    if carry:
        carry.extend(b"\x00" * (FRAME_BYTES - len(carry)))
        yield AudioFrame(pcm=bytes(carry))
