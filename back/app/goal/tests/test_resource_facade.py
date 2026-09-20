from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.goal.models import Goal, GoalCycle, GoalCycleStatus, GoalStatus
from app.goal.tests.factories import make_goal
from app.goal.resource_facade import (
    list_goal_cycle_resources,
    read_goal_cycle_resource,
)


async def _agents(db: AsyncSession) -> tuple[Agent, Agent]:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Goal resource {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agents = tuple(
        Agent(
            title_id=title.id,
            code=f"goal-resource-{index}-{suffix}",
            first_name="Goal",
            last_name=str(index),
            agent_driver="internal",
        )
        for index in range(2)
    )
    db.add_all(agents)
    await db.flush()
    return agents


@pytest.mark.asyncio
async def test_goal_cycle_resources_are_scoped_to_goal_owner(
    db: AsyncSession,
) -> None:
    owner, foreign_owner = await _agents(db)
    own_goal = await make_goal(
        agent_id=owner.id,
        title="Own goal",
        description="Visible goal cycles.",
        status=GoalStatus.ACTIVE,
    )
    foreign_goal = await make_goal(
        agent_id=foreign_owner.id,
        title="Foreign goal",
        description="Hidden goal cycles.",
        status=GoalStatus.ACTIVE,
    )
    db.add_all([own_goal, foreign_goal])
    await db.flush()
    own_cycle = GoalCycle(
        goal_id=own_goal.id,
        sequence=1,
        status=GoalCycleStatus.RUNNING,
    )
    foreign_cycle = GoalCycle(
        goal_id=foreign_goal.id,
        sequence=1,
        status=GoalCycleStatus.RUNNING,
    )
    db.add_all([own_cycle, foreign_cycle])
    await db.flush()

    rows = await list_goal_cycle_resources(actor_agent_id=owner.id)

    assert [row["id"] for row in rows] == [str(own_cycle.id)]
    assert await read_goal_cycle_resource(
        own_cycle.id,
        actor_agent_id=owner.id,
    ) is not None
    assert await read_goal_cycle_resource(
        foreign_cycle.id,
        actor_agent_id=owner.id,
    ) is None
