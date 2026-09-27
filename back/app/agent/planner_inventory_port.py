"""Injected, authorization-preserving reader for durable collection inventories."""

from collections.abc import Awaitable, Callable
from uuid import UUID

PlanInventoryReader = Callable[[int, UUID, str, int], Awaitable[tuple[str, int | None]]]
_reader: PlanInventoryReader | None = None


def register_plan_inventory_reader(reader: PlanInventoryReader) -> None:
    global _reader
    _reader = reader


async def read_plan_inventory(
    agent_id: int, task_id: UUID, uri: str, max_chars: int,
) -> tuple[str, int | None]:
    if _reader is None:
        raise RuntimeError("No authorized collection inventory reader is registered")
    return await _reader(agent_id, task_id, uri, max_chars)
