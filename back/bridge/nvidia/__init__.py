"""NVIDIA NIM provider bridge registration."""

from pydantic_ai.profiles import ModelProfile
from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy,
    ProviderResponsesPolicy, register_provider, register_responses_policy,
)


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"user"}, responses=RESPONSES_PARAMETERS - {"metadata", "user", "store"},
        efforts=("none", "low", "medium", "high", "xhigh", "max"),
    )

def _responses_model_profile(model_name: str) -> ModelProfile:
    return ModelProfile(supports_inline_system_prompts=True)


PROFILE = ProviderProfile(
    code="nvidia",
    display_name="NVIDIA NIM",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://integrate.api.nvidia.com/v1",
    token_url="https://build.nvidia.com/",
    documentation_url="https://docs.api.nvidia.com/nim/reference/llm-apis",
    icon="developer_board",
    color="light-green-9",
    models_dev_id="nvidia",
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
