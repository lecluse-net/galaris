"""Groq provider bridge registration."""

from pydantic_ai.providers.groq import GroqProvider
from .parameters import model_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    register_provider,
    register_responses_policy,
)


PROFILE = ProviderProfile(
    code="groq",
    display_name="Groq",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.groq.com/openai/v1",
    token_url="https://console.groq.com/keys",
    documentation_url="https://console.groq.com/docs/quickstart",
    icon="bolt",
    color="red",
    models_dev_id="groq",
    supports_transcription=True,
    supports_responses=True,
    capabilities=("chat", "vision", "transcription"),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, model_parameter_policy)
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=GroqProvider.model_profile,
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
