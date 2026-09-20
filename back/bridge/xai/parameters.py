"""xAI controls use Grok's capabilities, not OpenAI reasoning restrictions."""

from pydantic_ai.profiles.grok import grok_model_profile

from app.llm import CHAT_PARAMETERS, RESPONSES_PARAMETERS, RequestParameterPolicy


def model_parameter_policy(model: str) -> RequestParameterPolicy:
    profile = grok_model_profile(model) or {}
    native = profile.get("grok_reasoning_efforts", frozenset[str]())
    efforts = tuple(effort for effort in ("none", "low", "medium", "high", "xhigh") if effort in native)
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS, responses=RESPONSES_PARAMETERS,
        efforts=efforts, reasoning_fields=frozenset({"effort", "summary"}),
        reasoning_default=bool(efforts) and "none" not in efforts,
        drop_when_reasoning=frozenset({"presence_penalty", "frequency_penalty", "stop"}),
    )
