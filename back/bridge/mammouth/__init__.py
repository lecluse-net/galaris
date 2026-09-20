"""Mammouth AI public API provider; app-only services are deliberately excluded."""

from app.llm import register_media_provider
from app.llm.facade import (
    ProviderProfile,
    ProviderResponsesPolicy,
    register_image_generation_provider,
    register_model_metadata,
    register_openai_protocol_adapter,
    register_provider,
    register_resource_discovery,
    register_responses_policy,
)

from .image import MammouthImageGeneration
from .multimedia import MammouthMedia
from .protocol import MammouthProtocol, model_profile
from .resources import MammouthResources
from dataclasses import replace
from app.llm import (
    RequestParameterPolicy, register_request_parameter_policy, compatible_parameter_policy,
)


def _request_parameters(model: str) -> RequestParameterPolicy:
    policy = compatible_parameter_policy()
    return replace(policy, responses=policy.responses | {"store"}, chat_token_limit="max_tokens", thinking_toggle=False, chat_supports_tools=True)

PROFILE = ProviderProfile(
    code="mammouth", display_name="Mammouth AI", provider_type="openai_compatible",
    auth_type="api_key", base_url="https://api.mammouth.ai/v1",
    token_url="https://mammouth.ai/app/account/settings/api",
    documentation_url="https://info.mammouth.ai/docs/api-quick-start/",
    icon="hub", color="purple", aliases=("https://api.mammouth.ai",),
    supports_responses=True,
    capabilities=("chat", "vision", "embedding", "image_generation", "audio_understanding", "video_understanding"),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_openai_protocol_adapter(PROFILE.code, MammouthProtocol())
register_responses_policy(PROFILE.code, ProviderResponsesPolicy(
    model_profile=model_profile, supports_compaction=True, store=False, send_reasoning_ids=False,
))
RESOURCE_DISCOVERY = MammouthResources()
register_resource_discovery(PROFILE.code, RESOURCE_DISCOVERY)
register_model_metadata(PROFILE.code, RESOURCE_DISCOVERY)
register_image_generation_provider(PROFILE.code, MammouthImageGeneration())
register_media_provider(PROFILE.code, MammouthMedia())

__all__ = ["PROFILE"]
