"""Removed technical workflows are purged without touching business processes."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.process.dbadmin import _purge_avatar_processes, _purge_catalog_refresh_processes
from app.process.models import ProcessDefinition, ProcessRun, ProcessRunEvent, ProcessStartJob
from app.process.tests.test_recovery import waiting_run
from app.task.models import TaskStatus
from app.tools import ToolModel


@pytest.mark.asyncio
@pytest.mark.parametrize("archived_definition", [False, True])
@pytest.mark.parametrize("tool_code,operation,purge", [
    ("agent_admin", "avatar", _purge_avatar_processes),
    ("tool_admin", "catalog_refresh", _purge_catalog_refresh_processes),
])
async def test_technical_purge_removes_history_and_jobs_wakes_waiter_and_preserves_other_workflows(
        db, waiting_run, archived_definition, tool_code, operation, purge):
    run, parent, child = waiting_run
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == tool_code))
    definition = await db.get(ProcessDefinition, run.process_id)
    definition.tool_id = tool.id
    definition.engine_process_id = f"{tool_code}:{run.launcher_agent_id}:{operation}"
    if archived_definition:
        definition.deleted_at = datetime.now(timezone.utc)
    run.engine_code = tool_code
    definition_id, run_id, agent_id = definition.id, run.id, run.launcher_agent_id
    unrelated = ProcessDefinition(agent_id=agent_id, tool_id=tool.id,
        engine_process_id="synthetic-business-workflow", label="Synthetic business workflow")
    db.add(unrelated)
    await db.flush()
    other_run = ProcessRun(process_id=unrelated.id, launcher_agent_id=agent_id, engine_code="fake",
        correlation_id=uuid4().hex, callback_token=uuid4().hex, status="success", output={"kept": True})
    archived = ProcessRun(process_id=definition_id, launcher_agent_id=agent_id, engine_code=tool_code,
        correlation_id=uuid4().hex, callback_token=uuid4().hex, status="success",
        deleted_at=datetime.now(timezone.utc))
    db.add_all([other_run, archived, ProcessStartJob(run_id=run_id),
                ProcessRunEvent(run_id=run_id, source="test", event_type="synthetic", payload={})])
    await db.commit()
    other_run_id, unrelated_id = other_run.id, unrelated.id
    await purge(db)
    await db.commit()
    await db.refresh(parent)
    await db.refresh(child)
    assert not parent.paused and child.status == TaskStatus.ERROR
    assert await db.scalar(select(func.count()).select_from(ProcessDefinition).where(
        ProcessDefinition.id == definition_id).execution_options(include_historized=True)) == 0
    assert await db.scalar(select(func.count()).select_from(ProcessRun).where(
        ProcessRun.process_id == definition_id).execution_options(include_historized=True)) == 0
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob).where(ProcessStartJob.run_id == run_id)) == 0
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.run_id == run_id)) == 0
    await db.refresh(other_run)
    assert other_run.id == other_run_id and other_run.output == {"kept": True}
    assert (await db.get(ProcessDefinition, unrelated_id)).engine_process_id == "synthetic-business-workflow"
    await purge(db)
    await db.commit()
    await db.refresh(other_run)
    assert other_run.status == "success"
