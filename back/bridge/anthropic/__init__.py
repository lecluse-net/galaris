"""Anthropic provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import register_provider, register_resource_discovery

from .resources import AnthropicResourceDiscovery
from .parameters import model_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy


PROFILE = ProviderProfile(
    code="anthropic-api",
    display_name="Anthropic API",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.anthropic.com/v1",
    token_url="https://console.anthropic.com/settings/keys",
    documentation_url=(
        "https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk"
    ),
    icon="psychology",
    color="deep-orange",
    models_dev_id="anthropic",
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, model_parameter_policy)
register_resource_discovery(PROFILE.code, AnthropicResourceDiscovery())

__all__ = ["PROFILE"]
