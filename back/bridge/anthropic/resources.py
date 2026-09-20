"""Anthropic-specific authentication for its model catalog."""

from app.llm.capabilities import AICapability, applies_to_capability, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.handlers.openai_compatible import OpenAICompatibleHandler
from app.llm.provider_facade import ProviderConnection


class AnthropicResourceDiscovery:
    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        headers: dict[str, str] = {}
        if connection.api_key:
            headers = {
                "x-api-key": connection.api_key,
                "anthropic-version": "2023-06-01",
            }
        models = await OpenAICompatibleHandler().list_models(
            connection.base_url,
            connection.api_key,
            headers,
        )
        return [
            with_capability(model, capability)
            for model in models
            if applies_to_capability(model, capability)
        ]
