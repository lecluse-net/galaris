"""Ollama-specific resource discovery and model management."""

from __future__ import annotations

import httpx
from loguru import logger

from app.llm.capabilities import AICapability, applies_to_capability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from core.i18n import render_prompt, tr
from core.util import as_dict, as_list


class OllamaServices:
    def base_url(self, connection: ProviderConnection) -> str:
        base_url = connection.base_url.rstrip("/")
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        url = f"{connection.base_url.rstrip('/')}/api/tags"
        headers = {"Content-Type": "application/json"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
        payload = as_dict(response.json())
        resources: list[LLMModelInfo] = []
        for raw in as_list(payload.get("models")):
            if not isinstance(raw, dict):
                continue
            item = as_dict(raw)
            model_id = str(item.get("name") or "")
            if not model_id:
                continue
            details = as_dict(item.get("details"))
            model = LLMModelInfo(
                id=model_id,
                name=model_id,
                description=str(details.get("description") or "") or None,
                metadata_source="provider",
            )
            if applies_to_capability(model, capability):
                resources.append(with_capability(model, capability))
        return resources

    async def pull_model(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        logger.info(
            "Ollama pull model: {} from {}",
            model_name,
            connection.base_url,
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{connection.base_url.rstrip('/')}/api/pull",
                json={"name": model_name, "stream": False},
                headers=headers,
                timeout=600.0,
            )
            response.raise_for_status()
        return render_prompt(
            await tr("llm_api.model_installed"),
            model_name=model_name,
        )

    async def delete_model(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        async with httpx.AsyncClient() as client:
            request = httpx.Request(
                "DELETE",
                f"{connection.base_url.rstrip('/')}/api/delete",
                json={"name": model_name},
                headers=headers,
            )
            response = await client.send(request)
            response.raise_for_status()
        return render_prompt(
            await tr("llm_api.model_deleted"),
            model_name=model_name,
        )
