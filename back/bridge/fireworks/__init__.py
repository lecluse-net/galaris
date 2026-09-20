"""Fireworks AI provider bridge registration."""

from pydantic_ai.providers.fireworks import FireworksProvider

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    register_provider,
    register_image_generation_provider,
    register_responses_policy,
)

from .image import FireworksImageGeneration
from app.llm.provider_facade import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS | {"prediction", "metadata"},
        responses=RESPONSES_PARAMETERS, efforts=("none", "low", "medium", "high", "max"),
    )

PROFILE = ProviderProfile(
    code="fireworks",
    display_name="Fireworks AI",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.fireworks.ai/inference/v1",
    token_url="https://app.fireworks.ai/settings/users/api-keys",
    documentation_url="https://docs.fireworks.ai/api-reference/introduction",
    icon="rocket_launch",
    color="orange",
    models_dev_id="fireworks-ai",
    supports_responses=True,
    capabilities=("chat", "vision", "image_generation", "embedding"),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_image_generation_provider(PROFILE.code, FireworksImageGeneration())
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=FireworksProvider.model_profile,
        store=False,
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
