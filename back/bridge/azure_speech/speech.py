"""Azure AI Speech synthesis."""

from __future__ import annotations

import re
from html import escape

from core.util import post_buffered

from app.llm.provider_facade import (
    ProviderConnection,
    RealtimeSpeechStream,
    SpeechOptions,
    SpeechResult,
)


class AzureSpeech:
    async def synthesize(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        text: str,
        options: SpeechOptions,
    ) -> SpeechResult:
        voice = (
            options.voice.strip().removeprefix("voice:")
            or (
                model.strip().removeprefix("voice:")
                if resource_type == "voice"
                else ""
            )
        )
        if not voice:
            raise ValueError("a configured voice is required")
        if not connection.api_key:
            raise ValueError(f"provider {connection.name} requires an API key")
        region = str(connection.configuration.get("region") or "").strip().lower()
        if not region:
            raise ValueError("a configured region is required")
        match = re.match(r"^([a-z]{2,3}-[A-Z]{2})", voice)
        language = options.language.strip() or (
            match.group(1) if match else "en-US"
        )
        rate = round((options.speed - 1.0) * 100)
        pitch = f"{options.pitch:+g}st"
        ssml = (
            f'<speak version="1.0" xml:lang="{escape(language, quote=True)}">'
            f'<voice name="{escape(voice, quote=True)}">'
            f'<prosody rate="{rate:+d}%" pitch="{pitch}">{escape(text)}</prosody>'
            "</voice></speak>"
        )
        base_url = connection.base_url.replace("{region}", region).rstrip("/")
        content = await post_buffered(
                f"{base_url}/v1",
                headers={
                    "Ocp-Apim-Subscription-Key": connection.api_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": (
                        "audio-24khz-48kbitrate-mono-mp3"
                    ),
                    "User-Agent": "Galaris",
                },
                content=ssml.encode(),
            )
        if not content:
            raise RuntimeError("the speech provider returned an empty audio file")
        return SpeechResult(content, connection.name, voice)

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
