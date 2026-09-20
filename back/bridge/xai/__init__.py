"""xAI provider bridge registration."""

from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.grok import grok_model_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    register_provider,
    register_responses_policy,
    register_responses_transport,
)

from .responses import XAIResponsesTransport
from .parameters import model_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy


def _responses_model_profile(model_name: str) -> ModelProfile:
    """Add the REST Responses reasoning envelope to the native Grok profile."""

    return merge_profile(
        grok_model_profile(model_name),
        OpenAIModelProfile(
            openai_supports_encrypted_reasoning_content=True,
            # This OpenAI-specific flag also disables sampling in Pydantic AI.
            # Grok accepts temperature with reasoning; the gateway owns its controls.
        ),
    )


PROFILE = ProviderProfile(
    code="xai",
    display_name="xAI",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.x.ai/v1",
    token_url="https://console.x.ai/team/default/api-keys",
    documentation_url="https://docs.x.ai/docs/overview",
    icon="close",
    color="grey-9",
    models_dev_id="xai",
    supports_responses=True,
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, model_parameter_policy)
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=_responses_model_profile,
        supports_compaction=True,
        store=False,
        send_reasoning_ids=True,
    ),
)
register_responses_transport(PROFILE.code, XAIResponsesTransport())

__all__ = ["PROFILE"]
