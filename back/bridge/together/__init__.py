"""Together AI provider bridge registration."""

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import register_provider
from app.llm.provider_facade import CHAT_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"user"}, efforts=("none", "low", "medium", "high", "max"),
    )


PROFILE = ProviderProfile(
    code="together",
    display_name="Together AI",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.together.xyz/v1",
    token_url="https://api.together.ai/settings/api-keys",
    documentation_url="https://docs.together.ai/docs/quickstart",
    icon="groups",
    color="purple",
    models_dev_id="togetherai",
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)

__all__ = ["PROFILE"]
