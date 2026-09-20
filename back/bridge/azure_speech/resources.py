"""Azure Speech voice discovery."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from core.util import as_dict, as_list


_PUBLIC_VOICE_URL = (
    "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support"
)
_PUBLIC_VOICE_PATTERN = re.compile(
    r"[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+(?:"
    r":(?:DragonHDLatest|DragonHDOmniLatest)Neural|"
    r"(?:Multilingual|TurboMultilingual)?Neural(?:HD)?"
    r")"
)
_PUBLIC_VOICE_CACHE_TTL_SECONDS = 6 * 60 * 60
_public_voice_cache: tuple[float, tuple[str, ...]] | None = None


async def _public_voices() -> list[LLMModelInfo]:
    global _public_voice_cache
    now = time.monotonic()
    if (
        _public_voice_cache is not None
        and now - _public_voice_cache[0] < _PUBLIC_VOICE_CACHE_TTL_SECONDS
    ):
        voice_ids = _public_voice_cache[1]
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                _PUBLIC_VOICE_URL,
                headers={"Accept": "text/html"},
            )
            response.raise_for_status()
            voice_ids = tuple(sorted(set(_PUBLIC_VOICE_PATTERN.findall(response.text))))
        _public_voice_cache = (now, voice_ids)
    return [
        with_capability(
            LLMModelInfo(
                id=f"voice:{voice_id}",
                name=voice_id,
                description=(
                    f"Catalogue public · "
                    f"{voice_id.split('-', 2)[0]}-{voice_id.split('-', 2)[1]}"
                ),
                resource_type="voice",
                metadata_source="public-catalog",
            ),
            "speech",
            resource_type="voice",
        )
        for voice_id in voice_ids
    ]


class AzureSpeechResourceDiscovery:
    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        if capability != "speech":
            return []
        if not connection.api_key:
            return await _public_voices()
        region = str(connection.configuration.get("region") or "").strip().lower()
        if not region:
            raise ValueError("La région Azure Speech est requise")
        url = (
            f"https://{region}.tts.speech.microsoft.com/"
            "cognitiveservices/voices/list"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Ocp-Apim-Subscription-Key": connection.api_key},
            )
            response.raise_for_status()
            payload: Any = response.json()
        resources: list[LLMModelInfo] = []
        for raw in as_list(payload):
            voice = as_dict(raw)
            short_name = str(voice.get("ShortName") or voice.get("Name") or "")
            if not short_name:
                continue
            locale = str(voice.get("LocaleName") or voice.get("Locale") or "")
            styles = ", ".join(
                str(value) for value in as_list(voice.get("StyleList"))
            )
            description = " · ".join(value for value in (locale, styles) if value)
            resources.append(
                with_capability(
                    LLMModelInfo(
                        id=f"voice:{short_name}",
                        name=str(voice.get("DisplayName") or short_name),
                        description=description or None,
                        resource_type="voice",
                        metadata_source="provider",
                    ),
                    "speech",
                    resource_type="voice",
                )
            )
        return resources
