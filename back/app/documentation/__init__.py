"""Versioned product documentation and rebuildable retrieval projections.

The ORM model is exported lazily so offline checks (`check`, `revision`) run without
SQLAlchemy or application settings imported at package load time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import DocumentationPassage

__all__ = ["DocumentationPassage"]


def __getattr__(name: str) -> Any:
    if name == "DocumentationPassage":
        from .models import DocumentationPassage

        return DocumentationPassage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
