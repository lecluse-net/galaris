"""Local speech probabilities over canonical call audio, without network access."""

from __future__ import annotations

import struct

import av
from pysilero_vad import SileroVoiceActivityDetector

from .models import DEFAULT_SAMPLE_RATE


class SpeechDetector:
    """Keep resampling and model state private to one call.

    Silero consumes 32 ms at 16 kHz. Libav resamples continuously so packet
    boundaries and high-frequency noise do not change its input signal.
    """

    def __init__(self) -> None:
        self._model = SileroVoiceActivityDetector()
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
        self._pending = bytearray()
        self._probability = 0.0

    def __call__(self, pcm: bytes) -> bool:
        if not pcm:
            return False
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
        frame.sample_rate = DEFAULT_SAMPLE_RATE
        frame.planes[0].update(pcm)
        for resampled in self._resampler.resample(frame):
            self._pending.extend(bytes(resampled.planes[0])[:resampled.samples * 2])
        while len(self._pending) >= 1024:
            # Explicit little-endian decoding also works on big-endian hosts.
            samples = struct.unpack("<512h", self._pending[:1024])
            self._probability = self._model.process_samples(
                [sample / 32768.0 for sample in samples]
            )
            del self._pending[:1024]
        return self._probability >= 0.5
