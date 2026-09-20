import pytest

from app.llm.reasoning import REASONING_EFFORTS, normalize_reasoning_effort
from app.llm.profile_schemas import LlmProfileUpdate


def test_reasoning_efforts_use_the_cross_provider_scale() -> None:
    assert REASONING_EFFORTS == (
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )


def test_legacy_minimal_effort_is_normalized_to_low() -> None:
    assert normalize_reasoning_effort("minimal", strict=True) == "low"

    profile = LlmProfileUpdate(text_low_reasoning_effort="minimal")
    assert profile.text_low_reasoning_effort == "low"


def test_unknown_reasoning_effort_remains_invalid() -> None:
    with pytest.raises(ValueError, match="Unsupported reasoning effort"):
        normalize_reasoning_effort("extreme", strict=True)
