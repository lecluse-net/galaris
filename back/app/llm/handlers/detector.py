"""Canonical OpenAI-compatible handler selection."""
from .base import BaseLLMHandler
from .openai_compatible import OpenAICompatibleHandler


def get_handler(provider_type: str, base_url: str = "") -> BaseLLMHandler:
    """
    Select a provider handler from the persisted transport.

    Provider-specific discovery is selected through the bridge registry before
    this generic protocol fallback is reached.

    Args:
        provider_type: Persisted provider transport.
        base_url: Legacy API base URL fallback.

    Returns:
        Selected handler instance.
    """
    del provider_type, base_url
    return OpenAICompatibleHandler()


def get_handler_for_url(base_url: str) -> BaseLLMHandler:
    """Backward-compatible URL-only selection used by legacy callers."""
    return get_handler("openai_compatible", base_url)
