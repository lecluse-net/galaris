"""Resolve the durable language of Dream source material."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core.i18n import normalize_language


_LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
}


def source_language(value: object) -> str:
    """Normalize a persisted language code with the instance default as fallback."""

    return normalize_language(value)


def task_language(task: object) -> str:
    """Return the language detected by the dispatcher for one durable Task."""

    raw_data = getattr(task, "data", None)
    data: Mapping[str, Any] = (
        cast(Mapping[str, Any], raw_data) if isinstance(raw_data, Mapping) else {}
    )
    return source_language(data.get("language"))


def output_language_instruction(language: str, *, fields: str) -> str:
    """Build an explicit output-language constraint for a structured inference."""

    normalized = source_language(language)
    name = _LANGUAGE_NAMES.get(normalized, normalized)
    return (
        f"Required output language: {name} ({normalized}). "
        f"Write every generated {fields} in {name}, even when system instructions, "
        "field names, existing records, or technical evidence are in another language. "
        "Keep proper nouns, identifiers, code, and exact technical terms unchanged."
    )


def language_metadata(language: str) -> dict[str, Any]:
    """Return consistent provenance metadata for generated content."""

    return {"language": source_language(language)}


__all__ = [
    "language_metadata",
    "output_language_instruction",
    "source_language",
    "task_language",
]
