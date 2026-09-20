"""Cohere provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from pydantic_ai.profiles.cohere import cohere_model_profile
from app.llm.provider_facade import register_provider
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy,
    register_request_parameter_policy,
)


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"parallel_tool_calls", "stream_options", "user", "logit_bias", "logprobs", "top_logprobs"},
        responses=RESPONSES_PARAMETERS,
        efforts=("none", "high") if (cohere_model_profile(model) or {}).get("supports_thinking", False) else (),
    )


PROFILE = ProviderProfile(
    code="cohere",
    display_name="Cohere",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.cohere.com/compatibility/v1",
    token_url="https://dashboard.cohere.com/api-keys",
    documentation_url="https://docs.cohere.com/docs/compatibility-api",
    icon="language",
    color="green-7",
    models_dev_id="cohere",
    capabilities=("chat", "embedding"),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)

__all__ = ["PROFILE"]
