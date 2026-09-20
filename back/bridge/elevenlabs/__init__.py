"""ElevenLabs speech and transcription provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    register_provider,
    register_realtime_transcription_provider,
    register_resource_discovery,
    register_speech_provider,
    register_transcription_provider,
)

from .resources import ElevenLabsResourceDiscovery
from .speech import ElevenLabsSpeech
from .transcription import ElevenLabsTranscription
from .multimedia import ElevenLabsMedia
from app.llm import register_media_provider


PROFILE = ProviderProfile(
    code="elevenlabs",
    display_name="ElevenLabs",
    provider_type="elevenlabs",
    auth_type="api_key",
    base_url="https://api.elevenlabs.io/v1",
    token_url="https://elevenlabs.io/app/settings/api-keys",
    documentation_url="https://elevenlabs.io/docs/api-reference/introduction",
    icon="record_voice_over",
    color="deep-purple-7",
    capabilities=("speech", "transcription", "music_generation", "sound_generation"),
    supports_transcription=True,
)

register_provider(PROFILE)
register_media_provider(PROFILE.code, ElevenLabsMedia())
register_resource_discovery(PROFILE.code, ElevenLabsResourceDiscovery())
register_speech_provider(PROFILE.code, ElevenLabsSpeech())
TRANSCRIPTION = ElevenLabsTranscription()
register_transcription_provider(PROFILE.code, TRANSCRIPTION)
register_realtime_transcription_provider(PROFILE.code, TRANSCRIPTION)

__all__ = ["PROFILE"]
