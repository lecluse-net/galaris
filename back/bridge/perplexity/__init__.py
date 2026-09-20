"""Perplexity provider bridge registration."""

from dataclasses import replace

from pydantic_ai.profiles import ModelProfile
from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy,
    register_request_parameter_policy, compatible_parameter_policy,
    ProviderConnection, ProviderResponsesPolicy, register_openai_protocol_adapter,
    register_provider, register_responses_policy,
)


def _request_parameters(model: str) -> RequestParameterPolicy:
    policy = compatible_parameter_policy()
    return replace(
        policy, chat=CHAT_PARAMETERS - {"parallel_tool_calls", "seed", "user", "logit_bias", "logprobs", "top_logprobs"},
        responses=policy.responses & RESPONSES_PARAMETERS,
        reasoning_fields=frozenset({"effort"}), thinking_toggle=False, chat_efforts=(),
    )

class _PerplexityProtocol:
    """Normalize legacy catalog connections to the Agent API base path."""

    def base_url(self, connection: ProviderConnection) -> str:
        base_url = connection.base_url.rstrip("/")
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


def _responses_model_profile(model_name: str) -> ModelProfile:
    return ModelProfile(supports_inline_system_prompts=True)


PROFILE = ProviderProfile(
    code="perplexity",
    display_name="Perplexity",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.perplexity.ai/v1",
    token_url="https://www.perplexity.ai/settings/api",
    documentation_url="https://docs.perplexity.ai/getting-started/quickstart",
    icon="manage_search",
    color="cyan-8",
    models_dev_id="perplexity",
    supports_responses=True,
    aliases=("https://api.perplexity.ai",),
)

register_provider(PROFILE)
register_request_parameter_policy(PROFILE.code, _request_parameters)
register_openai_protocol_adapter(PROFILE.code, _PerplexityProtocol())
register_responses_policy(
    PROFILE.code,
    ProviderResponsesPolicy(
        model_profile=_responses_model_profile,
        chat_fallback_statuses=frozenset({400, 404, 422}),
        send_reasoning_ids=False,
    ),
)

__all__ = ["PROFILE"]
