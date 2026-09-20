"""Provider-neutral resource discovery facade.

OpenAI-compatible discovery is the canonical fallback. Any product-specific
endpoint, authentication rule, or catalog parser is registered by ``bridge.*``.
"""

from __future__ import annotations

from typing import Optional

from .capabilities import AICapability, applies_to_capability, with_capability
from .handlers import LLMModelInfo
from .handlers.openai_compatible import OpenAICompatibleHandler
from .provider_facade import (
    ProviderConnection,
    openai_protocol_base_url,
    resource_discovery_for,
)
from .provider_models import LLMProvider
from .subscription_policy import ensure_subscription_confirmation


def provider_connection(
    provider: LLMProvider,
    api_key: Optional[str],
) -> ProviderConnection:
    """Detach an ORM connection before crossing into a provider bridge."""

    return ProviderConnection(
        id=provider.id,
        name=provider.name,
        catalog_code=provider.catalog_code,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=api_key,
        configuration=dict(provider.configuration or {}),
    )


async def _openai_compatible_resources(
    connection: ProviderConnection,
    capability: AICapability,
) -> list[LLMModelInfo]:
    models = await OpenAICompatibleHandler().list_models(
        openai_protocol_base_url(connection),
        connection.api_key,
    )
    return [
        with_capability(model, capability)
        for model in models
        if applies_to_capability(model, capability)
    ]


async def list_resources(
    provider: LLMProvider,
    api_key: Optional[str],
    capability: AICapability,
) -> list[LLMModelInfo]:
    """Discover resources through a bridge or the canonical OpenAI protocol."""

    await ensure_subscription_confirmation(provider)
    connection = provider_connection(provider, api_key)
    service = resource_discovery_for(connection)
    if service is not None:
        return await service.list_resources(connection, capability)
    if provider.provider_type == "openai_compatible":
        return await _openai_compatible_resources(connection, capability)
    raise ValueError(
        f"No resource-discovery bridge is registered for {provider.name}"
    )


__all__ = ["list_resources", "provider_connection"]
