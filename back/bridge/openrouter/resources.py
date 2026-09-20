"""OpenRouter-specific resource discovery endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.capabilities import AICapability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.handlers.openai_compatible import OpenAICompatibleHandler
from app.llm.provider_facade import ProviderConnection


class OpenRouterResourceDiscovery:
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
        return OpenAICompatibleHandler().parse_models(payload)

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        base = connection.base_url.rstrip("/")
        if capability == "video_generation":
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
