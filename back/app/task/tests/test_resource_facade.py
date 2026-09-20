from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.task.models import Task, TaskStatus
from app.task.resource_facade import list_task_resources, read_task_resource


async def _agents(db: AsyncSession) -> tuple[Agent, Agent, Agent]:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Resource {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agents = tuple(
        Agent(
            title_id=title.id,
            code=f"resource-{index}-{suffix}",
            first_name="Resource",
            last_name=str(index),
            agent_driver="internal",
        )
        for index in range(3)
    )
    db.add_all(agents)
    await db.flush()
    return agents


@pytest.mark.asyncio
async def test_task_resources_are_scoped_to_owner_or_requester(
    db: AsyncSession,
) -> None:
    owner, requester, foreign_agent = await _agents(db)
    owned = Task(
        label="Owned resource",
        objective="Visible to the owner.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
    )
    requested = Task(
        label="Requested resource",
        objective="Visible to the requester.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        requester_agent_id=requester.id,
    )
    foreign = Task(
        label="Foreign resource",
        objective="Must stay hidden.",
        status=TaskStatus.SUCCESS,
        agent_id=foreign_agent.id,
    )
    db.add_all([owned, requested, foreign])
    await db.flush()

    owner_rows = await list_task_resources(actor_agent_id=owner.id)
    requester_rows = await list_task_resources(actor_agent_id=requester.id)

    assert {row["id"] for row in owner_rows} >= {str(owned.id), str(requested.id)}
    assert {row["id"] for row in requester_rows} == {str(requested.id)}
    assert await read_task_resource(
        requested.id,
        actor_agent_id=requester.id,
    ) is not None
    assert await read_task_resource(
        foreign.id,
        actor_agent_id=requester.id,
    ) is None
