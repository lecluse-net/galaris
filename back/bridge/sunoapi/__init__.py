"""SunoAPI.org intermediary; deliberately distinct from official Suno Platform."""

from app.llm import register_media_provider
from app.llm.facade import ProviderProfile, register_provider, register_resource_discovery
from .media import SunoApiMedia, SunoApiResources

PROFILE = ProviderProfile(
    code="sunoapi", display_name="SunoAPI.org (third party)", provider_type="sunoapi",
    auth_type="api_key", base_url="https://api.sunoapi.org/api/v1",
    token_url="https://sunoapi.org/api-key", documentation_url="https://docs.sunoapi.org/",
    icon="music_note", color="orange", capabilities=("music_generation", "sound_generation"),
)
register_provider(PROFILE)
register_media_provider(PROFILE.code, SunoApiMedia())
register_resource_discovery(PROFILE.code, SunoApiResources())
