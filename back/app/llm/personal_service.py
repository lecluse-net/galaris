"""Human-owned model selections and document speech, independent of agents."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from typing import Literal, Self
import httpx

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.database import get_db
from core.util import visible_text

from . import llm_service, llm_provider_service, profile_service, tts_service
from .profile_models import UserLlmPreferences
from .provider_models import LLM


class PersonalPreferences(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    profile_id: int | None = Field(default=None, gt=0)
    voice_llm_id: int | None = Field(default=None, gt=0)
    voice_mode: Literal["tts", "realtime"] = "tts"
    voice_code: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_voice(self) -> Self:
        if self.voice_mode == "realtime":
            if self.voice_llm_id is None or not self.voice_code or not self.voice_code.strip():
                raise ValueError("a realtime voice requires a model and a voice code")
            self.voice_code = self.voice_code.strip()
        elif self.voice_code is not None:
            raise ValueError("TTS selections do not have a native voice code")
        return self


class PersonalSpeechError(ValueError):
    """Stable localized error code for personal audio operations."""


async def preferences(user_id: int) -> PersonalPreferences:
    row = (
        await get_db().execute(
            select(UserLlmPreferences).where(UserLlmPreferences.user_id == user_id)
        )
    ).scalar_one_or_none()
    return PersonalPreferences.model_validate(row) if row else PersonalPreferences()


async def save_preferences(user_id: int, values: PersonalPreferences) -> PersonalPreferences:
    if (
        values.profile_id is not None
        and await profile_service.get_profile(values.profile_id) is None
    ):
        raise PersonalSpeechError("profile_unavailable")
    if values.voice_llm_id is not None:
        resource = await llm_service.get_llm(values.voice_llm_id)
        capability = "speech" if values.voice_mode == "tts" else "realtime_conversation"
        if (
            resource is None
            or not resource.provider.is_active
            or capability not in resource.service_capabilities
        ):
            raise PersonalSpeechError("voice_unavailable")
    statement = insert(UserLlmPreferences).values(user_id=user_id, **values.model_dump())
    await get_db().execute(
        statement.on_conflict_do_update(
            index_elements=[UserLlmPreferences.user_id],
            set_=values.model_dump(),
        )
    )
    await get_db().commit()
    return await preferences(user_id)


class SelectionOption(BaseModel):
    id: int
    label: str


class NativeVoiceOption(BaseModel):
    model_id: int
    voice_code: str
    label: str
    caption: str


class PersonalOptions(BaseModel):
    profiles: list[SelectionOption]
    current_profile_id: int | None
    voices: list[SelectionOption]
    native_voices: list[NativeVoiceOption]
    native_voices_error: bool = False


async def selection_options() -> PersonalOptions:
    resources = [r for r in await llm_service.list_llms() if r.provider.is_active]
    native: list[NativeVoiceOption] = []
    native_error = False
    providers: dict[int, list[LLM]] = {}
    for resource in resources:
        if "realtime_conversation" in resource.service_capabilities:
            providers.setdefault(resource.llm_provider_id, []).append(resource)
    for provider_id, models in providers.items():
        try:
            voices = await llm_provider_service.list_resources(provider_id, capability="speech")
        except httpx.HTTPError, ValueError, RuntimeError:
            native_error = True
            continue
        for model in models:
            native.extend(
                NativeVoiceOption(
                    model_id=model.id,
                    voice_code=voice.id,
                    label=voice.name or voice.id.removeprefix("voice:"),
                    caption=f"{model.provider.name} · {model.label}",
                )
                for voice in voices
                if voice.resource_type == "voice"
            )
    return PersonalOptions(
        profiles=[
            SelectionOption(id=p.id, label=p.label) for p in await profile_service.list_profiles()
        ],
        current_profile_id=await profile_service.get_current_profile_id(),
        voices=[
            SelectionOption(id=r.id, label=f"{r.provider.name} — {r.label}")
            for r in resources
            if "speech" in r.service_capabilities
        ],
        native_voices=native,
        native_voices_error=native_error,
    )


async def transcription_resource(user_id: int) -> LLM:
    selected = await preferences(user_id)
    profile_id = selected.profile_id
    if profile_id is None:
        profile_id = await profile_service.get_current_profile_id()
    profile = await profile_service.get_profile(profile_id) if profile_id is not None else None
    resource = (
        await llm_service.get_llm(profile.transcription_llm_id)
        if profile and profile.transcription_llm_id
        else None
    )
    if (
        resource is None
        or not resource.provider.is_active
        or "transcription" not in resource.service_capabilities
    ):
        raise PersonalSpeechError("transcription_unavailable")
    return resource


def speech_chunk(html: str, offset: int) -> tuple[str, int, bool]:
    """Extract editorial text, preserving order and never truncating the document."""
    # The editorial extractor keeps block/line breaks and separates table cells
    # with tabs. Speech needs audible boundaries for those layout separators too.
    text = visible_text(html).replace("\t", "\n")
    if not text.strip():
        raise PersonalSpeechError("empty_document")
    if offset < 0 or offset >= len(text):
        raise PersonalSpeechError("invalid_offset")
    end = min(offset + 2000, len(text))
    if end < len(text):
        boundary = max(text.rfind("\n", offset + 1000, end), text.rfind(" ", offset + 1000, end))
        if boundary > offset:
            end = boundary + 1
    return text[offset:end], end, end == len(text)


async def read_document(user_id: int, html: str, offset: int) -> tuple[bytes, int, bool]:
    selected = await preferences(user_id)
    if selected.voice_llm_id is None or selected.voice_mode != "tts":
        raise PersonalSpeechError("voice_unavailable")
    text, next_offset, done = speech_chunk(html, offset)
    audio = await tts_service.generate_for_resource(selected.voice_llm_id, text)
    return audio.content, next_offset, done
