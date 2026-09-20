"""Ephemeral progress events for human voice transcription."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from loguru import logger


VoiceTranscriptionStatus = Literal["started", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class VoiceTranscriptionEvent:
    """One bounded UI projection of a human utterance being transcribed."""

    room_id: UUID
    transcription_id: UUID
    status: VoiceTranscriptionStatus
    started_at: datetime
    message_id: UUID | None = None


VoiceTranscriptionListener = Callable[[VoiceTranscriptionEvent], Awaitable[None]]
_listeners: set[VoiceTranscriptionListener] = set()


def register_voice_transcription_listener(
    listener: VoiceTranscriptionListener,
) -> None:
    """Subscribe an adapter to transient human transcription progress."""

    _listeners.add(listener)


def unregister_voice_transcription_listener(
    listener: VoiceTranscriptionListener,
) -> None:
    _listeners.discard(listener)


async def publish_voice_transcription(event: VoiceTranscriptionEvent) -> None:
    """Publish progress without persisting an empty Messenger message."""

    for listener in tuple(_listeners):
        try:
            await listener(event)
        except Exception:
            logger.exception(
                "Voice transcription listener failed room={} transcription={} status={}",
                event.room_id,
                event.transcription_id,
                event.status,
            )


__all__ = [
    "VoiceTranscriptionEvent",
    "VoiceTranscriptionListener",
    "VoiceTranscriptionStatus",
    "publish_voice_transcription",
    "register_voice_transcription_listener",
    "unregister_voice_transcription_listener",
]
