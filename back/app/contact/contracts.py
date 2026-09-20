"""Public contracts for the canonical contact directory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReachableHumanContact:
    """One deduplicated human together with an exact messaging route."""

    connection_id: int
    tool_id: int
    platform: str
    user_id: str
    display_name: str
    contact_item_id: UUID | None = None
    galaris_user_id: int | None = None
    is_human: Literal[True] = True


__all__ = ["ReachableHumanContact"]
