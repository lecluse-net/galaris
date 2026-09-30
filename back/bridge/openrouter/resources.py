"""OpenRouter-specific resource discovery endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.handlers.openai_compatible import OpenAICompatibleHandler
from app.llm.provider_facade import ProviderAuthenticationError, ProviderConnection
from core.i18n import tr
from core.util import as_dict, as_list


class OpenRouterResourceDiscovery:
    async def validate_connection(self, connection: ProviderConnection) -> None:
        if not connection.api_key:
            raise ProviderAuthenticationError(await tr("llm_api.connection.invalid_key"))
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{connection.base_url.rstrip('/')}/key",
                headers={"Authorization": f"Bearer {connection.api_key}"},
            )
            response.raise_for_status()
            data = as_dict(as_dict(response.json()).get("data"))
        if data.get("is_management_key") is not False:
            raise ProviderAuthenticationError(await tr("llm_api.connection.invalid_key"))

    async def _models_at(
        self,
        connection: ProviderConnection,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[LLMModelInfo]:
        headers = {"Content-Type": "application/json"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload: Any = response.json()
        models = OpenAICompatibleHandler().parse_models(payload)
        raw_by_id = {
            str(item.get("id")): item
            for raw in as_list(as_dict(payload).get("data"))
            if (item := as_dict(raw))
        }
        for model in models:
            top = as_dict(raw_by_id.get(model.id, {}).get("top_provider"))
            capacity = top.get("max_completion_tokens")
            if isinstance(capacity, int) and not isinstance(capacity, bool) and capacity > 0:
                model.max_output_tokens = capacity
            context = top.get("context_length")
            if isinstance(context, int) and not isinstance(context, bool) and context > 0:
                model.context_length = min(model.context_length or context, context)
        return models

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        base = connection.base_url.rstrip("/")
        if capability == "decision":
            models = await self._models_at(
                connection, f"{base}/models", params={"output_modalities": "decisions"},
            )
            models = [model for model in models if "decision" in model.service_capabilities]
        elif capability == "video_generation":
            models = await self._models_at(connection, f"{base}/videos/models")
        elif capability == "music_generation":
            models = await self._models_at(connection, f"{base}/models", params={"output_modalities": "audio"})
            models = [model for model in models if model.id in {"google/lyria-3-pro-preview", "google/lyria-3-clip-preview"}]
            for model in models:
                model.service_capabilities = ["music_generation"]
        elif capability in {"audio_understanding", "video_understanding"}:
            models = await self._models_at(connection, f"{base}/models", params={"output_modalities": "text"})
            flag = "input_audio" if capability == "audio_understanding" else "input_video"
            models = [model for model in models if (model.modalities or {}).get(flag)]
        elif capability == "embedding":
            models = await self._models_at(
                connection,
                f"{base}/embeddings/models",
            )
        elif capability == "image_generation":
            models = await self._models_at(
                connection,
                f"{base}/images/models",
            )
        else:
            output = {
                "chat": "text",
                "vision": "text",
                "transcription": "transcription",
                "speech": "speech",
            }[capability]
            models = await self._models_at(
                connection,
                f"{base}/models",
                params={"output_modalities": output},
            )
            if capability == "vision":
                models = [
                    model
                    for model in models
                    if (model.modalities or {}).get("input_image")
                ]
        return [with_capability(model, capability) for model in models]

    async def get_model_metadata(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> LLMModelInfo | None:
        models = await self._models_at(
            connection,
            f"{connection.base_url.rstrip('/')}/models",
            params={"output_modalities": "all"},
        )
        return next((model for model in models if model.id == model_name), None)
