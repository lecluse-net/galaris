"""Hugging Face provider bridge registration."""

from dataclasses import replace

from pydantic_ai.profiles import ModelProfile
from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy,
    register_request_parameter_policy, compatible_parameter_policy,
    ProviderResponsesPolicy, register_provider, register_responses_policy,
    register_embedding_provider, register_resource_discovery,
    register_transcription_provider, register_speech_provider, register_image_generation_provider,
)
from .resources import HuggingFaceResources
from .inference import (
    HuggingFaceEmbeddings, HuggingFaceTranscription, HuggingFaceSpeech, HuggingFaceImageGeneration,
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
    supports_transcription=True,
    capabilities=("chat", "vision", "embedding", "transcription", "speech", "image_generation"),
)

register_provider(PROFILE)
register_resource_discovery(PROFILE.code, HuggingFaceResources())
register_embedding_provider(PROFILE.code, HuggingFaceEmbeddings())
register_transcription_provider(PROFILE.code, HuggingFaceTranscription())
register_speech_provider(PROFILE.code, HuggingFaceSpeech())
register_image_generation_provider(PROFILE.code, HuggingFaceImageGeneration())
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=_responses_model_profile,
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
