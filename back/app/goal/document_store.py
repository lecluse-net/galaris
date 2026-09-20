"""Provider-neutral port for Goal-owned editorial HTML documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GoalMarkdown:
    description: str
    tracking: str


GoalDocumentKind = Literal["description", "tracking"]


class GoalDocumentStore(Protocol):
    async def create(
        self,
        *,
        goal_id: UUID,
        owner_agent_id: int,
        kind: GoalDocumentKind,
        goal_title: str,
        content: str,
    ) -> UUID: ...

    async def read(self, document_id: UUID) -> str: ...

    async def revision(self, document_id: UUID) -> int: ...

    async def read_many(self, document_ids: tuple[UUID, ...]) -> dict[UUID, str]: ...

    async def update(
        self,
        document_id: UUID,
        *,
        content: str | None = None,
        expected_revision: int | None = None,
        goal_title: str | None = None,
        owner_agent_id: int | None = None,
    ) -> None: ...

    async def discard(self, document_id: UUID) -> None: ...

    async def search(self, terms: tuple[str, ...]) -> dict[str, frozenset[UUID]]: ...


_store: GoalDocumentStore | None = None


def register_goal_document_store(store: GoalDocumentStore) -> None:
    global _store
    _store = store


def get_goal_document_store() -> GoalDocumentStore:
    if _store is None:
        raise RuntimeError("The Goal document store is not registered.")
    return _store


def reset_goal_document_store() -> None:
    global _store
    _store = None


__all__ = [
    "GoalDocumentStore",
    "GoalDocumentKind",
    "GoalMarkdown",
    "get_goal_document_store",
    "register_goal_document_store",
    "reset_goal_document_store",
]
