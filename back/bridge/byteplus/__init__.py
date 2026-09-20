"""BytePlus LAS Seedance provider."""

from app.llm import register_media_provider
from app.llm.facade import ProviderProfile, register_provider, register_resource_discovery
from .media import BytePlusMedia, BytePlusResources

PROFILE = ProviderProfile(
    code="byteplus", display_name="BytePlus LAS", provider_type="byteplus",
    auth_type="api_key", base_url="https://operator.las.ap-southeast-1.bytepluses.com/api/v1",
    token_url="https://console.byteplus.com/las",
    documentation_url="https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced",
    icon="movie", color="blue", capabilities=("video_generation",),
)
register_provider(PROFILE)
register_media_provider(PROFILE.code, BytePlusMedia())
register_resource_discovery(PROFILE.code, BytePlusResources())
