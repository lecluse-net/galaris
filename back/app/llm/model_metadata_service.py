"""Provider-neutral facade for optional third-party model metadata."""

from __future__ import annotations

from typing import Optional

from .handlers import LLMModelInfo
from .provider_facade import model_catalog_metadata
from .provider_models import LLMProvider
from .resource_discovery import provider_connection


def clear_cache() -> None:
    service = model_catalog_metadata()
    if service is not None:
        service.clear_cache()


async def enrich_models(
    provider: LLMProvider,
    models: list[LLMModelInfo],
    *,
    force_refresh: bool = False,
) -> list[LLMModelInfo]:
    service = model_catalog_metadata()
    if service is None:
        return models
    return await service.enrich_models(
        provider_connection(provider, None),
        models,
        force_refresh=force_refresh,
    )


async def get_model_metadata(
    provider: LLMProvider,
    model_id: str,
) -> Optional[LLMModelInfo]:
    service = model_catalog_metadata()
    if service is None:
        return None
    return await service.get_model_metadata(
        provider_connection(provider, None),
        model_id,
    )


__all__ = ["clear_cache", "enrich_models", "get_model_metadata"]
