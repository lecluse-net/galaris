"""Provider-neutral audio transcription for messaging and live voice calls."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

import httpx

from core.util import as_dict

from . import llm_call_service, llm_provider_service, llm_service
from .purposes import LLMCallPurpose
from .provider_facade import (
    ProviderTranscriptionError,
    RealtimeTranscriber,
    TranscriptionResult,
    realtime_transcription_provider_for,
    transcription_provider_for,
)
from .resource_discovery import provider_connection


class TranscriptionNotConfigured(ValueError):
    """Raised when no usable transcription resource is configured."""


# Stable public exception name for callers of this facade.
TranscriptionFailed = ProviderTranscriptionError


_AUDIO_FORMATS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/oga": "ogg",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
}
_PCM_SAMPLE_RATES = {8_000, 16_000, 22_050, 24_000, 44_100, 48_000}


def audio_format(mime_type: str, filename: str = "") -> str:
    """Infer a protocol-level audio format from a MIME type or filename."""

    detected = _AUDIO_FORMATS.get((mime_type or "").lower())
    if detected:
        return detected
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    return "ogg" if extension == "oga" else extension


async def _selected_resource(agent_id: int | None = None, *, user_id: int | None = None):
    if user_id is not None:
        from .personal_service import transcription_resource

        resource = await transcription_resource(user_id)
    else:
        resource = await llm_service.get_transcription_llm(agent_id)
    if resource is None:
        raise TranscriptionNotConfigured("no transcription resource is configured")
    if not resource.provider.is_active:
        raise TranscriptionNotConfigured("the transcription provider is disabled")
    base_url = llm_provider_service.transcription_base_url(
        resource.provider
    ).rstrip("/")
    if not base_url:
        raise TranscriptionNotConfigured("the transcription provider has no endpoint")
    api_key = (
        llm_provider_service.decrypt_api_key(resource.provider.api_key) or ""
    ).strip()
    connection = replace(
        provider_connection(resource.provider, api_key),
        base_url=base_url,
    )
    return resource, connection


async def create_realtime_transcriber(
    *,
    agent_id: int | None = None,
    language: str = "",
    sample_rate: int = 48_000,
    channels: int = 1,
) -> RealtimeTranscriber | None:
    """Open a live STT session when the selected bridge exposes that capability."""

    if sample_rate not in _PCM_SAMPLE_RATES or channels != 1:
        return None
    try:
        resource, connection = await _selected_resource(agent_id)
    except TranscriptionNotConfigured:
        return None
    service = realtime_transcription_provider_for(connection)
    if service is None:
        return None
    return await service.create_realtime_transcriber(
        connection,
        model=resource.llm_name,
        language=language,
        sample_rate=sample_rate,
        channels=channels,
    )


async def transcription_available_for_agent(agent_id: int) -> bool:
    """Return whether the agent profile exposes a usable STT resource."""

    try:
        _resource, connection = await _selected_resource(agent_id)
    except (TranscriptionNotConfigured, ValueError):
        return False
    return (
        transcription_provider_for(connection) is not None
        or connection.provider_type == "openai_compatible"
    )


async def transcribe_audio(
    content: bytes,
    *,
    filename: str = "audio.wav",
    mime_type: str = "audio/wav",
    language: str = "",
    agent_id: int | None = None,
    user_id: int | None = None,
) -> str:
    """Transcribe one complete audio utterance with the configured STT resource."""

    if not content:
        raise ValueError("audio content must not be empty")
    return await _transcribe_audio_source(
        content,
        filename=filename,
        mime_type=mime_type,
        language=language,
        agent_id=agent_id,
        timeout=120.0,
        user_id=user_id,
    )


async def transcribe_audio_file(
    path: Path,
    *,
    filename: str = "",
    mime_type: str = "application/octet-stream",
    language: str = "",
    agent_id: int | None = None,
) -> str:
    """Transcribe a file, streaming multipart uploads from disk when supported."""

    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("audio file must exist and not be empty")
    return await _transcribe_audio_source(
        path,
        filename=filename or path.name,
        mime_type=mime_type,
        language=language,
        agent_id=agent_id,
        timeout=900.0,
    )


async def _transcribe_audio_source(
    source: bytes | Path,
    *,
    filename: str,
    mime_type: str,
    language: str,
    agent_id: int | None,
    timeout: float,
    user_id: int | None = None,
) -> str:
    if user_id is not None:
        resource, connection = await _selected_resource(agent_id, user_id=user_id)
    else:
        resource, connection = await _selected_resource(agent_id)
    service = transcription_provider_for(connection)
    if service is None and connection.provider_type != "openai_compatible":
        raise TranscriptionNotConfigured(
            f"no transcription bridge is registered for {connection.name}"
        )

    size_bytes = source.stat().st_size if isinstance(source, Path) else len(source)
    provider = resource.provider
    call = await llm_call_service.create_running_call(
        purpose=LLMCallPurpose.AUDIO_TRANSCRIPTION,
        requester_user_id=user_id,
        task_id=None,
        agent_run_id=None,
        agent_id=agent_id,
        llm_id=resource.id,
        provider_name=provider.name,
        provider_code=provider.catalog_code
        or (
            provider.provider_type
            if provider.provider_type != "openai_compatible"
            else None
        ),
        requested_model=resource.llm_name,
        effective_model=resource.llm_name,
        stream=False,
        request_body={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Audio transcription request\n"
                        f"filename: {filename}\n"
                        f"mime_type: {mime_type}\n"
                        f"size_bytes: {size_bytes}\n"
                        f"language: {language.strip() or 'auto'}"
                    ),
                }
            ]
        },
        is_subscription=bool(getattr(resource, "is_subscription", False)),
    )
    try:
        if service is not None:
            result = await service.transcribe(
                connection,
                model=resource.llm_name,
                source=source,
                filename=filename,
                mime_type=mime_type,
                language=language,
                timeout=timeout,
            )
        else:
            result = await _transcribe_openai_compatible(
                connection.base_url,
                connection.api_key,
                model=resource.llm_name,
                source=source,
                filename=filename,
                mime_type=mime_type,
                language=language,
                timeout=timeout,
            )
    except Exception as exc:
        await llm_call_service.finalize_call(
            call.id,
            trace={},
            raw_response=(
                exc.raw_response
                if isinstance(exc, ProviderTranscriptionError)
                else None
            ),
            status="error",
            error=str(exc),
            input_rate=resource.cost_per_input_token,
            cached_input_rate=resource.cost_per_cached_input_token,
            output_rate=resource.cost_per_output_token,
        )
        raise

    usage = dict(result.usage)
    usage.setdefault("audio_bytes", size_bytes)
    await llm_call_service.finalize_call(
        call.id,
        trace={
            "response_text": result.text,
            "finish_reason": "stop",
            "usage": usage,
            "upstream_request_id": result.upstream_request_id,
        },
        raw_response=result.raw_response,
        input_rate=resource.cost_per_input_token,
        cached_input_rate=resource.cost_per_cached_input_token,
        output_rate=resource.cost_per_output_token,
    )
    return result.text


async def _transcribe_openai_compatible(
    base_url: str,
    api_key: str | None,
    *,
    model: str,
    source: bytes | Path,
    filename: str,
    mime_type: str,
    language: str,
    timeout: float,
) -> TranscriptionResult:
    data = {"model": model}
    language_code = language.strip().lower().split("-", 1)[0]
    if language_code:
        data["language"] = language_code
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    raw_response = ""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await _post_multipart_audio(
                client,
                f"{base_url}/audio/transcriptions",
                source,
                filename=filename,
                mime_type=mime_type,
                data=data,
                headers=headers,
            )
            raw_response = response.content.decode("utf-8", errors="replace")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise TranscriptionFailed(
            f"the transcription provider returned HTTP {exc.response.status_code}",
            raw_response=exc.response.content.decode("utf-8", errors="replace"),
        ) from exc
    except httpx.RequestError as exc:
        raise TranscriptionFailed("the transcription provider request failed") from exc
    except ValueError as exc:
        raise TranscriptionFailed(
            "the transcription provider returned invalid JSON",
            raw_response=raw_response,
        ) from exc
    text = (
        str(as_dict(payload).get("text") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if not text:
        raise TranscriptionFailed(
            "the transcription provider returned no text",
            raw_response=raw_response,
        )
    usage = as_dict(payload).get("usage") if isinstance(payload, dict) else None
    response_headers = getattr(response, "headers", {})
    request_id = (
        response_headers.get("x-request-id")
        if hasattr(response_headers, "get")
        else None
    )
    return TranscriptionResult(
        text=text,
        usage=as_dict(usage),
        upstream_request_id=str(request_id) if request_id else None,
        raw_response=raw_response,
    )


async def _post_multipart_audio(
    client: httpx.AsyncClient,
    url: str,
    source: bytes | Path,
    *,
    filename: str,
    mime_type: str,
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    if isinstance(source, Path):
        with source.open("rb") as audio_file:
            return await _post_audio_file(
                client,
                url,
                audio_file,
                filename=filename,
                mime_type=mime_type,
                data=data,
                headers=headers,
            )
    return await client.post(
        url,
        data=data,
        files={"file": (filename, source, mime_type)},
        headers=headers,
    )


async def _post_audio_file(
    client: httpx.AsyncClient,
    url: str,
    audio_file: BinaryIO,
    *,
    filename: str,
    mime_type: str,
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    return await client.post(
        url,
        data=data,
        files={"file": (filename, audio_file, mime_type)},
        headers=headers,
    )


__all__ = [
    "RealtimeTranscriber",
    "TranscriptionFailed",
    "TranscriptionNotConfigured",
    "audio_format",
    "create_realtime_transcriber",
    "transcription_available_for_agent",
    "transcribe_audio",
    "transcribe_audio_file",
]
