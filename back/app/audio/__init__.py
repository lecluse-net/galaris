"""Audio-file processing exposed through canonical resource URI tools."""

from . import audio_service
from .isolated_normalization import normalize_for_transcription_chunks_isolated
from .audio_service import (
    AudioChunk,
    AudioConversionFailed,
    TRANSCRIPTION_CHUNK_SECONDS,
    media_audio_duration,
    normalize_for_transcription,
    normalize_for_transcription_chunks,
)

__all__ = [
    "audio_service",
    "AudioChunk",
    "AudioConversionFailed",
    "TRANSCRIPTION_CHUNK_SECONDS",
    "media_audio_duration",
    "normalize_for_transcription",
    "normalize_for_transcription_chunks",
    "normalize_for_transcription_chunks_isolated",
]
