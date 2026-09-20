"""Translations for the SSH console module."""

from typing import Any

from . import en, fr

messages: dict[str, dict[str, Any]] = {"en": en.default, "fr": fr.default}

__all__ = ["messages"]
