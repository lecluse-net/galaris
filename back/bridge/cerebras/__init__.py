"""Cerebras provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import register_provider
from app.llm.provider_facade import CHAT_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy
from pydantic_ai.providers.cerebras import CerebrasProvider


def _request_parameters(model: str) -> RequestParameterPolicy:
    profile = CerebrasProvider.model_profile(model) or {}
    efforts = ("low", "medium", "high") if profile.get("thinking_always_enabled", False) else (
        ("none",) if profile.get("supports_thinking", False) else ()
    )
    return RequestParameterPolicy(chat=CHAT_PARAMETERS - {"logit_bias", "user"}, efforts=efforts)


PROFILE = ProviderProfile(
    code="cerebras",
    display_name="Cerebras",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.cerebras.ai/v1",
    token_url="https://cloud.cerebras.ai/platform/",
    documentation_url="https://inference-docs.cerebras.ai/quickstart",
    icon="memory",
    color="cyan-9",
    models_dev_id="cerebras",
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)

__all__ = ["PROFILE"]
