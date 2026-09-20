"""Agent-module catalog aggregated by ``core.i18n``.

System contracts remain canonical English prompts; user-facing notices and Janus dialogue
are localized in ``en.py`` and ``fr.py``.
"""

from typing import Any

from . import en, fr

messages: dict[str, dict[str, Any]] = {"en": en.default, "fr": fr.default}

__all__ = ["messages"]
