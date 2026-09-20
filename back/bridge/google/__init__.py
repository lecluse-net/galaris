"""Google Gemini and Cloud Text-to-Speech bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    register_provider,
    register_image_generation_provider,
    register_image_size_resolver,
    register_resource_discovery,
    register_speech_provider,
)

from .resources import GoogleCloudTTSResourceDiscovery
from .speech import GeminiSpeech, GoogleCloudSpeech
from .image import GeminiImageGeneration, native_image_size
from .parameters import model_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy


GEMINI_PROFILE = ProviderProfile(
    code="gemini",
    display_name="Google Gemini",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    token_url="https://aistudio.google.com/app/apikey",
    documentation_url="https://ai.google.dev/gemini-api/docs/openai",
    icon="diamond",
    color="blue-7",
    models_dev_id="google",
    capabilities=("chat", "vision", "image_generation", "embedding", "speech"),
)
TTS_PROFILE = ProviderProfile(
    code="google-cloud-tts",
    display_name="Google Cloud Text-to-Speech",
    provider_type="google_cloud_tts",
    auth_type="optional_api_key",
    base_url="https://texttospeech.googleapis.com/v1",
    token_url="https://console.cloud.google.com/apis/credentials",
    documentation_url=(
        "https://cloud.google.com/text-to-speech/docs/reference/rest"
    ),
    icon="campaign",
    color="blue-8",
    capabilities=("speech",),
)

register_provider(GEMINI_PROFILE)
register_request_parameter_policy(GEMINI_PROFILE.code, model_parameter_policy)
register_image_generation_provider(GEMINI_PROFILE.code, GeminiImageGeneration())
register_image_size_resolver("google", native_image_size)
register_provider(TTS_PROFILE)
register_resource_discovery(
    TTS_PROFILE.code,
    GoogleCloudTTSResourceDiscovery(),
)
register_speech_provider(GEMINI_PROFILE.code, GeminiSpeech())
register_speech_provider(TTS_PROFILE.code, GoogleCloudSpeech())

__all__ = ["GEMINI_PROFILE", "TTS_PROFILE"]
