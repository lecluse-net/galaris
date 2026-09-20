"""Canonical reasoning-effort validation and precedence rules."""

from __future__ import annotations

from .provider_facade import ReasoningEffort


REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
_REASONING_EFFORT_SET = frozenset(REASONING_EFFORTS)


def normalize_reasoning_effort(
    value: object,
    *,
    strict: bool = False,
) -> ReasoningEffort | None:
    """Normalize one canonical value; optionally reject unsupported values."""

    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    # ``minimal`` was exposed by Galaris before providers converged on ``low``
    # as the broadly supported low-latency level. Keep old rows and run metadata
    # readable without ever emitting the retired value again.
    if normalized == "minimal":
        normalized = "low"
    if normalized not in _REASONING_EFFORT_SET:
        if strict:
            raise ValueError(f"Unsupported reasoning effort: {normalized}")
        return None
    return normalized


def parse_force_reasoning_effort(value: object) -> bool:
    """Parse the explicit marker that lets a harness override profile policy."""

    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"", "0", "false", "no"}:
        return False
    if normalized in {"1", "true", "yes"}:
        return True
    raise ValueError("galaris_force_reasoning_effort must be a boolean")


def effective_reasoning_effort(
    requested: object,
    *,
    configured: ReasoningEffort | None,
    force: bool,
) -> ReasoningEffort | None:
    """Prefer a forced harness value, otherwise the configured profile value."""

    requested_effort = normalize_reasoning_effort(requested)
    return (
        requested_effort
        if force and requested_effort is not None
        else configured or requested_effort
    )
