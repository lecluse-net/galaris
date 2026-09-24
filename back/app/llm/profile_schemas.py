"""API schemas for LLM configuration profiles."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .provider_facade import ReasoningEffort


class LlmProfileCreate(BaseModel):
    """Creation payload: a profile starts with only a label and no values."""

    label: str

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        if len(value) > 100:
            raise ValueError("too_long")
        return value


class LlmProfileUpdate(BaseModel):
    """Update payload: rename and/or set profile columns.

    A column of ``None`` clears that usage in this profile. Absent keys are
    left untouched; profiles are never mixed during resolution.
    """

    label: Optional[str] = None
    text_ultra_low_llm_id: Optional[int] = None
    text_low_llm_id: Optional[int] = None
    text_standard_llm_id: Optional[int] = None
    text_high_llm_id: Optional[int] = None
    text_ultra_low_reasoning_effort: ReasoningEffort | None = None
    text_low_reasoning_effort: ReasoningEffort | None = None
    text_standard_reasoning_effort: ReasoningEffort | None = None
    text_high_reasoning_effort: ReasoningEffort | None = None
    vision_llm_id: Optional[int] = None
    document_llm_id: Optional[int] = None
    audio_llm_id: Optional[int] = None
    video_llm_id: Optional[int] = None
    sound_generation_llm_id: Optional[int] = None
    music_generation_llm_id: Optional[int] = None
    video_generation_llm_id: Optional[int] = None
    image_llm_id: Optional[int] = None
    transcription_llm_id: Optional[int] = None
    vector_llm_id: Optional[int] = None
    decision_llm_id: Optional[int] = None
    decision_fallback_policy: Literal["text_on_failure", "disabled"] = "text_on_failure"

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("empty")
        if len(value) > 100:
            raise ValueError("too_long")
        return value


class LlmProfileOut(BaseModel):
    """Complete profile with one field per model column (never auto-applied)."""

    id: int
    label: str
    created_at: datetime
    updated_at: datetime
    text_ultra_low_llm_id: Optional[int] = None
    text_low_llm_id: Optional[int] = None
    text_standard_llm_id: Optional[int] = None
    text_high_llm_id: Optional[int] = None
    text_ultra_low_reasoning_effort: ReasoningEffort | None = None
    text_low_reasoning_effort: ReasoningEffort | None = None
    text_standard_reasoning_effort: ReasoningEffort | None = None
    text_high_reasoning_effort: ReasoningEffort | None = None
    vision_llm_id: Optional[int] = None
    document_llm_id: Optional[int] = None
    audio_llm_id: Optional[int] = None
    video_llm_id: Optional[int] = None
    sound_generation_llm_id: Optional[int] = None
    music_generation_llm_id: Optional[int] = None
    video_generation_llm_id: Optional[int] = None
    image_llm_id: Optional[int] = None
    transcription_llm_id: Optional[int] = None
    vector_llm_id: Optional[int] = None
    decision_llm_id: Optional[int] = None
    decision_fallback_policy: Literal["text_on_failure", "disabled"] = "text_on_failure"

    model_config = ConfigDict(from_attributes=True)


class LlmProfileListResponse(BaseModel):
    """List of profiles for the usage page banner."""

    profiles: list[LlmProfileOut]
    current_profile_id: Optional[int] = None


class LlmProfileUseResponse(BaseModel):
    """Result of using a profile: it becomes the current profile."""

    profile_id: int
    current_profile_id: int
