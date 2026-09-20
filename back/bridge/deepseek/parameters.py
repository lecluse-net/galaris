"""DeepSeek thinking controls for Chat Completions and Responses."""

from app.llm import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy
from pydantic_ai.providers.deepseek import DeepSeekProvider


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = DeepSeekProvider.model_profile(model) or {}
    adjustable_thinking = profile.get("supports_thinking", False) and not profile.get("thinking_always_enabled", False)
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"parallel_tool_calls", "user", "seed", "logit_bias"},
        responses=RESPONSES_PARAMETERS - {"store", "metadata", "user", "truncation", "top_logprobs"},
        efforts=("none", "low", "high", "max") if adjustable_thinking else (),
        reasoning_default=profile.get("openai_reasoning_enabled_by_default", False) or profile.get("thinking_always_enabled", False),
        drop_when_reasoning=frozenset({"temperature", "top_p", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs"}),
        thinking_toggle=adjustable_thinking,
        forced_tools_when_reasoning=profile.get("openai_supports_forced_tool_choice_with_thinking", True),
    )
