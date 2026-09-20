"""Mistral AI provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import register_provider
from app.llm.provider_facade import CHAT_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"user", "logit_bias", "logprobs", "top_logprobs", "stream_options", "seed"},
        efforts=("none", "high"),
    )


PROFILE = ProviderProfile(
    code="mistral",
    display_name="Mistral AI",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.mistral.ai/v1",
    token_url="https://console.mistral.ai/api-keys",
    documentation_url="https://docs.mistral.ai/getting-started/quickstart/",
    icon="air",
    color="amber-9",
    models_dev_id="mistral",
    capabilities=("chat", "vision", "embedding"),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)

__all__ = ["PROFILE"]
