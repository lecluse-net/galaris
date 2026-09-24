"""OpenRouter provider bridge registration."""

from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.llm import register_media_provider
from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy,
    register_request_parameter_policy,
    ProviderMediaInputPolicy,
    register_media_input_policy,
    ProviderResponsesPolicy,
    register_model_metadata,
    register_provider,
    register_image_generation_provider,
    register_resource_discovery,
    register_responses_policy,
    register_transcription_provider,
    register_usage_accounting,
)

from .resources import OpenRouterResourceDiscovery
from .transcription import OpenRouterTranscription
from .usage import OpenRouterUsageAccounting
from .image import OpenRouterImageGeneration
from .multimedia import OpenRouterMedia
from .decisions import OpenRouterDecisions
from app.llm.facade import register_decision_provider


def _request_parameters(model: str) -> RequestParameterPolicy:
    # OpenRouter translates this unified vocabulary for the selected upstream.
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS,
        responses=RESPONSES_PARAMETERS | {"store"},
        chat_token_limit="max_tokens", thinking_toggle=False, chat_reasoning_object=True,
        efforts=("none", "low", "medium", "high", "xhigh", "max"),
        reasoning_fields=frozenset({"effort", "enabled", "exclude", "max_tokens"}),
        chat_supports_tools=True,
    )

PROFILE = ProviderProfile(
    code="openrouter",
    display_name="OpenRouter",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://openrouter.ai/api/v1",
    token_url="https://openrouter.ai/settings/keys",
    documentation_url="https://openrouter.ai/docs/quickstart",
    icon="hub",
    color="indigo",
    models_dev_id="openrouter",
    supports_transcription=True,
    supports_responses=True,
    capabilities=(
        "decision",
        "chat",
        "vision",
        "image_generation",
        "embedding",
        "transcription",
        "speech",
        "audio_understanding",
        "video_understanding",
        "video_generation",
        "music_generation",
    ),
)

register_provider(PROFILE)
register_decision_provider(PROFILE.code, OpenRouterDecisions())
register_media_input_policy(PROFILE.code, ProviderMediaInputPolicy(
    audio_types=frozenset({"audio/wav", "audio/mpeg", "audio/aiff", "audio/aac",
                           "audio/ogg", "audio/flac", "audio/mp4"}),
    video_types=frozenset({"video/mp4", "video/mpeg", "video/quicktime", "video/webm"}),
))
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_media_provider(PROFILE.code, OpenRouterMedia())
register_image_generation_provider(PROFILE.code, OpenRouterImageGeneration())
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=OpenRouterProvider.model_profile,
        store=False,
        send_reasoning_ids=False,
    ),
)
RESOURCE_DISCOVERY = OpenRouterResourceDiscovery()
register_resource_discovery(PROFILE.code, RESOURCE_DISCOVERY)
register_model_metadata(PROFILE.code, RESOURCE_DISCOVERY)
register_transcription_provider(PROFILE.code, OpenRouterTranscription())
register_usage_accounting(PROFILE.code, OpenRouterUsageAccounting())

__all__ = ["PROFILE"]
