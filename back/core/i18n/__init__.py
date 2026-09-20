"""Backend i18n engine for language resolution, lookup, and template rendering.

Message catalogs live in each module's ``i18n`` package. ``catalog.py`` discovers and merges
them lazily, while ``i18n_service`` exposes the public API.
"""

from .catalog import SUPPORTED_LANGUAGES
from .i18n_service import (
    current_language,
    default_language,
    is_supported,
    normalize_language,
    render_prompt,
    t,
    tr,
)

__all__ = [
    "current_language",
    "default_language",
    "is_supported",
    "normalize_language",
    "render_prompt",
    "t",
    "tr",
    "SUPPORTED_LANGUAGES",
]
