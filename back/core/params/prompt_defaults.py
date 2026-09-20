"""Canonical packaged defaults for configurable model prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_PROMPT_DEFAULTS_DIR = Path(__file__).resolve().parent / "prompt_defaults"


@lru_cache(maxsize=1)
def _defaults() -> dict[str, str]:
    """Load each English Markdown prompt once, keyed by Param name."""

    if not _PROMPT_DEFAULTS_DIR.is_dir():
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8").rstrip("\n")
        for path in sorted(_PROMPT_DEFAULTS_DIR.glob("*.md"))
    }


def prompt_default(name: str) -> str | None:
    """Return one canonical English prompt without locale resolution."""

    return _defaults().get(name)


__all__ = ["prompt_default"]
