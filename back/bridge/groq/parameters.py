"""Groq serving restrictions apply even when the model author accepts a control."""

from app.llm import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy
from pydantic_ai.profiles.groq import groq_model_profile


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = groq_model_profile(model)
    efforts: tuple[str, ...] = ()
    aliases: tuple[tuple[str, str], ...] = ()
    if profile.get("groq_supports_graded_reasoning_effort", False):
        efforts = ("low", "medium", "high")
    elif profile.get("supports_thinking", False):
        efforts = (("none", "high") if not profile.get("thinking_always_enabled", False)
                   else ("high",))
        aliases = (("high", "default"),)
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"logprobs", "top_logprobs", "logit_bias", "presence_penalty", "frequency_penalty"},
        responses=RESPONSES_PARAMETERS - {"top_logprobs", "user"},
        efforts=efforts, effort_aliases=aliases,
    )
