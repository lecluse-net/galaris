"""DeepSeek provider bridge registration."""

from pydantic_ai.providers.deepseek import DeepSeekProvider
from .parameters import model_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    register_provider,
    register_responses_policy,
)


PROFILE = ProviderProfile(
    code="deepseek",
    display_name="DeepSeek",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.deepseek.com/v1",
    token_url="https://platform.deepseek.com/api_keys",
    documentation_url="https://api-docs.deepseek.com/",
    icon="travel_explore",
    color="blue",
    models_dev_id="deepseek",
    supports_responses=True,
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, model_parameter_policy)
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=DeepSeekProvider.model_profile,
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
