"""Mammouth's OpenAI-compatible gateway and stateless Responses policy."""

from pydantic_ai.profiles import ModelProfile

from app.llm import ProviderConnection


class MammouthProtocol:
    def base_url(self, connection: ProviderConnection) -> str:
        base = connection.base_url.rstrip("/")
        return base if base.endswith("/v1") else f"{base}/v1"


def model_profile(model: str) -> ModelProfile:
    return ModelProfile(supports_inline_system_prompts=True)
