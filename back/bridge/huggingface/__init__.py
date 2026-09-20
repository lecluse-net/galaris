"""Hugging Face provider bridge registration."""

from dataclasses import replace

from pydantic_ai.profiles import ModelProfile
from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy,
    register_request_parameter_policy, compatible_parameter_policy,
    ProviderResponsesPolicy, register_provider, register_responses_policy,
)


def _request_parameters(model: str) -> RequestParameterPolicy:
    policy = compatible_parameter_policy()
    return replace(
        policy, chat=policy.chat & CHAT_PARAMETERS, responses=(policy.responses & RESPONSES_PARAMETERS) | {"store"},
        chat_token_limit="max_tokens", thinking_toggle=False,
    )

def _responses_model_profile(model_name: str) -> ModelProfile:
    # The OpenAI-compatible route does not require the native huggingface_hub SDK.
    return ModelProfile(supports_inline_system_prompts=True)


PROFILE = ProviderProfile(
    code="huggingface",
    display_name="Hugging Face",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://router.huggingface.co/v1",
    token_url="https://huggingface.co/settings/tokens",
    documentation_url="https://huggingface.co/docs/inference-providers/index",
    icon="sentiment_satisfied",
    color="amber",
    models_dev_id="huggingface",
    supports_responses=True,
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=_responses_model_profile,
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
