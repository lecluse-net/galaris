"""Join public model aliases/prices with Mammouth's richer LiteLLM metadata."""

from __future__ import annotations

import asyncio
import math
from typing import Any
from urllib.parse import quote

import httpx

from app.llm import ProviderConnection
from app.llm.facade import AICapability, LLMModelInfo
from core.util import as_dict, as_list

from .protocol import MammouthProtocol

_MAX_CATALOG_BYTES = 8_000_000
_CAPABILITIES = {"chat", "vision", "embedding", "image_generation", "audio_understanding", "video_understanding"}


async def _get_json(client: httpx.AsyncClient, url: str, *, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > _MAX_CATALOG_BYTES:
                raise ValueError("Mammouth catalog exceeds the size limit.")
        import json

        payload: object = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("Invalid Mammouth catalog response.")
        return as_dict(payload)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data: object = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Mammouth catalog has no model list.")
    return [as_dict(row) for row in as_list(data)]


def _price(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value) * 1_000_000
    return None


def parse_catalog(models: dict[str, Any], details: dict[str, Any]) -> list[LLMModelInfo]:
    """Deployment hashes and underlying provider names are not callable public IDs."""
    metadata = {row.get("model_name"): as_dict(row.get("model_info")) for row in _rows(details)}
    result: list[LLMModelInfo] = []
    seen: set[str] = set()
    for row in _rows(models):
        name = row.get("id")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        info = metadata.get(name, {})
        public = as_dict(row.get("model_info"))
        mode = info.get("mode")
        lowered = name.lower().rsplit("/", 1)[-1]
        embedding = mode == "embedding" or lowered.startswith("text-embedding-")
        # Current public image entries omit mode/output flags; use their stable families.
        image = mode == "image_generation" or lowered.startswith("gpt-image-") or (
            lowered.startswith("gemini-") and "-image" in lowered
        )
        if mode not in {None, "chat", "completion", "embedding", "image_generation"}:
            continue  # A new upstream service needs an actual adapter before exposure.
        modalities = {"input_text": True, "output_text": not (embedding or image)}
        capabilities: list[str] = ["embedding" if embedding else "image_generation" if image else "chat"]
        if image:
            modalities["output_image"] = True
        if not embedding:
            modalities["input_image"] = info.get("supports_vision") is True
            modalities["input_file"] = info.get("supports_pdf_input") is True
            if not image:
                for flag, modality, capability in (
                    ("supports_vision", "input_image", "vision"),
                    ("supports_audio_input", "input_audio", "audio_understanding"),
                    ("supports_video_input", "input_video", "video_understanding"),
                ):
                    modalities[modality] = info.get(flag) is True
                    if modalities[modality]:
                        capabilities.append(capability)
        pricing: dict[str, Any] = {}
        for source, target in (
            ("input_cost_per_token", "input"),
            ("output_cost_per_token", "output"),
            ("cache_read_input_token_cost", "cached_input"),
            ("cache_creation_input_token_cost", "cache_write"),
        ):
            rate = _price(public.get(source))
            if rate is None:
                rate = _price(info.get(source))
            if rate is not None:
                pricing[target] = rate
        # Preserve non-token billing units without treating image prices as token prices.
        for key in ("input_cost_per_image", "output_cost_per_image"):
            value = info.get(key)
            if _price(value) is not None:
                pricing[key] = value
        context = public.get("max_input_tokens") or info.get("max_input_tokens")
        technical: dict[str, bool] = {}
        for source, target in (
            ("supports_function_calling", "tools"),
            ("supports_reasoning", "reasoning"),
            ("supports_response_schema", "structured_output"),
            ("supports_web_search", "web_search"),
            ("supports_prompt_caching", "prompt_caching"),
        ):
            value = info.get(source)
            if isinstance(value, bool):
                technical[target] = value
        result.append(LLMModelInfo(
            id=name, name=name, context_length=context if isinstance(context, int) and context > 0 else None,
            pricing=pricing, modalities=modalities, capabilities=technical,
            metadata_source="mammouth", service_capabilities=capabilities,
            resource_type="preset" if name == "mammouth-recommended" else "model",
        ))
    return result


class MammouthResources:
    async def catalog(self, connection: ProviderConnection, *, verify_key: bool = False) -> list[LLMModelInfo]:
        base = MammouthProtocol().base_url(connection)
        root = base.removesuffix("/v1")
        if verify_key and not connection.api_key:
            raise ValueError("A Mammouth API key is required.")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            models, details = await asyncio.gather(
                _get_json(client, f"{root}/public/models"),
                _get_json(client, f"{root}/public/model/info"),
            )
            result = parse_catalog(models, details)
            if verify_key:
                if not result:
                    raise ValueError("Mammouth returned an empty model catalog.")
                # The public catalog cannot validate credentials. This protected GET is free.
                await _get_json(client, f"{base}/models/{quote(result[0].id, safe='')}", api_key=connection.api_key)
        return result

    async def list_resources(self, connection: ProviderConnection, capability: AICapability) -> list[LLMModelInfo]:
        if capability not in _CAPABILITIES:
            return []
        return [model for model in await self.catalog(connection, verify_key=True)
                if capability in model.service_capabilities]

    async def get_model_metadata(self, connection: ProviderConnection, model_name: str) -> LLMModelInfo | None:
        return next((model for model in await self.catalog(connection) if model.id == model_name), None)
