"""Ports for source-owned recall and knowledge graph relations."""

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from uuid import UUID

from .contracts import MemorySearchItem
from .schemas import MemoryGraphEdge, MemoryRecallRequest

class ResourceSearch(Protocol):
    async def __call__(self, request: MemoryRecallRequest, *,
                       mode: Literal["text", "semantic"] = "semantic") -> list[MemorySearchItem]: ...


ResourceGraph = Callable[[int, set[UUID], UUID | None, int], Awaitable[list[MemoryGraphEdge]]]

resource_search: ResourceSearch | None = None
resource_graph: ResourceGraph | None = None


def register_indexed_resources(*, search: ResourceSearch, graph: ResourceGraph) -> None:
    global resource_search, resource_graph
    resource_search, resource_graph = search, graph
