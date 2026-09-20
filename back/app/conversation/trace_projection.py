"""Bounded, secret-redacted values for room-visible execution traces."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import JsonValue


_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|passwd|secret|private[_-]?key|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|bearer)",
    re.IGNORECASE,
)
_INLINE_SECRET = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}|"
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)"
    r"\s*[:=]\s*)[^\s,;]+|"
    r"(?:sk|ghp|gho|github_pat|xox[baprs])[-_][a-z0-9_-]{12,}|"
    r"eyj[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}"
)


def public_text(value: object, *, limit: int) -> str:
    """Return bounded text with common inline credential shapes redacted."""

    text = str(value or "")

    def replacement(match: re.Match[str]) -> str:
        return f"{match.group(1) or match.group(2) or ''}[redacted]"

    return _INLINE_SECRET.sub(replacement, text)[:limit]


def _public_value(value: object, *, depth: int = 0) -> JsonValue:
    if depth >= 4:
        return "…"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return public_text(value, limit=4_000)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        output: dict[str, JsonValue] = {}
        for raw_key, child in list(mapping.items())[:50]:
            key = str(raw_key)[:200]
            output[key] = (
                "[redacted]"
                if _SENSITIVE_KEY.search(key)
                else _public_value(child, depth=depth + 1)
            )
        return output
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        sequence = cast(Sequence[object], value)
        return [_public_value(child, depth=depth + 1) for child in list(sequence)[:50]]
    return public_text(value, limit=4_000)


def public_mapping(value: object) -> dict[str, JsonValue]:
    """Project an arbitrary mapping into bounded JSON-safe public fields."""

    if not isinstance(value, Mapping):
        return {}
    projected = _public_value(cast(Mapping[object, object], value))
    return cast(dict[str, JsonValue], projected) if isinstance(projected, dict) else {}


def public_number(value: object) -> float:
    """Normalize a non-negative duration or cost without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, float(value))


__all__ = ["public_mapping", "public_number", "public_text"]
