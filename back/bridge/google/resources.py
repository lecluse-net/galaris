"""Google Cloud Text-to-Speech voice discovery."""

from __future__ import annotations

import re

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection, PublicVoiceCatalog
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
_public_voice_catalog = PublicVoiceCatalog(_PUBLIC_VOICE_URL, _PUBLIC_VOICE_PATTERN)


class GoogleCloudTTSResourceDiscovery:
    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        if capability != "speech":
            return []
        if not connection.api_key:
            return await _public_voice_catalog.list_resources()
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
