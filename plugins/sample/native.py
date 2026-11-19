"""Registration example for application images that ship their provider."""

from app.llm.provider_facade import ProviderProfile, register_provider


def provider_sample(base_url: str) -> ProviderProfile:
    """Use a normal connection for the URL's credentials."""
    return ProviderProfile(
        code="sample-llm",
        display_name="Sample LLM",
        provider_type="openai_compatible",
        auth_type="api_key",
        base_url=base_url,
        token_url=None,
        documentation_url="",
        icon="smart_toy",
        color="solaire-blue",
    )


def register_provider_sample(base_url: str) -> None:
    register_provider(provider_sample(base_url))
