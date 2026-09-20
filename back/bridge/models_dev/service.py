"""Enrich provider model catalogs with normalized public metadata.

Provider ``/models`` endpoints are authoritative for availability but often
omit context windows, modalities, and prices. models.dev supplies those missing
details. Network failure is deliberately non-fatal: callers keep the live
provider catalog unchanged.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx
from loguru import logger

from core.util import as_dict, as_list
from app.llm.handlers import LLMModelInfo
from app.llm.provider_catalog import resolve_provider_profile
from app.llm.provider_facade import ProviderConnection


MODELS_DEV_URL = "https://models.dev/api.json"
_CACHE_TTL_SECONDS = 60 * 60
_cache: dict[str, Any] = {}
_cache_loaded_at = 0.0


def clear_cache() -> None:
    """Clear in-memory metadata, primarily for deterministic tests."""
    global _cache, _cache_loaded_at
    _cache = {}
    _cache_loaded_at = 0.0


async def _registry(*, force_refresh: bool = False) -> dict[str, Any]:
    global _cache, _cache_loaded_at
    now = time.monotonic()
    if _cache and not force_refresh and now - _cache_loaded_at < _CACHE_TTL_SECONDS:
        return _cache

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(MODELS_DEV_URL)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            _cache = as_dict(payload)
            _cache_loaded_at = now
    except Exception as exc:
        logger.debug("Unable to refresh models.dev metadata: {}", exc)
    return _cache


def _provider_metadata_id(provider: ProviderConnection) -> Optional[str]:
    profile = resolve_provider_profile(
        catalog_code=provider.catalog_code,
        base_url=provider.base_url,
    )
    return profile.models_dev_id if profile else None


def _models_for_provider(
    registry: dict[str, Any],
    provider: ProviderConnection,
) -> dict[str, Any]:
    metadata_id = _provider_metadata_id(provider)
    if not metadata_id:
        return {}
    provider_data = as_dict(registry.get(metadata_id))
    return as_dict(provider_data.get("models"))


def _model_candidates(model_id: str) -> tuple[str, ...]:
    """Return common provider-specific and canonical forms for one model ID."""
    candidates = [model_id]
    marker = "/models/"
    if marker in model_id:
        candidates.append(model_id.rsplit(marker, 1)[-1])
    if "/" in model_id:
        candidates.append(model_id.rsplit("/", 1)[-1])
    # Preserve order while removing duplicates.
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _raw_model(models: dict[str, Any], model_id: str) -> Optional[dict[str, Any]]:
    for candidate in _model_candidates(model_id):
        exact = models.get(candidate)
        if isinstance(exact, dict):
            return as_dict(exact)

    lowered = {str(key).lower(): value for key, value in models.items()}
    for candidate in _model_candidates(model_id):
        value = lowered.get(candidate.lower())
        if isinstance(value, dict):
            return as_dict(value)
    return None


def _price(raw_cost: dict[str, Any], key: str) -> Optional[float]:
    if key not in raw_cost or raw_cost.get(key) is None:
        return None
    try:
        return float(raw_cost[key])
    except (TypeError, ValueError):
        return None


def _pricing(raw: dict[str, Any]) -> Optional[dict[str, float]]:
    cost = as_dict(raw.get("cost"))
    mapping = {
        "input": _price(cost, "input"),
        "cached_input": _price(cost, "cache_read"),
        "cache_write": _price(cost, "cache_write"),
        "output": _price(cost, "output"),
    }
    return {key: value for key, value in mapping.items() if value is not None} or None


def _modalities(raw: dict[str, Any]) -> Optional[dict[str, bool]]:
    modalities = as_dict(raw.get("modalities"))
    input_values = {str(value).lower() for value in as_list(modalities.get("input"))}
    output_values = {str(value).lower() for value in as_list(modalities.get("output"))}
    if not input_values and not output_values and raw.get("attachment") is None:
        return None

    if raw.get("attachment") and not ({"image", "pdf", "file"} & input_values):
        input_values.add("image")

    def supports(values: set[str], name: str) -> bool:
        if name == "file":
            return bool({"file", "pdf"} & values)
        return name in values

    names = ("text", "image", "file", "video", "audio")
    flags: dict[str, bool] = {}
    for name in names:
        flags[f"input_{name}"] = supports(input_values, name)
        flags[f"output_{name}"] = supports(output_values, name)
    return flags


def _capabilities(raw: dict[str, Any]) -> dict[str, bool]:
    return {
        "reasoning": bool(raw.get("reasoning")),
        "tools": bool(raw.get("tool_call")),
        "attachments": bool(raw.get("attachment")),
        "temperature": bool(raw.get("temperature")),
        "structured_output": bool(raw.get("structured_output")),
        "open_weights": bool(raw.get("open_weights")),
    }


def _context_length(raw: dict[str, Any]) -> Optional[int]:
    value = as_dict(raw.get("limit")).get("context")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _metadata_model(model_id: str, raw: dict[str, Any]) -> LLMModelInfo:
    return LLMModelInfo(
        id=model_id,
        name=str(raw.get("name") or model_id),
        context_length=_context_length(raw),
        pricing=_pricing(raw),
        modalities=_modalities(raw),
        capabilities=_capabilities(raw),
        release_date=str(raw.get("release_date") or "") or None,
        status=str(raw.get("status") or "") or None,
        metadata_source="models.dev",
    )


def _merge_model(live: LLMModelInfo, metadata: LLMModelInfo) -> LLMModelInfo:
    live_pricing = dict(live.pricing or {})
    for key, value in (metadata.pricing or {}).items():
        live_pricing.setdefault(key, value)

    live_modalities = dict(live.modalities or {})
    for key, value in (metadata.modalities or {}).items():
        live_modalities.setdefault(key, value)

    live_capabilities = dict(live.capabilities or {})
    for key, value in (metadata.capabilities or {}).items():
        live_capabilities.setdefault(key, value)

    return LLMModelInfo(
        id=live.id,
        name=live.name or metadata.name,
        description=live.description or metadata.description,
        context_length=live.context_length or metadata.context_length,
        pricing=live_pricing or None,
        modalities=live_modalities or None,
        capabilities=live_capabilities or None,
        release_date=live.release_date or metadata.release_date,
        status=live.status or metadata.status,
        metadata_source=(
            "provider+models.dev"
            if live.metadata_source and live.metadata_source != "models.dev"
            else metadata.metadata_source
        ),
        resource_type=live.resource_type,
        service_capabilities=(
            live.service_capabilities or metadata.service_capabilities
        ),
    )


async def enrich_models(
    provider: ProviderConnection,
    models: list[LLMModelInfo],
    *,
    force_refresh: bool = False,
) -> list[LLMModelInfo]:
    """Fill missing model details while preserving live-provider values."""
    registry = await _registry(force_refresh=force_refresh)
    provider_models = _models_for_provider(registry, provider)
    if not provider_models:
        return models

    enriched: list[LLMModelInfo] = []
    for model in models:
        raw = _raw_model(provider_models, model.id)
        enriched.append(
            _merge_model(model, _metadata_model(model.id, raw)) if raw else model
        )
    return enriched


async def get_model_metadata(
    provider: ProviderConnection,
    model_id: str,
) -> Optional[LLMModelInfo]:
    """Return normalized metadata for one configured model when available."""
    registry = await _registry()
    raw = _raw_model(_models_for_provider(registry, provider), model_id)
    return _metadata_model(model_id, raw) if raw else None


class ModelsDevMetadata:
    """Object adapter registered against the app.llm metadata contract."""

    async def enrich_models(
        self,
        connection: ProviderConnection,
        models: list[LLMModelInfo],
        *,
        force_refresh: bool = False,
    ) -> list[LLMModelInfo]:
        return await enrich_models(
            connection,
            models,
            force_refresh=force_refresh,
        )

    async def get_model_metadata(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> Optional[LLMModelInfo]:
        return await get_model_metadata(connection, model_name)

    def clear_cache(self) -> None:
        clear_cache()
