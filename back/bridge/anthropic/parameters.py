"""SDK capabilities on Anthropic's OpenAI-compatible endpoint."""

from pydantic_ai.profiles.anthropic import anthropic_model_profile

from app.llm import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = anthropic_model_profile(model) or {}
    rejects_sampling = bool(profile.get("anthropic_disallows_sampling_settings"))
    unsupported = {"temperature", "top_p"} if rejects_sampling else set[str]()
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"seed", "user", "logit_bias", "logprobs", "top_logprobs", "presence_penalty", "frequency_penalty"} - unsupported,
        responses=RESPONSES_PARAMETERS - unsupported,
        # The OpenAI compatibility layer ignores reasoning_effort; routers translate
        # their native reasoning object independently.
        reasoning_default=rejects_sampling,
        drop_when_reasoning=frozenset({"temperature", "top_p"}),
        temperature_max=1.0, exclusive_sampling=True,
    )
