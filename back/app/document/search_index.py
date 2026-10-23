"""Optional search adapters; Document retains admission and canonical fallback."""

from typing import Literal, Protocol
from uuid import UUID


class DocumentSearchIndex(Protocol):
    async def __call__(self, *, agent_id: int, task_id: UUID | None,
        expected_kind: Literal["document"], query: str, mode: Literal["name", "text", "semantic"],
        limit: int | None, offset: int, conversation_turn: object | None = None,
    ) -> dict[str, object]: ...


_index: DocumentSearchIndex | None = None


def register_document_search(index: DocumentSearchIndex | None) -> DocumentSearchIndex | None:
    global _index
    previous, _index = _index, index
    return previous


def document_search_index() -> DocumentSearchIndex | None:
    return _index
