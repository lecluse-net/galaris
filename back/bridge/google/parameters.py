"""Gemini OpenAI-compatibility controls (not the native generateContent schema)."""

from app.llm import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy
from pydantic_ai.profiles.google import google_model_profile


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = google_model_profile(model) or {}
    reasoning = profile.get("supports_thinking", False)
    can_disable = not profile.get("thinking_always_enabled", False)
    efforts = (("none",) if can_disable else ()) + ("low", "medium", "high")
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"logit_bias", "logprobs", "top_logprobs", "user"},
        responses=RESPONSES_PARAMETERS,
        efforts=efforts if reasoning else (),
    )
