"""Normalize untyped JSON payloads such as LLM responses.

Provider request and response bodies arrive as raw ``Any`` JSON. These helpers
normalize access and prevent ``Unknown`` propagation in strict Pyright mode.
"""

from __future__ import annotations

from typing import Any, cast


def as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` as ``dict[str, Any]`` or an empty dictionary."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Return ``value`` as ``list[Any]`` or an empty list."""
    return cast("list[Any]", value) if isinstance(value, list) else []
