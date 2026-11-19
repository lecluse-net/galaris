"""OpenAI-compatible profile backed by the synthetic checkout target."""

from app.llm.provider_facade import ProviderProfile
from app.plugin.contracts import PluginRuntimeContext


def plugin_provider(_context: PluginRuntimeContext) -> ProviderProfile:
    return ProviderProfile(
        code="sample.provider", display_name="Sample AI Provider", provider_type="openai_compatible",
        auth_type="api_key", base_url="http://127.0.0.1:8000/api/plugin-samples/provider/v1",
        token_url=None, documentation_url="", icon="smart_toy", color="solaire-blue",
    )
