from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.file_share import ResourceContext, resource_info, resource_list, resource_read, resource_search
from app.goal.models import Goal, GoalCycle, GoalCycleStatus, GoalStatus
from app.goal.tests.factories import make_goal
from app.goal.resource_facade import (
    list_goal_cycle_resources,
    read_goal_cycle_resource,
    read_goal_resource,
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
    snapshot = await read_goal_resource(own_goal.id, actor_agent_id=owner.id)
    assert snapshot is not None
    assert snapshot["description"] == own_goal.description
    assert snapshot["tracking_document_id"] == str(own_goal.tracking_document_id)
    assert snapshot["resource_uri"] == f"galaris://goal/{own_goal.id}"
    assert "description_document_id" not in snapshot
    assert await read_goal_resource(foreign_goal.id, actor_agent_id=owner.id) is None


@pytest.mark.asyncio
async def test_goal_cycle_folders_keep_goal_first_number_cycles_and_preserve_live_scope(db: AsyncSession) -> None:
    owner, foreign_owner = await _agents(db)
    goals = [await make_goal(agent_id=agent.id, title="Synthetic same title", description="Synthetic cycles.",
        status=GoalStatus.ACTIVE) for agent in (owner, owner, foreign_owner)]
    db.add_all(goals)
    await db.flush()
    own, empty, foreign = goals
    cycles = [GoalCycle(goal_id=own.id, sequence=sequence, status=GoalCycleStatus.RUNNING)
        for sequence in (10000, 2, 1)]
    db.add_all([*cycles, GoalCycle(goal_id=foreign.id, sequence=1, status=GoalCycleStatus.RUNNING)])
    await db.flush()
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    folder = f"galaris://goal/{own.id}/"
    for limit in (1, 2, 500):
        folders = []
        cursor = None
        while True:
            page = await resource_list(ctx, "galaris://goal/", max_entries=limit, cursor=cursor)
            folders.extend(page.entries)
            if not page.truncated:
                assert page.next_cursor is None
                break
            assert page.next_cursor is not None and page.next_cursor != cursor
            cursor = page.next_cursor
        assert {entry.uri for entry in folders} == {folder, f"galaris://goal/{empty.id}/"}
        assert all(entry.is_collection and entry.name == own.title for entry in folders)
        entries = []
        cursor = None
        while True:
            page = await resource_list(ctx, folder, max_entries=limit, cursor=cursor)
            assert len(page.entries) <= limit
            assert page.ancestors[-1].name == own.title
            assert [entry.uri for entry in page.ancestors] == ["galaris://", "galaris://goal/", folder]
            entries.extend(page.entries)
            if not page.truncated:
                assert page.next_cursor is None
                break
            assert page.next_cursor is not None and page.next_cursor != cursor
            cursor = page.next_cursor
        assert [entry.uri for entry in entries] == [f"galaris://goal/{own.id}",
            *[f"galaris://goal_cycle/{cycle.id}" for cycle in reversed(cycles)]]
        assert [entry.name for entry in entries] == [own.title, "0001", "0002", "10000"]
        assert [entry.metadata["sort_order"] for entry in entries] == [0, 1, 2, 10000]
    empty_page = await resource_list(ctx, f"galaris://goal/{empty.id}/", max_entries=1)
    assert [entry.uri for entry in empty_page.entries] == [f"galaris://goal/{empty.id}"]
    assert not empty_page.truncated
    for operation in (resource_info, resource_list):
        with pytest.raises(FileNotFoundError):
            await operation(ctx, f"galaris://goal/{foreign.id}/")
    own.title = "Synthetic renamed goal"
    await db.flush()
    assert (await resource_info(ctx, folder)).name == own.title
    assert (await resource_list(ctx, folder)).entries[0].name == own.title
    search = await resource_search(ctx, "galaris://goal/", "renamed", mode="name")
    assert [hit.resource.uri for hit in search.hits] == [folder]
    assert search.hits[0].resource.is_collection
    assert (await resource_info(ctx, f"galaris://goal_cycle/{own.id}/")).uri == folder
    cycle_uri = f"galaris://goal_cycle/{cycles[1].id}"
    assert (await resource_info(ctx, cycle_uri)).name == "0002"
    assert '"sequence": 2' in (await resource_read(ctx, cycle_uri)).content
    search = await resource_search(ctx, folder, "0002", mode="name")
    assert any(hit.resource.uri == cycle_uri and hit.resource.name == "0002" for hit in search.hits)
    legacy = await resource_list(ctx, f"galaris://goal/{own.id}/cycles/")
    assert {entry.uri for entry in legacy.entries} == {f"galaris://goal_cycle/{cycle.id}" for cycle in cycles}
