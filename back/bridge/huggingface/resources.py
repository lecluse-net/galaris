"""Task catalogs and live routing for Hugging Face Inference Providers.

The OpenAI router lists chat models only. Native tasks use the Hub catalog and
only providers whose wire protocols this bridge implements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.llm.facade import (
    AICapability, LLMModelInfo, ProviderConnection, default_modalities, openai_compatible_resources,
)
from core.util import as_dict, as_list, read_response

HUB = "https://huggingface.co/api/models"
ROUTER = "https://router.huggingface.co"
TASKS: dict[AICapability, tuple[str, ...]] = {
    "embedding": ("feature-extraction", "sentence-similarity"),
    "transcription": ("automatic-speech-recognition",),
    "speech": ("text-to-speech",),
    "image_generation": ("text-to-image",),
}


def headers(connection: ProviderConnection) -> dict[str, str]:
    if not connection.api_key:
        raise ValueError("A Hugging Face inference token is required.")
    return {"Authorization": f"Bearer {connection.api_key}", "Accept-Encoding": "identity"}


def split_model(model: str) -> tuple[str, str | None]:
    name, separator, provider = model.partition(":")
    if (
        not name or len(name.split("/")) != 2
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/" for character in name)
        or (separator and provider not in {"hf-inference", "deepinfra"})
    ):
        raise ValueError("Invalid or unsupported Hugging Face inference model.")
    return name, provider if separator else None


@dataclass(frozen=True)
class Route:
    provider: str
    model: str

    def url(self, task: str) -> str:
        if self.provider == "hf-inference":
            suffix = "/pipeline/feature-extraction" if task == "feature-extraction" else ""
            return f"{ROUTER}/hf-inference/models/{quote(self.model, safe='/')}{suffix}"
        path = {
            "feature-extraction": "embeddings",
            "automatic-speech-recognition": "audio/transcriptions",
            "text-to-speech": "audio/speech",
        }[task]
        return f"{ROUTER}/deepinfra/v1/openai/{path}"


def routes(row: dict[str, Any], capability: AICapability) -> list[Route]:
    raw = row.get("inferenceProviderMapping")
    mappings = (
        [{**as_dict(value), "provider": provider} for provider, value in as_dict(raw).items()]
        if isinstance(raw, dict) else [as_dict(value) for value in as_list(raw)]
    )
    result: list[Route] = []
    for provider in ("hf-inference", "deepinfra"):
        if capability == "image_generation" and provider != "hf-inference":
            continue
        if capability == "speech" and provider != "deepinfra":
            continue  # The speech facade requires MP3; native HF models return varying formats.
        for mapping in mappings:
            task = mapping.get("task")
            if mapping.get("provider") != provider or mapping.get("status") != "live":
                continue
            if task not in TASKS.get(capability, ()):
                continue
            if capability == "embedding" and task == "sentence-similarity" and (
                provider != "hf-inference" or "feature-extraction" not in as_list(row.get("tags"))
            ):
                continue
            model = mapping.get("providerId")
            if isinstance(model, str) and model:
                # hf-inference uses the Hub ID, not an external URL or arbitrary path.
                if provider == "hf-inference":
                    model, _ = split_model(str(row.get("id") or ""))
                result.append(Route(provider, model))
    return result


async def get_json(
    client: httpx.AsyncClient, url: str, connection: ProviderConnection,
    *, params: list[tuple[str, str]] | None = None,
) -> tuple[Any, str | None]:
    async with client.stream("GET", url, headers=headers(connection), params=tuple(params) if params else None) as response:
        response.raise_for_status()
        data: Any = json.loads(await read_response(response, max_bytes=4_000_000))
        next_url = response.links.get("next", {}).get("url")
    if next_url:
        parsed = urlsplit(next_url)
        if parsed.scheme != "https" or parsed.netloc != "huggingface.co" or parsed.path != "/api/models":
            raise ValueError("Hugging Face returned an invalid catalog continuation.")
    return data, next_url


async def resolve_route(
    connection: ProviderConnection, model: str, capability: AICapability, *, timeout: float = 30.0,
) -> Route:
    name, selected_provider = split_model(model)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        data, _ = await get_json(client, f"{HUB}/{quote(name, safe='/')}", connection, params=[
            ("expand", "inferenceProviderMapping"), ("expand", "tags"),
        ])
    row = {**as_dict(data), "id": name}
    available = routes(row, capability)
    route = next((item for item in available if selected_provider in {None, item.provider}), None)
    if route is None:
        raise ValueError("The selected Hugging Face model has no supported live inference provider for this task.")
    return route


class HuggingFaceResources:
    async def list_resources(self, connection: ProviderConnection, capability: AICapability) -> list[LLMModelInfo]:
        if capability in {"chat", "vision"}:
            return await openai_compatible_resources(connection, capability)
        if capability not in TASKS:
            return []
        result: dict[str, LLMModelInfo] = {}
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            for task in TASKS[capability]:
                url: str | None = HUB
                params: list[tuple[str, str]] | None = [
                    ("inference_provider", "hf-inference" if capability == "image_generation" else "deepinfra" if capability == "speech" else "hf-inference,deepinfra"),
                    ("pipeline_tag", task), ("limit", "100"),
                    ("expand", "inferenceProviderMapping"), ("expand", "tags"),
                ]
                visited: set[str] = set()
                while url:
                    if url in visited or len(visited) >= 100:
                        raise ValueError("Hugging Face catalog pagination did not terminate.")
                    visited.add(url)
                    data, url = await get_json(client, url, connection, params=params)
                    params = None
                    if not isinstance(data, list):
                        raise ValueError("Hugging Face returned an invalid task catalog.")
                    for raw in as_list(data):
                        row = as_dict(raw)
                        name = row.get("id")
                        if not isinstance(name, str) or not routes(row, capability):
                            continue
                        split_model(name)
                        result[name] = LLMModelInfo(
                            id=name, name=name, metadata_source="huggingface", status="live",
                            service_capabilities=[capability], modalities=default_modalities(capability),
                        )
        return list(result.values())
