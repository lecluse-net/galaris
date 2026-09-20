"""OpenRouter audio-transcription payload adaptation."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from app.llm.provider_facade import (
    ProviderConnection,
    ProviderTranscriptionError,
    TranscriptionResult,
)
from core.util import as_dict


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


def _audio_format(mime_type: str, filename: str) -> str:
    detected = _AUDIO_FORMATS.get((mime_type or "").lower())
    if detected:
        return detected
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    return "ogg" if extension == "oga" else extension


class OpenRouterTranscription:
    async def transcribe(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        source: bytes | Path,
        filename: str,
        mime_type: str,
        language: str,
        timeout: float,
    ) -> TranscriptionResult:
        content = source.read_bytes() if isinstance(source, Path) else source
        payload: dict[str, object] = {
            "model": model,
            "input_audio": {
                "data": base64.b64encode(content).decode("ascii"),
                "format": _audio_format(mime_type, filename),
            },
        }
        language_code = language.strip().lower().split("-", 1)[0]
        if language_code:
            payload["language"] = language_code
        headers = (
            {"Authorization": f"Bearer {connection.api_key}"}
            if connection.api_key
            else {}
        )
        raw_response = ""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{connection.base_url.rstrip('/')}/audio/transcriptions",
                    json=payload,
                    headers=headers,
                )
                raw_response = response.content.decode("utf-8", errors="replace")
                response.raise_for_status()
                result = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderTranscriptionError(
                f"the transcription provider returned HTTP {exc.response.status_code}",
                raw_response=exc.response.content.decode("utf-8", errors="replace"),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderTranscriptionError(
                "the transcription provider request failed"
            ) from exc
        except ValueError as exc:
            raise ProviderTranscriptionError(
                "the transcription provider returned invalid JSON",
                raw_response=raw_response,
            ) from exc
        text = (
            str(as_dict(result).get("text") or "").strip()
            if isinstance(result, dict)
            else ""
        )
        if not text:
            raise ProviderTranscriptionError(
                "the transcription provider returned no text",
                raw_response=raw_response,
            )
        payload_result = as_dict(result)
        return TranscriptionResult(
            text=text,
            usage=as_dict(payload_result.get("usage")),
            upstream_request_id=response.headers.get("x-request-id"),
            raw_response=raw_response,
        )
