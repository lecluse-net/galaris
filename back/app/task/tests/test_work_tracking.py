from uuid import uuid4
import asyncio

import pytest
from pydantic import ValidationError

from app.agent import WorkPlan, work_plan_progress
from app.task import Task, TaskStatus
from app.task.mcp import mcp_work_update
from app.tools.mcp_loader import McpToolContext
from core.database import get_db_session


def plan(state="doing", observation="", next_action="Inspect the remaining inputs"):
    return WorkPlan.model_validate({"milestones": [
        {"key": "prepare", "label": "Verify the method", "acceptance": "One input is processed and reread",
         "state": state, "observation": observation},
    ], "next_action": next_action})


async def seed(db):
    from app.agent.models import Agent, Title
    from core.user.models import User
    user = User(email=f"synthetic-{uuid4()}@example.test", hashed_password="synthetic-unusable")
    db.add(user)
    await db.flush()
    title = Title(label="Synthetic", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(code=f"synthetic-{uuid4()}", first_name="Synthetic", last_name="Executor", title_id=title.id, user_id=user.id)
    db.add(agent)
    await db.flush()
    current = Task(id=uuid4(), label="Synthetic work", objective="<p>Prepare one study.</p>",
                   agent_id=agent.id, status=TaskStatus.EXEC, paused=False,
                   data={"existing": {"keep": True}}, cost=0.0)
    db.add(current)
    await db.flush()
    return current


@pytest.mark.asyncio
async def test_work_tracking_survives_reload_and_preserves_completed_work(committed_database):
    async with get_db_session() as db:
        current = await seed(db)
        task_id, agent_id, revision = current.id, current.agent_id, current.revision
    ctx = McpToolContext(agent_id=agent_id, runtime="internal", task_id=task_id)
    async with get_db_session():
        started = await mcp_work_update(ctx, plan(), revision)
    async with get_db_session() as db:
        current = await db.get(Task, task_id)
        assert current.data["existing"] == {"keep": True}
        assert current.status == TaskStatus.EXEC
        assert current.data["work_plan"]["next_action"] == "Inspect the remaining inputs"
        # A stale write must not replace newer progress.
        with pytest.raises(ValueError, match="revision changed"):
            await mcp_work_update(ctx, plan("done", "Reread output matches the sample", ""), revision)
        done = await mcp_work_update(ctx, plan("done", "Reread output matches the sample", ""), started["revision"])
        duplicate = await mcp_work_update(ctx, plan("done", "Reread output matches the sample", ""), started["revision"])
        assert duplicate == done
        with pytest.raises(ValueError, match="revision reason"):
            await mcp_work_update(ctx, plan(), done["revision"])
        reopened = await mcp_work_update(ctx, plan(), done["revision"], "A new input invalidates the initial assumption")
        assert reopened["work_plan"]["milestones"][0]["state"] == "doing"
        current.status = TaskStatus.SUCCESS
        await db.commit()
        with pytest.raises(ValueError, match="terminal"):
            await mcp_work_update(ctx, plan(), current.revision)


@pytest.mark.asyncio
async def test_tracking_is_owned_by_the_current_executor_and_respects_pause(committed_database):
    async with get_db_session() as db:
        current = await seed(db)
        task_id, agent_id, revision = current.id, current.agent_id, current.revision
        current.paused = True
    async with get_db_session():
        with pytest.raises(PermissionError):
            await mcp_work_update(McpToolContext(agent_id=agent_id + 1, runtime="internal", task_id=task_id), plan(), revision)
        with pytest.raises(PermissionError):
            await mcp_work_update(McpToolContext(agent_id=agent_id, runtime="internal"), plan(), revision)
        with pytest.raises(ValueError, match="inactive"):
            await mcp_work_update(McpToolContext(agent_id=agent_id, runtime="internal", task_id=task_id), plan(), revision)


@pytest.mark.asyncio
async def test_concurrent_progress_writers_cannot_erase_each_other(committed_database):
    async with get_db_session() as db:
        current = await seed(db)
        task_id, agent_id = current.id, current.agent_id
        current.data = {**current.data, "_agent_run_checkpoint": {"opaque": "preserved"}}
        await db.flush()
        revision = current.revision  # Both writers start from the committed checkpoint revision.
    ctx = McpToolContext(agent_id=agent_id, runtime="internal", task_id=task_id)

    async def write(next_action):
        async with get_db_session():
            return await mcp_work_update(ctx, plan(next_action=next_action), revision)

    results = await asyncio.gather(write("Check source A"), write("Check source B"), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    async with get_db_session() as db:
        current = await db.get(Task, task_id)
        assert current.data["_agent_run_checkpoint"] == {"opaque": "preserved"}
        assert current.data["existing"] == {"keep": True}
        assert current.data["work_plan"]["next_action"] in {"Check source A", "Check source B"}


@pytest.mark.asyncio
async def test_retry_cannot_execute_an_unanswered_organization_question(committed_database):
    from app.task import task_service
    async with get_db_session() as db:
        current = await seed(db)
        current.status = TaskStatus.ERROR
        current.data = {"organization": "clarify", "organization_clarification": True,
                        "clarifications": [{"questions": ["Which depth?"], "answer": None}]}
        await db.commit()
        retried = await task_service.retry(current.id, current.revision)
        assert retried.status == TaskStatus.CREATE
        assert retried.data["organization"] == "clarify"


@pytest.mark.parametrize("defect", ["unchecked", "no_next_action", "duplicate", "multiple_current"])
def test_tracking_requires_bounded_useful_progress(defect):
    raw = plan().model_dump()
    if defect == "unchecked":
        raw["milestones"][0]["state"] = "done"
    elif defect == "no_next_action":
        raw["next_action"] = ""
    elif defect == "duplicate":
        raw["milestones"].append(raw["milestones"][0].copy())
    else:
        raw["milestones"].append(raw["milestones"][0] | {"key": "another"})
    with pytest.raises(ValidationError):
        WorkPlan.model_validate(raw)


def test_progress_reports_milestones_without_fabricating_a_task_outcome():
    current = plan("done", "The output was reread and matched", "").model_dump(mode="json")
    assert work_plan_progress({"work_plan": current}) == {
        "done": 1, "total": 1, "percent": 100,
        "current": None, "next_action": "", "kind": "milestones",
    }
    assert work_plan_progress({"work_plan": current | {"schema_version": "future/v2"}}) is None
    assert work_plan_progress({"work_plan": {}}) is None
