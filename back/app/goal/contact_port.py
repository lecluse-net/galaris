"""Injected contact-directory port used by Goal supervision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GoalHumanContact:
    """Human contact data required by Goal without importing the Contact domain."""

    connection_id: int
    tool_id: int
    platform: str
    user_id: str
    display_name: str
    galaris_user_id: int | None = None


class GoalContactDirectoryPort(Protocol):
    async def list_humans(
        self, *, agent_id: int, query: str
    ) -> tuple[GoalHumanContact, ...]: ...


class _GoalContactDirectoryProxy:
    def __init__(self) -> None:
        self._implementation: GoalContactDirectoryPort | None = None

    def register(self, implementation: GoalContactDirectoryPort) -> None:
        self._implementation = implementation

    async def list_humans(
        self, *, agent_id: int, query: str
    ) -> tuple[GoalHumanContact, ...]:
        if self._implementation is None:
            raise RuntimeError("The Goal contact directory is not configured.")
        return await self._implementation.list_humans(agent_id=agent_id, query=query)


contact_directory_port = _GoalContactDirectoryProxy()


def register_goal_contact_directory(
    implementation: GoalContactDirectoryPort,
) -> None:
    contact_directory_port.register(implementation)


__all__ = [
    "GoalContactDirectoryPort",
    "GoalHumanContact",
    "contact_directory_port",
    "register_goal_contact_directory",
]
