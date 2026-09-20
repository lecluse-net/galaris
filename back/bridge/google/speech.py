"""Google speech-provider implementations."""

from __future__ import annotations

import base64
import re
import json

from core.util import post_buffered

from app.llm.provider_facade import (
    ProviderConnection,
    RealtimeSpeechStream,
    SpeechOptions,
    SpeechResult,
)


def _voice(resource_type: str, model: str, options: SpeechOptions) -> str:
    if options.voice.strip():
        return options.voice.strip().removeprefix("voice:")
    if resource_type == "voice":
        return model.strip().removeprefix("voice:")
    return ""


class GoogleCloudSpeech:
    async def synthesize(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        text: str,
        options: SpeechOptions,
    ) -> SpeechResult:
        voice = _voice(resource_type, model, options)
        if not voice:
            raise ValueError("a configured voice is required")
        if not connection.api_key:
            raise ValueError(f"provider {connection.name} requires an API key")
        match = re.match(r"^([a-z]{2,3}-[A-Z]{2})", voice)
        language = options.language.strip() or (
            match.group(1) if match else "en-US"
        )
        content = await post_buffered(
                f"{connection.base_url.rstrip('/')}/text:synthesize",
                headers={"X-Goog-Api-Key": connection.api_key},
                json={
                    "input": {"text": text},
                    "voice": {"name": voice, "languageCode": language},
                    "audioConfig": {
                        "audioEncoding": "MP3",
                        "speakingRate": options.speed,
                        "pitch": options.pitch,
                    },
                },
            )
        encoded = json.loads(content).get("audioContent")
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("the speech provider returned no audio content")
        return SpeechResult(
            base64.b64decode(encoded, validate=True),
            connection.name,
            voice,
        )

    async def create_realtime_stream(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        options: SpeechOptions,
    ) -> RealtimeSpeechStream | None:
        del connection, model, resource_type, options
        return None


class GeminiSpeech:
    async def synthesize(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        text: str,
        options: SpeechOptions,
    ) -> SpeechResult:
        del connection, model, resource_type, text, options
        raise ValueError(
            "this provider returns raw PCM and cannot generate an MP3 message"
        )

    async def create_realtime_stream(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        options: SpeechOptions,
    ) -> RealtimeSpeechStream | None:
        del connection, model, resource_type, options
        return None
