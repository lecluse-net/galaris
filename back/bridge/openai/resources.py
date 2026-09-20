"""OpenAI model discovery enriched with built-in Realtime voices."""

from __future__ import annotations

from app.llm.capabilities import (
    AICapability,
    applies_to_capability,
    with_capability,
)
from app.llm.handlers import LLMModelInfo
from app.llm.handlers.openai_compatible import OpenAICompatibleHandler
from app.llm.provider_facade import ProviderConnection


_REALTIME_VOICES: tuple[tuple[str, str], ...] = (
    ("alloy", "Alloy"),
    ("ash", "Ash"),
    ("ballad", "Ballad"),
    ("coral", "Coral"),
    ("echo", "Echo"),
    ("sage", "Sage"),
    ("shimmer", "Shimmer"),
    ("verse", "Verse"),
    ("marin", "Marin"),
    ("cedar", "Cedar"),
)


class OpenAIResourceDiscovery:
    """Expose ordinary API models and stable Realtime voice resources."""

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        models = await OpenAICompatibleHandler().list_models(
            connection.base_url,
            connection.api_key,
        )
        resources = [
            with_capability(model, capability)
            for model in models
            if applies_to_capability(model, capability)
        ]
        if capability != "speech":
            return resources

        resources.extend(
            with_capability(
                LLMModelInfo(
                    id=f"voice:{voice}",
                    name=label,
                    description=(
                        "Voix native OpenAI Realtime."
                        + (
                            " Recommandée par OpenAI pour la meilleure qualité."
                            if voice in {"marin", "cedar"}
                            else ""
                        )
                    ),
                    resource_type="voice",
                    metadata_source="provider-catalog",
                ),
                "speech",
                resource_type="voice",
            )
            for voice, label in _REALTIME_VOICES
        )
        return resources


__all__ = ["OpenAIResourceDiscovery"]
