"""Read planner inventories through the canonical resource authorization boundary."""

from uuid import UUID

from app.agent import register_plan_inventory_reader
from .resource_contracts import ResourceContext
from .resource_service import resource_read


async def read_plan_inventory(
    agent_id: int, task_id: UUID, uri: str, max_chars: int,
) -> tuple[str, int | None]:
    result = await resource_read(
        ResourceContext(agent_id=agent_id, task_id=task_id, runtime="internal"),
        uri, max_chars=max_chars,
    )
    if (result.media_type != "application/json" or result.encoding != "utf-8"
            or result.next_offset is not None or result.total > max_chars):
        raise ValueError("Collection inventory must be complete bounded UTF-8 JSON")
    return result.content, result.revision


def register_planner_inventory_adapter() -> None:
    register_plan_inventory_reader(read_plan_inventory)
