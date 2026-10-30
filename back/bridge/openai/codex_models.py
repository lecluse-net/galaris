"""Bridge-local ChatGPT model variants; OpenAI only receives the underlying model."""

from typing import Any

from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.openai_codex import openai_codex_model_profile

from core.util import as_dict, as_list


FAST_SUFFIX = ":fast"


def base_model_name(model: str) -> str:
    return model.removesuffix(FAST_SUFFIX) if model.endswith(FAST_SUFFIX) and model != FAST_SUFFIX else model


def supports_fast(item: dict[str, Any]) -> bool:
    """Prefer the account's explicit tier list over legacy speed hints."""
    if "service_tiers" in item:
        return any(
            isinstance(tier, dict) and as_dict(tier).get("id") in ("priority", "fast")
            for tier in as_list(item.get("service_tiers"))
        )
    return "fast" in as_list(item.get("additional_speed_tiers"))


def apply_model_variant(body: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    """The configured variant wins over client settings, without mutating caller data."""
    forwarded = dict(body)
    model = body.get("model")
    if isinstance(model, str) and (base := base_model_name(model)) != model:
        forwarded["model"] = base
        if compact:
            forwarded.pop("service_tier", None)
        else:
            forwarded["service_tier"] = "priority"
    return forwarded


def chatgpt_model_profile(model: str) -> ModelProfile:
    return openai_codex_model_profile(base_model_name(model))
