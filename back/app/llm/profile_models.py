"""Persistent models for LLM configuration profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from . import model_usages

PROFILE_MODEL_FIELDS = model_usages.ALL
PROFILE_REASONING_FIELDS = model_usages.TEXT_REASONING_FIELDS


class LlmProfile(Base):
    """Reusable snapshot of configured model values.

    HistoryMixin is intentionally omitted: profiles are parameterizations that
    need no history. The default profile seed keeps the table non-empty.

    Text usages share four tier columns; specialized usages keep dedicated
    columns. The only model selection outside a profile is an agent's or user's voice
    selection. Columns hold LLM ids and use foreign keys without ``ondelete``:
    LLMs are soft-deleted application-side and the purge service clears their
    referencing columns.
    """

    __tablename__ = "llm_profiles"
    decision_fallback_policy: Mapped[str] = mapped_column(
        String(24), default="text_on_failure", server_default="text_on_failure",
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    text_ultra_low_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    text_low_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    text_standard_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    text_high_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    text_ultra_low_reasoning_effort: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    text_low_reasoning_effort: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    text_standard_reasoning_effort: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    text_high_reasoning_effort: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    vision_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    document_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    audio_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    video_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    image_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    sound_generation_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    music_generation_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    video_generation_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    transcription_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    vector_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )
    decision_llm_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llms.id"), nullable=True
    )


class UserLlmPreferences(Base):
    """Personal selections; a null profile follows the current shared profile."""

    __tablename__ = "user_llm_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_profiles.id", ondelete="SET NULL"), nullable=True
    )
    voice_llm_id: Mapped[int | None] = mapped_column(
        ForeignKey("llms.id", ondelete="SET NULL"), nullable=True
    )
    voice_mode: Mapped[str] = mapped_column(String(20), default="tts", server_default="tts")
    voice_code: Mapped[str | None] = mapped_column(String(300), nullable=True)
