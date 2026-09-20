"""OpenAI endpoint controls projected from Pydantic AI capabilities."""

from dataclasses import replace

from pydantic_ai.profiles.openai import openai_model_profile

from app.llm import (
    CHAT_PARAMETERS, RESPONSES_PARAMETERS, SAMPLING_PARAMETERS, RequestParameterPolicy,
)


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = openai_model_profile(model)
    reasoning = bool(profile.get("openai_supports_reasoning"))
    # Explicit efforts are left to the SDK/provider; no local table by model version.
    efforts = ("low", "medium", "high", "xhigh", "max")
    if profile.get("openai_supports_reasoning_effort_none"):
        efforts = ("none", *efforts)
    chat = CHAT_PARAMETERS | frozenset({"metadata", "store", "service_tier", "prediction", "safety_identifier"})
    if reasoning:
        chat = chat - {"stop", "prediction"}
    responses = RESPONSES_PARAMETERS | frozenset({
        "service_tier", "prompt_cache_key", "prompt_cache_retention", "background", "safety_identifier",
    })
    fields = {"effort", "summary"}
    if profile.get("openai_responses_supports_reasoning_context"):
        fields.add("context")
    if profile.get("openai_responses_supports_reasoning_mode"):
        fields.add("mode")
    return RequestParameterPolicy(
        chat=chat, responses=responses, efforts=efforts if reasoning else (),
        reasoning_fields=frozenset(fields),
        reasoning_default=bool(profile.get("openai_reasoning_enabled_by_default")),
        drop_when_reasoning=SAMPLING_PARAMETERS,
        chat_token_limit="max_completion_tokens", verbosity=True,
    )


def chatgpt_parameter_policy(model: str) -> RequestParameterPolicy:
    policy = model_parameter_policy(model)
    # Use the endpoint controls already exercised by the Chat-to-Responses transport.
    accepted = frozenset({"parallel_tool_calls", "store", "service_tier", "prompt_cache_key"})
    # ChatGPT's Chat transport converts tool calls to Responses before sending them.
    return replace(policy, responses=policy.responses & accepted, chat_supports_tools=True)
