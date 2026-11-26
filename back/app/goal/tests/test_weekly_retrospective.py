"""Real Goal admission, MCP authorization and personal package persistence."""

from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent import agent_service
from app.agent.contracts import AIMessage, ExecutionResult
from app.agent.schemas import AgentCreate
from app.goal import calendar, goal_service, retrospective, runner, settings_service
from app.goal.models import Goal, GoalCycle, GoalStatus, GoalVerdict
from app.goal.schemas import GoalCommand, GoalSettingsUpdate, GoalUpdate
from app.goal.tests.factories import make_goal
from app.goal.tests.test_calendar import START, clock, create_goal
from app.goal.tests.test_goal_runner import _new_agent
from app.services.mcp_loader import execute_native_mcp_tool, list_enabled_native_mcp_definitions
from app.services.mandatory_services import sync_integrated_service_connections
from app.skill import Skill, SkillLearningEvidence, storage
from app.task import Task
from app.task.models import TaskStatus
from core.i18n import t


async def _weekly(db, agent_id):
    return await db.scalar(select(Goal).where(
        Goal.agent_id == agent_id, Goal.is_weekly_retrospective.is_(True),
    ))


@pytest.mark.asyncio
async def test_creation_and_reconciliation_keep_one_protected_pausable_goal(db):
    legacy = await _new_agent(db)
    assert await _weekly(db, legacy.id) is None
    new = await agent_service.create(AgentCreate(
        title_id=legacy.title_id, user_id=legacy.user_id,
        code=f"weekly-{uuid4().hex[:10]}", first_name="Synthetic",
    ))
    goal = await _weekly(db, new.id)
    assert goal is not None and goal.recurrence["frequency"] == "WEEKLY"
    assert goal.referrer_type is None and goal.status == GoalStatus.ACTIVE
    assert (await goal_service.get_read(goal.id)).is_weekly_retrospective

    protection = GoalCommand(expected_revision=goal.revision)
    with pytest.raises(goal_service.GoalConflictError, match="required"):
        await goal_service.delete(goal.id)
    with pytest.raises(goal_service.GoalConflictError, match="paused instead"):
        await goal_service.complete(goal.id, protection)
    with pytest.raises(goal_service.GoalConflictError, match="stays assigned"):
        await goal_service.update(goal.id, GoalUpdate(expected_revision=goal.revision, agent_id=legacy.id))
    paused = await goal_service.pause(goal.id, protection)
    assert paused.status == GoalStatus.PAUSED
    with pytest.raises(goal_service.GoalConflictError, match="Resume"):
        await goal_service.run_now(goal.id, GoalCommand(expected_revision=paused.revision))
    with pytest.raises(goal_service.GoalConflictError, match="requires a calendar recurrence"):
        await goal_service.update(goal.id, GoalUpdate(expected_revision=paused.revision, recurrence=None))
    updated = await goal_service.update(goal.id, GoalUpdate(
        expected_revision=paused.revision, title=t("goal_retrospective.legacy_title", "fr"),
        recurrence=paused.recurrence.model_copy(update={"frequency": "MONTHLY", "interval": 2}),
    ))
    goal.description = f"<p>{t('goal_retrospective.legacy_description', 'fr')}</p>"
    await db.commit()

    for index in range(2):
        db.add(await make_goal(title=f"Synthetic objective {index}", description="<p>Test list.</p>",
                               agent_id=new.id, status=GoalStatus.ACTIVE))
    await db.flush()
    regular = await goal_service.list_page(agent_ids={new.id}, is_weekly_retrospective=False, limit=1)
    assert len(regular.items) == 1 and not regular.items[0].is_weekly_retrospective
    assert regular.total == regular.summary.active == 2 and regular.summary.paused == 0
    weekly = await goal_service.list_page(agent_ids={new.id}, is_weekly_retrospective=True, limit=1)
    assert [item.id for item in weekly.items] == [goal.id]
    assert weekly.total == weekly.summary.paused == 1 and weekly.summary.active == 0
    assert (await goal_service.list_page(agent_ids={new.id})).total == 3

    await retrospective.reconcile_weekly_retrospectives()
    repaired = await _weekly(db, legacy.id)
    assert repaired is not None and repaired.status == GoalStatus.ACTIVE
    await retrospective.reconcile_weekly_retrospectives()
    assert (await _weekly(db, legacy.id)).id == repaired.id
    renamed = await goal_service.get_read(goal.id)
    assert renamed.id == paused.id and renamed.status == GoalStatus.PAUSED
    assert renamed.title == t("goal_retrospective.title", "fr")
    assert renamed.description == f"<p>{t('goal_retrospective.description', 'fr')}</p>"
    assert renamed.tracking_document_id == paused.tracking_document_id
    assert renamed.recurrence == updated.recurrence
    resumed = await goal_service.resume(renamed.id, GoalCommand(expected_revision=renamed.revision))
    assert resumed.status == GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_scheduled_review_applies_verified_personal_learning_and_continues(
    db, clock, tmp_path, monkeypatch,
):
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    owner, other = await _new_agent(db), await _new_agent(db)
    await sync_integrated_service_connections(owner.id)
    await retrospective.ensure_weekly_retrospective(owner.id, now=START - timedelta(days=10))
    await db.commit()
    goal = await _weekly(db, owner.id)
    anchor = (await goal_service.get_read(goal.id)).recurrence.start_at
    for agent_id, finished in (
        (owner.id, anchor - timedelta(hours=1)),
        (other.id, anchor - timedelta(hours=2)),
        (owner.id, anchor - timedelta(days=8)),
    ):
        source = Task(agent_id=agent_id, label="Synthetic check", objective="<p>Check the fixture.</p>",
                      status=TaskStatus.SUCCESS, created_at=finished, updated_at=finished)
        source.set_execution_result(ExecutionResult(prompt="Synthetic check", success=True, result="Verified the fixture.", messages=[
            AIMessage(type="tool", tool_name="verify_fixture", content="Fixture verified. token=synthetic-test-value"),
        ]))
        db.add(source)
        await db.flush()
    recent, foreign, old = list(await db.scalars(select(Task.id).where(Task.label == "Synthetic check")
                                                 .order_by(Task.created_at.desc())))
    await db.commit()

    clock.now = anchor + timedelta(seconds=10)
    await calendar.materialize_due()
    assert await runner.start_due_cycle()
    passage = await calendar.agenda_window(owner.id, anchor - timedelta(minutes=1), anchor + timedelta(minutes=1))
    cycle = await db.scalar(select(GoalCycle).where(GoalCycle.goal_id == goal.id))
    assert passage.items[0].task_uri == f"galaris://task/{cycle.task_id}"
    review = await db.get(Task, cycle.task_id)
    assert review.forced_route == "EXEC"
    review.status = TaskStatus.EXEC
    await db.commit()

    names = {"goal_retrospective_evidence", "goal_retrospective_learn", "goal_retrospective_record"}
    assert {item.name for item in await list_enabled_native_mcp_definitions(
        owner.id, runtime="internal", allowed_tool_names=names, task_id=review.id,
    )} == names
    assert not await list_enabled_native_mcp_definitions(
        owner.id, runtime="internal", allowed_tool_names=names, task_id=recent,
    )

    async def call(name, **arguments):
        return await execute_native_mcp_tool(owner.id, runtime="internal", task_id=review.id,
                                             tool_name=name, arguments=arguments)

    summary = await call("goal_retrospective_evidence")
    recent_uri = f"galaris://task/{recent}"
    assert summary["sources"] == [{"task_uri": recent_uri, "status": "SUCCESS"}]
    original_start = summary["period_start"]
    current = await goal_service.get_read(goal.id)
    await goal_service.update(goal.id, GoalUpdate(expected_revision=current.revision,
        recurrence=current.recurrence.model_copy(update={"frequency": "DAILY", "interval": 2})))
    summary = await call("goal_retrospective_evidence")
    assert summary["period_start"] == original_start
    for hidden in (foreign, old, review.id):
        with pytest.raises(PermissionError, match="outside"):
            await retrospective.evidence(owner.id, review.id, f"galaris://task/{hidden}")
    observed = await call("goal_retrospective_evidence", source_task_uri=recent_uri)
    assert observed["learning_eligible"] is True
    tool = next(item for item in observed["observations"] if item["kind"] == "tool_result")
    assert "synthetic-test-value" not in tool["detail"]
    code = summary["skill_code_prefix"] + "verify-fixture"
    proposal = {
        "action": "CREATE", "code": code, "label": "Verify the fixture",
        "markdown": f"---\nname: {code}\ndescription: Verify the synthetic fixture.\n---\nRun the fixture check.\n",
        "evidence_refs": [tool["reference"]], "rationale": "The recorded check succeeded.",
        "confidence": 0.9,
    }
    with pytest.raises(ValueError, match="only references"):
        await retrospective.learn(owner.id, review.id, recent_uri, {**proposal, "evidence_refs": ["fabricated"]})
    assert (await call("goal_retrospective_learn", source_task_uri=recent_uri, operation=proposal))["changed"] == 1
    assert (await call("goal_retrospective_learn", source_task_uri=recent_uri, operation=proposal))["changed"] == 0
    package = await db.scalar(select(Skill).where(Skill.code == code))
    proof = (await db.scalars(select(SkillLearningEvidence).where(SkillLearningEvidence.skill_id == package.id))).one()
    assert package.owner_agent_id == owner.id and package.learning_evidence_count == 1
    assert proof.source_ref == recent_uri
    assert "Run the fixture check." in storage.read_text(code, "SKILL.md", owner_agent_id=owner.id)

    tracking = "<p>The fixture check succeeded. Verify reuse in the next cycle.</p>"
    recorded = await call("goal_retrospective_record", expected_revision=summary["goal_revision"], tracking_content=tracking)
    assert await call("goal_retrospective_record", expected_revision=summary["goal_revision"], tracking_content=tracking) == recorded
    assert (await goal_service.get_read(goal.id)).tracking_content == tracking
    review.status = TaskStatus.SUCCESS
    await db.commit()
    judge = AsyncMock(side_effect=AssertionError("The weekly objective has no completion decision."))
    monkeypatch.setattr(goal_service, "get_tracking_llm", judge)
    assert await runner.process_terminal_cycle()
    await db.refresh(cycle)
    assert cycle.verdict == GoalVerdict.CONTINUE
    assert (await goal_service.get_read(goal.id)).status == GoalStatus.ACTIVE
    judge.assert_not_awaited()

    next_passage = calendar.next_passage((await goal_service.get_read(goal.id)).recurrence, anchor, inclusive=False)
    clock.now = next_passage + timedelta(seconds=10)
    await calendar.materialize_due()
    assert await runner.start_due_cycle()
    next_cycle = await db.scalar(select(GoalCycle).where(GoalCycle.goal_id == goal.id, GoalCycle.sequence == 2))
    next_review = await db.get(Task, next_cycle.task_id)
    next_review.status = TaskStatus.EXEC
    await db.commit()
    next_summary = await retrospective.evidence(owner.id, next_review.id, None)
    assert next_summary["period_end"] == next_passage.isoformat()
    assert datetime.fromisoformat(str(next_summary["period_start"])) == anchor
    assert next_summary["sources"] == []
    assert (await goal_service.get_read(goal.id)).tracking_content == tracking


@pytest.mark.asyncio
async def test_pausing_each_goal_group_blocks_its_queued_manual_cycle_only(db, clock):
    owner = await _new_agent(db)
    self_learning_id = await retrospective.ensure_weekly_retrospective(owner.id, now=clock.now)
    await db.commit()
    learning = await goal_service.get_read(self_learning_id)
    regular = await create_goal(db)

    await settings_service.update_settings(GoalSettingsUpdate(self_learning_paused=True))
    queued_learning = await goal_service.run_now(learning.id, GoalCommand(expected_revision=learning.revision))
    queued_regular = await goal_service.run_now(regular.id, GoalCommand(expected_revision=regular.revision))
    assert queued_learning.next_cycle_at is None and queued_regular.next_cycle_at is not None
    assert await runner.start_due_cycle(manual_only=True)
    assert not await runner.start_due_cycle(manual_only=True)
    assert set(await db.scalars(select(GoalCycle.goal_id))) == {regular.id}

    paused = await settings_service.update_settings(GoalSettingsUpdate(goals_paused=True))
    assert paused.globally_paused and not await runner.start_due_cycle(manual_only=True)
    settings = await settings_service.update_settings(GoalSettingsUpdate(self_learning_paused=False))
    assert settings.goals_paused and not settings.globally_paused
    assert await runner.start_due_cycle(manual_only=True)
    assert set(await db.scalars(select(GoalCycle.goal_id))) == {regular.id, learning.id}
