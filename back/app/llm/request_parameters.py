"""Pure wire-parameter adaptation shared by provider-owned compatibility policies."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, cast


RequestProtocol = Literal["chat", "responses", "compact"]
EFFORT_ORDER = ("none", "low", "medium", "high", "xhigh", "max")
SAMPLING_PARAMETERS = frozenset({
    "temperature", "top_p", "presence_penalty", "frequency_penalty",
    "logit_bias", "logprobs", "top_logprobs",
})
# These are generation controls, not user content, tools or output schemas. A provider
# must explicitly opt into controls beyond the conservative OpenAI-compatible fallback.
CONTROL_PARAMETERS = SAMPLING_PARAMETERS | frozenset({
    "seed", "stop", "parallel_tool_calls", "stream_options", "user", "store",
    "metadata", "service_tier", "prediction", "reasoning_effort", "reasoning",
    "max_tokens", "max_completion_tokens", "max_output_tokens", "verbosity",
    "prompt_cache_key", "prompt_cache_retention", "prompt_cache_options",
    "background", "truncation", "context_management", "safety_identifier", "thinking",
})
# Content/envelope fields are preserved, never treated as optional generation tuning.
# Unknown extension fields pass through; provider errors and SDK profiles govern support.
PAYLOAD_PARAMETERS = frozenset({
    "model", "messages", "input", "instructions", "stream", "tools", "tool_choice",
    "response_format", "text", "include", "previous_response_id", "conversation",
    "prompt", "audio", "modalities", "n", "functions", "function_call", "web_search_options",
})
NESTED_PARAMETERS: dict[str, frozenset[str]] = {
    "reasoning": frozenset({"effort", "summary", "context", "mode", "enabled", "exclude", "max_tokens"}),
    "text": frozenset({"format", "verbosity"}),
    "stream_options": frozenset({"include_usage", "include_obfuscation"}),
    "thinking": frozenset({"type", "budget_tokens", "display"}),
}
BASIC_PARAMETERS = frozenset({"max_tokens", "max_output_tokens"})
CHAT_PARAMETERS = BASIC_PARAMETERS | SAMPLING_PARAMETERS | frozenset({
    "seed", "stop", "parallel_tool_calls", "stream_options", "user",
})
RESPONSES_PARAMETERS = frozenset({
    "max_output_tokens", "temperature", "top_p", "top_logprobs", "parallel_tool_calls",
    "store", "metadata", "user", "truncation",
})


@dataclass(frozen=True, slots=True)
class RequestParameterPolicy:
    """Capabilities of a model on a particular serving endpoint, not its marketing name."""

    chat: frozenset[str] = BASIC_PARAMETERS
    responses: frozenset[str] = BASIC_PARAMETERS
    efforts: tuple[str, ...] = ()
    chat_efforts: tuple[str, ...] | None = None
    reasoning_fields: frozenset[str] = frozenset({"effort"})
    reasoning_default: bool = False
    drop_when_reasoning: frozenset[str] = frozenset()
    chat_token_limit: str = "max_tokens"
    temperature_max: float = 2.0
    exclusive_sampling: bool = False
    verbosity: bool = False
    # DeepSeek Chat uses a separate thinking toggle; effort='none' is not a wire enum.
    thinking_toggle: bool = False
    chat_reasoning_object: bool = False
    effort_aliases: tuple[tuple[str, str], ...] = ()
    chat_supports_tools: bool = True
    forced_tools_when_reasoning: bool = True

    def __post_init__(self) -> None:
        unknown = (self.chat | self.responses | self.drop_when_reasoning) - CONTROL_PARAMETERS
        unknown_reasoning = self.reasoning_fields - NESTED_PARAMETERS["reasoning"]
        if unknown or unknown_reasoning:
            raise ValueError(
                "Unreviewed policy parameters: "
                + ", ".join(sorted(unknown | {f"reasoning.{key}" for key in unknown_reasoning}))
            )


ParameterPolicyResolver = Callable[[str], RequestParameterPolicy]
def compatible_parameter_policy() -> RequestParameterPolicy:
    """Unknown gateways delegate model-specific capabilities to their upstream."""
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS, responses=RESPONSES_PARAMETERS, efforts=EFFORT_ORDER,
    )


def _map_effort(value: object, supported: tuple[str, ...]) -> str | None:
    if value is None or not supported:
        return None
    effort = "low" if value == "minimal" else str(value)
    if effort in supported:
        return effort
    if effort not in EFFORT_ORDER:
        raise ValueError(f"Unsupported reasoning effort: {effort}")
    target = EFFORT_ORDER.index(effort)
    candidates = tuple(item for item in supported if effort == "none" or item != "none")
    if not candidates:
        return None
    # Preserve the requested minimum effort where possible, capped at the provider maximum.
    return next((item for item in candidates if EFFORT_ORDER.index(item) >= target), candidates[-1])


def adapt_request_parameters(
    body: dict[str, Any], policy: RequestParameterPolicy, protocol: RequestProtocol,
) -> dict[str, Any]:
    """Return a fresh request; never mutate caller-owned history, tools or settings."""
    result = deepcopy(body)
    if protocol == "chat" and result.get("tools") and not policy.chat_supports_tools:
        raise ValueError("This model requires the Responses API for tool calls; use /responses.")
    if protocol == "compact":
        for key in CONTROL_PARAMETERS:
            result.pop(key, None)
        return result

    supported = policy.chat if protocol == "chat" else policy.responses
    reasoning_raw = result.get("reasoning")
    reasoning: dict[str, Any] = dict(cast(dict[str, Any], reasoning_raw)) if isinstance(reasoning_raw, dict) else {}
    requested_effort = result.get("reasoning_effort", reasoning.get("effort"))
    thinking = cast(dict[str, Any] | None, result.get("thinking"))
    if requested_effort is None:
        if policy.thinking_toggle and isinstance(thinking, dict) and thinking.get("type") == "disabled":
            requested_effort = "none"
        elif policy.chat_reasoning_object and reasoning.get("enabled") is False:
            requested_effort = "none"
    reverse_aliases = {wire: canonical for canonical, wire in policy.effort_aliases}
    if isinstance(requested_effort, str):
        requested_effort = reverse_aliases.get(requested_effort, requested_effort)
    efforts = policy.chat_efforts if protocol == "chat" and policy.chat_efforts is not None else policy.efforts
    effort = _map_effort(requested_effort, efforts)
    active = policy.reasoning_default if effort is None else effort != "none"
    if effort is None and policy.chat_reasoning_object and (
        reasoning.get("enabled") is True or reasoning.get("max_tokens")
    ):
        active = True
    choice = result.get("tool_choice")
    if active and not policy.forced_tools_when_reasoning and (
        choice == "required" or isinstance(choice, dict)
    ):
        raise ValueError("This model does not support forced tool_choice while reasoning is enabled.")

    for key in CONTROL_PARAMETERS - supported:
        result.pop(key, None)
    # A budget is functional: translate its spelling, preserving the stricter cap if
    # a client supplied multiple aliases, instead of silently losing it in the adapter.
    limits: list[int] = []
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        value = body.get(key)
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            limits.append(value)
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        result.pop(key, None)
    limit_key = policy.chat_token_limit if protocol == "chat" else "max_output_tokens"
    if limits and (limit_key in supported or "max_tokens" in supported):
        result[limit_key] = min(limits)

    result.pop("reasoning_effort", None)
    result.pop("reasoning", None)
    if efforts:
        wire_effort = dict(policy.effort_aliases).get(effort, effort) if effort else None
        if protocol == "chat" and not policy.chat_reasoning_object:
            if policy.thinking_toggle and effort is not None:
                result["thinking"] = {"type": "disabled" if effort == "none" else "enabled"}
            if effort is not None and not (policy.thinking_toggle and effort == "none"):
                result["reasoning_effort"] = wire_effort
        else:
            reasoning = {key: value for key, value in reasoning.items() if key in policy.reasoning_fields}
            if effort is not None:
                reasoning["effort"] = wire_effort
                if "enabled" in reasoning:
                    reasoning["enabled"] = effort != "none"
            if reasoning:
                result["reasoning"] = reasoning

    if active:
        for key in policy.drop_when_reasoning:
            result.pop(key, None)
    temperature = result.get("temperature")
    if isinstance(temperature, (int, float)):
        result["temperature"] = min(max(temperature, 0.0), policy.temperature_max)
    if policy.exclusive_sampling and temperature is not None:
        result.pop("top_p", None)
    text = cast(dict[str, Any] | None, result.get("text"))
    if isinstance(text, dict) and not policy.verbosity:
        text.pop("verbosity", None)
        if not text:
            result.pop("text", None)
    if "top_logprobs" not in result and isinstance(result.get("include"), list):
        result["include"] = [item for item in result["include"] if item != "message.output_text.logprobs"]
        if not result["include"]:
            result.pop("include")
    if not result.get("stream"):
        result.pop("stream_options", None)
    if not result.get("tools"):
        result.pop("parallel_tool_calls", None)
    return result
