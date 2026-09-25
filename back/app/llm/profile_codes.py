"""Stable ASCII names for public profile model selectors."""

import re
import unicodedata
from collections.abc import Collection
from typing import Protocol


MAX_PROFILE_CODE_LENGTH = 100


def profile_code(label: str, occupied: Collection[str] = ()) -> str:
    normalized = label.lower().translate(str.maketrans({
        "œ": "oe", "æ": "ae", "ß": "ss", "ø": "o", "ł": "l", "đ": "d",
    }))
    normalized = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9_-]", "", normalized)
    base = re.sub(r"-+", "-", normalized).strip("-_")[:MAX_PROFILE_CODE_LENGTH] or "profil"
    candidate = base
    counter = 2
    while candidate in occupied:
        suffix = f"-{counter}"
        candidate = base[:MAX_PROFILE_CODE_LENGTH - len(suffix)] + suffix
        counter += 1
    return candidate


class _DefaultContext(Protocol):
    def get_current_parameters(self) -> dict[str, object]: ...


def default_profile_code(context: _DefaultContext) -> str:
    """Cover direct ORM inserts; public creation allocates under a database lock."""
    return profile_code(str(context.get_current_parameters()["label"]))
