"""Provider-neutral text-to-speech generation for configured agent voices."""

from __future__ import annotations

from typing import Any, Optional

import httpx
from core.util import post_buffered

from . import llm_provider_service, llm_service
from .provider_facade import (
    RealtimeSpeechStream,
    SpeechOptions,
    SpeechResult,
    speech_provider_for,
)
from .provider_models import LLM
from .resource_discovery import provider_connection


class TTSNotConfigured(ValueError):
    """Raised when an agent has no usable speech resource configured."""


class TTSProviderUnsupported(ValueError):
    """Raised when the selected provider cannot return MP3 speech."""


class TTSStreamingUnavailable(RuntimeError):
    """Raised when a realtime speech connection cannot be established."""


# Stable public names kept for callers of the app.llm speech facade.
TTSOptions = SpeechOptions
GeneratedSpeech = SpeechResult


def _require_range(name: str, value: float, minimum: float, maximum: float) -> float:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _optional_range(
    name: str,
    value: Optional[float],
    minimum: float,
    maximum: float,
) -> Optional[float]:
    if value is None:
        return None
    return _require_range(name, value, minimum, maximum)


def _validate_options(options: TTSOptions) -> None:
    _require_range("speed", options.speed, 0.25, 4.0)
    _require_range("pitch", options.pitch, -20.0, 20.0)
    _optional_range("stability", options.stability, 0.0, 1.0)
    _optional_range("similarity_boost", options.similarity_boost, 0.0, 1.0)
    _optional_range("style", options.style, 0.0, 1.0)


def _validate(message: str, options: TTSOptions) -> str:
    text = (message or "").strip()
    if not text:
        raise ValueError("message must not be empty")
    if len(text) > 10_000:
        raise ValueError("message must not exceed 10,000 characters")
    _validate_options(options)
    return text


def _clean_resource_id(value: str) -> str:
    return (value or "").strip().removeprefix("voice:")


def _selected_voice(resource: LLM, options: TTSOptions, default: str = "") -> str:
    if options.voice.strip():
        return _clean_resource_id(options.voice)
    if resource.resource_type == "voice":
        return _clean_resource_id(resource.llm_name)
    return default


def _selected_model(resource: LLM, options: TTSOptions, default: str) -> str:
    if options.model.strip():
        return options.model.strip()
    if resource.resource_type != "voice":
        return resource.llm_name.strip()
    return default


def _api_key(resource: LLM) -> str:
    key = llm_provider_service.decrypt_api_key(resource.provider.api_key)
    if not key:
        raise ValueError(
            f"provider {resource.provider.name} requires an API key for speech generation"
        )
    return key


async def _post_mp3(
    url: str,
    *,
    headers: dict[str, str],
    json: Any = None,
) -> bytes:
    try:
        content = await post_buffered(url, headers=headers, json=json)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"the TTS provider returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError("the TTS provider request failed") from exc
    if not content:
        raise RuntimeError("the TTS provider returned an empty audio file")
    return content


async def _generate_openai_compatible(
    resource: LLM,
    text: str,
    options: TTSOptions,
) -> GeneratedSpeech:
    """Use the canonical OpenAI-compatible speech endpoint."""

    voice = _selected_voice(resource, options, "alloy")
    model = _selected_model(resource, options, "gpt-4o-mini-tts")
    audio = await _post_mp3(
        f"{resource.provider.base_url.rstrip('/')}/audio/speech",
        headers={
            "Authorization": f"Bearer {_api_key(resource)}",
            "Accept": "audio/mpeg",
        },
        json={
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": options.speed,
        },
    )
    return GeneratedSpeech(audio, resource.provider.name, voice)


async def _resource_for_agent(agent_id: int) -> LLM:
    from app.agent import agent_service
    from app.agent.voice import parse_voice_selection

    agent = await agent_service.get(agent_id)
    selection = (
        parse_voice_selection(getattr(agent, "voice", None))
        if agent is not None
        else None
    )
    if selection is None or selection.mode != "tts":
        raise TTSNotConfigured("no TTS resource is configured for this agent")
    resource = await llm_service.get_llm(selection.model_id)
    if resource is None or "speech" not in resource.service_capabilities:
        raise TTSNotConfigured("the configured TTS resource is unavailable or invalid")
    if not resource.provider.is_active:
        raise TTSNotConfigured("the configured TTS provider is disabled")
    return resource


def _connection(resource: LLM):
    return provider_connection(
        resource.provider,
        llm_provider_service.decrypt_api_key(resource.provider.api_key),
    )


async def create_realtime_speech_stream_for_agent(
    agent_id: int,
    options: Optional[TTSOptions] = None,
) -> RealtimeSpeechStream | None:
    """Prepare native streaming speech when the selected bridge supports it."""

    selected_options = options or TTSOptions()
    _validate_options(selected_options)
    resource = await _resource_for_agent(agent_id)
    return await create_realtime_speech_stream_for_resource(
        resource.id,
        selected_options,
    )


async def speech_available_for_agent(agent_id: int) -> bool:
    """Return whether the agent's selected TTS resource can synthesize MP3 audio."""

    try:
        resource = await _resource_for_agent(agent_id)
        connection = _connection(resource)
    except (TTSNotConfigured, ValueError):
        return False
    return (
        speech_provider_for(connection) is not None
        or resource.provider.provider_type == "openai_compatible"
    )


async def create_realtime_speech_stream_for_resource(
    resource_id: int,
    options: Optional[TTSOptions] = None,
) -> RealtimeSpeechStream | None:
    """Prepare streaming speech for an explicitly selected voice resource."""

    selected_options = options or TTSOptions()
    _validate_options(selected_options)
    resource = await llm_service.get_llm(resource_id)
    if resource is None or "speech" not in resource.service_capabilities:
        raise TTSNotConfigured("the configured voice resource is unavailable or invalid")
    if not resource.provider.is_active:
        raise TTSNotConfigured("the configured voice provider is disabled")
    connection = _connection(resource)
    service = speech_provider_for(connection)
    if service is None:
        return None
    try:
        return await service.create_realtime_stream(
            connection,
            model=resource.llm_name,
            resource_type=resource.resource_type,
            options=selected_options,
        )
    except RuntimeError as exc:
        raise TTSStreamingUnavailable(str(exc)) from exc


async def generate_for_agent(
    agent_id: int,
    message: str,
    options: Optional[TTSOptions] = None,
) -> GeneratedSpeech:
    """Generate MP3 speech through a provider bridge or the canonical protocol."""

    selected_options = options or TTSOptions()
    text = _validate(message, selected_options)
    resource = await _resource_for_agent(agent_id)
    return await _generate_resource(resource, text, selected_options)


async def generate_for_resource(
    resource_id: int,
    message: str,
    options: Optional[TTSOptions] = None,
) -> GeneratedSpeech:
    """Synthesize with an explicitly selected, active speech resource."""
    selected_options = options or TTSOptions()
    text = _validate(message, selected_options)
    resource = await llm_service.get_llm(resource_id)
    if resource is None or "speech" not in resource.service_capabilities:
        raise TTSNotConfigured("the configured voice resource is unavailable or invalid")
    if not resource.provider.is_active:
        raise TTSNotConfigured("the configured voice provider is disabled")
    return await _generate_resource(resource, text, selected_options)


async def _generate_resource(
    resource: LLM, text: str, selected_options: TTSOptions,
) -> GeneratedSpeech:
    connection = _connection(resource)
    service = speech_provider_for(connection)
    if service is not None:
        try:
            return await service.synthesize(
                connection,
                model=resource.llm_name,
                resource_type=resource.resource_type,
                text=text,
                options=selected_options,
            )
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"the TTS provider returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError("the TTS provider request failed") from exc
    if resource.provider.provider_type == "openai_compatible":
        return await _generate_openai_compatible(resource, text, selected_options)
    raise TTSProviderUnsupported(
        f"provider {resource.provider.name} cannot generate MP3 speech messages"
    )


__all__ = [
    "GeneratedSpeech",
    "RealtimeSpeechStream",
    "TTSNotConfigured",
    "TTSOptions",
    "TTSProviderUnsupported",
    "TTSStreamingUnavailable",
    "create_realtime_speech_stream_for_agent",
    "create_realtime_speech_stream_for_resource",
    "generate_for_agent",
    "generate_for_resource",
    "speech_available_for_agent",
]
