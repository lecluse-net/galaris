"""Transport-neutral models for real-time PCM calls and durable conversations."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin

# Backend-local scratch directory for call audio and PulseAudio sockets.
VOICE_ROOT = Path("/tmp/galaris-voice")

# Canonical bridge PCM: signed 16-bit little-endian mono at native WebRTC/Opus 48 kHz.
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_CHANNELS = 1


@dataclass
class AudioFrame:
    """Raw signed 16-bit little-endian PCM frame."""

    pcm: bytes
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS


class VoiceConversationStatus(str, enum.Enum):
    """Durable lifecycle of one live call."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class VoiceTurnStatus(str, enum.Enum):
    """Durable outcome of one user turn and its conversational response."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class VoiceConversationSession(HistoryMixin, Base):
    """Minimal durable lifecycle for one call inside a Messenger conversation."""

    __tablename__ = "voice_sessions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    messenger_room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_rooms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requester_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=VoiceConversationStatus.ACTIVE.value,
        server_default=VoiceConversationStatus.ACTIVE.value,
        index=True,
    )
    next_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __mapper_args__ = {"version_id_col": revision}
