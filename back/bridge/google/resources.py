"""Google Cloud Text-to-Speech voice discovery."""

from __future__ import annotations

import re
import time

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from core.util import as_dict, as_list


_PUBLIC_VOICE_URL = (
    "https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types?hl=en"
)
_PUBLIC_VOICE_PATTERN = re.compile(
    r"[a-z]{2,3}-[A-Z]{2}-(?:"
    r"Chirp3-HD-[A-Za-z]+|Chirp-HD-[A-Z]|Neural2-[A-Z]|Standard-[A-Z]|"
    r"Studio-[A-Z]|Wavenet-[A-Z]|Polyglot-[0-9]+|Journey-[A-Z]|Casual-[A-Z]|News-[A-Z]"
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


class GoogleCloudTTSResourceDiscovery:
    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        if capability != "speech":
            return []
        if not connection.api_key:
            return await _public_voices()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{connection.base_url.rstrip('/')}/voices",
                params={"key": connection.api_key},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = as_dict(response.json())
        resources: list[LLMModelInfo] = []
        for raw in as_list(payload.get("voices")):
            voice = as_dict(raw)
            name = str(voice.get("name") or "")
            if not name:
                continue
            languages = ", ".join(
                str(value) for value in as_list(voice.get("languageCodes"))
            )
            resources.append(
                with_capability(
                    LLMModelInfo(
                        id=f"voice:{name}",
                        name=name,
                        description=languages or None,
                        resource_type="voice",
                        metadata_source="provider",
                    ),
                    "speech",
                    resource_type="voice",
                )
            )
        return resources
