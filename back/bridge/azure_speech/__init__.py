"""Azure AI Speech provider bridge registration."""

from app.llm.provider_catalog import ProviderConfigurationField, ProviderProfile
from app.llm.provider_facade import (
    register_provider,
    register_resource_discovery,
    register_speech_provider,
)

from .resources import AzureSpeechResourceDiscovery
from .speech import AzureSpeech


PROFILE = ProviderProfile(
    code="azure-speech",
    display_name="Azure AI Speech",
    provider_type="azure_speech",
    auth_type="optional_api_key",
    base_url="https://{region}.tts.speech.microsoft.com/cognitiveservices",
    token_url="https://portal.azure.com/",
    documentation_url=(
        "https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech"
    ),
    icon="spatial_audio_off",
    color="light-blue-9",
    capabilities=("speech",),
    configuration_fields=(
        ProviderConfigurationField(
            key="region",
            label="Région Azure",
            required=False,
            placeholder="Ex : francecentral, westeurope",
        ),
    ),
)

register_provider(PROFILE)
register_resource_discovery(PROFILE.code, AzureSpeechResourceDiscovery())
register_speech_provider(PROFILE.code, AzureSpeech())

__all__ = ["PROFILE"]
