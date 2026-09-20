"""Explicit authenticated human identity for domain operations without an Agent."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HumanActor:
    user_id: int
