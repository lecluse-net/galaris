"""ElevenLabs model and voice discovery."""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from core.util import as_dict, as_list


def _headers(connection: ProviderConnection) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if connection.api_key:
        headers["xi-api-key"] = connection.api_key
    return headers


class ElevenLabsResourceDiscovery:
    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        if capability in {"music_generation", "sound_generation"}:
            names = ("music_v1", "music_v2") if capability == "music_generation" else ("eleven_text_to_sound_v2",)
            return [with_capability(LLMModelInfo(
                id=name, name=name, metadata_source="provider-catalog",
                service_capabilities=[capability],
            ), capability) for name in names]
        if capability == "transcription":
            return [
                with_capability(
                    LLMModelInfo(
                        id="scribe_v2",
                        name="Scribe v2",
                        description="Transcription multilingue avec diarisation.",
                        metadata_source="provider-catalog",
                    ),
                    capability,
                ),
                with_capability(
                    LLMModelInfo(
                        id="scribe_v2_realtime",
                        name="Scribe v2 Realtime",
                        description="Transcription temps réel à faible latence.",
                        metadata_source="provider-catalog",
                    ),
                    capability,
                ),
            ]

        base = connection.base_url.rstrip("/")
        voice_payloads: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            models_response = await client.get(
                f"{base}/models",
                headers=_headers(connection),
            )
            models_response.raise_for_status()

            next_page_token: str | None = None
            seen_page_tokens: set[str] = set()
            while True:
                params = {"page_size": "100", "include_total_count": "false"}
                if next_page_token:
                    params["next_page_token"] = next_page_token
                voices_response = await client.get(
                    f"{base.removesuffix('/v1')}/v2/voices",
                    headers=_headers(connection),
                    params=params,
                )
                voices_response.raise_for_status()
                voices_payload = as_dict(voices_response.json())
                voice_payloads.extend(
                    as_dict(raw) for raw in as_list(voices_payload.get("voices"))
                )
                raw_token = voices_payload.get("next_page_token")
                next_page_token = (
                    str(raw_token).strip() if raw_token is not None else None
                )
                if (
                    not voices_payload.get("has_more")
                    or not next_page_token
                    or next_page_token in seen_page_tokens
                ):
                    break
                seen_page_tokens.add(next_page_token)

        resources: list[LLMModelInfo] = []
        for raw in as_list(models_response.json()):
            model = as_dict(raw)
            if not model.get("can_do_text_to_speech"):
                continue
            rates = as_dict(model.get("model_rates"))
            resources.append(
                with_capability(
                    LLMModelInfo(
                        id=str(model.get("model_id") or ""),
                        name=str(model.get("name") or model.get("model_id") or ""),
                        description=model.get("description"),
                        pricing={
                            "unit": "character",
                            "character_multiplier": rates.get(
                                "character_cost_multiplier"
                            ),
                            "discount_multiplier": rates.get(
                                "cost_discount_multiplier"
                            ),
                        },
                        metadata_source="provider",
                    ),
                    capability,
                )
            )
        seen_voice_ids: set[str] = set()
        for voice in voice_payloads:
            voice_id = str(voice.get("voice_id") or "")
            if not voice_id or voice_id in seen_voice_ids:
                continue
            seen_voice_ids.add(voice_id)
            labels = as_dict(voice.get("labels"))
            label_summary = ", ".join(
                f"{key}: {value}"
                for key, value in labels.items()
                if isinstance(value, (str, int, float, bool))
            )
            description = " · ".join(
                value
                for value in (
                    str(voice.get("description") or "").strip(),
                    str(voice.get("category") or "").strip(),
                    label_summary,
                )
                if value
            )
            resources.append(
                with_capability(
                    LLMModelInfo(
                        id=f"voice:{voice_id}",
                        name=str(voice.get("name") or voice_id),
                        description=description or None,
                        resource_type="voice",
                        metadata_source="provider",
                    ),
                    capability,
                    resource_type="voice",
                )
            )
        return [resource for resource in resources if resource.id]
