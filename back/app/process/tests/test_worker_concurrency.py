"""Real independent transactions around the durable admission boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from core.database import get_db_session
from core.user.models import User
from app.agent.models import Agent, Title
from app.tools.models import Tool
from app.process.models import ProcessDefinition, ProcessRun, ProcessStartJob
from app.process.schemas import EngineRunSnapshot, EngineStartResult
from app.process import registry
from app.process.workers import start_engine_jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("different_workflow", [False, True])
async def test_parallel_external_execution_discovery_creates_one_canonical_run(committed_database, monkeypatch, different_workflow):
    from app.process.process_service import resolve_engine_run

    code = f"discovery-{uuid4().hex[:8]}"
    async with get_db_session() as db:
        title = Title(label=code, gender="X")
        tool = Tool(code=code, label=code, connection_schema={})
        user = User(email=f"{code}@example.test", hashed_password="unused", is_active=True)
        db.add_all([title, tool, user])
        await db.flush()
        agent = Agent(user_id=user.id, code=code, first_name="Discovery", last_name="Test", title_id=title.id)
        db.add(agent)
        await db.flush()
        db.add(ProcessDefinition(tool_id=tool.id, agent_id=agent.id, engine_process_id=code, label=code))
        if different_workflow:
            db.add(ProcessDefinition(tool_id=tool.id, agent_id=agent.id, engine_process_id=code + "-other", label="Other workflow"))

    arrivals = 0
    both_read = asyncio.Event()
    async def observe(reference):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), 5)
        return EngineRunSnapshot(status="success", output={"receipt": "remote"}, raw={"workflowId": reference.correlation_id.split(":")[1]})
    monkeypatch.setitem(registry._engines, code, SimpleNamespace(get_run=observe))
    async def discover(workflow):
        async with get_db_session():
            return (await resolve_engine_run(workflow, "remote-execution")).id

    found = await asyncio.gather(discover(code), discover(code + "-other" if different_workflow else code), return_exceptions=True)
    if different_workflow:
        assert sum(isinstance(result, PermissionError) for result in found) == 1
        assert sum(not isinstance(result, BaseException) for result in found) == 1
    else:
        assert not any(isinstance(result, BaseException) for result in found)
        assert found[0] == found[1]
    async with get_db_session() as db:
        rows = list(await db.scalars(select(ProcessRun).where(ProcessRun.engine_code == code)))
        assert len(rows) == 1 and rows[0].status == "success"
        assert rows[0].output == {"receipt": "remote"}


@pytest.mark.asyncio
async def test_slow_admission_does_not_block_other_run_and_parallel_worker_cannot_resubmit(committed_database, monkeypatch):
    slow_started, release, fast_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    admitted = []
    code = f"test-{uuid4().hex[:8]}"
    async with get_db_session() as db:
        title = Title(label=code, gender="X")
        tool = Tool(code=code, label=code, connection_schema={})
        user = User(email=f"{code}@example.test", hashed_password="unused", is_active=True)
        db.add_all([title, tool, user]); await db.flush()
        agent = Agent(user_id=user.id, code=code, first_name="Worker", last_name="Test", title_id=title.id)
        db.add(agent); await db.flush()
        definition = ProcessDefinition(tool_id=tool.id, agent_id=agent.id, engine_process_id=code, label=code)
        db.add(definition); await db.flush()
        runs = [ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code=code,
            correlation_id=uuid4().hex, callback_token="token", status="queued", launch_snapshot={"input": {}}) for _ in range(2)]
        db.add_all(runs); await db.flush()
        ids = [run.id for run in runs]
        db.add_all([ProcessStartJob(run_id=run.id) for run in runs])

    async def submit(_workflow, reference, _payload):
        admitted.append(reference.id)
        if reference.id == ids[0]:
            slow_started.set()
            await release.wait()
        else:
            fast_done.set()
        return EngineStartResult(accepted=True, engine_run_id=str(reference.id))

    engine = SimpleNamespace(code=code, start_run=submit, prepare_input=AsyncMock(),
        start_timeout_seconds=660, refresh_timeout_seconds=660)
    monkeypatch.setitem(registry._engines, code, engine)
    async def worker():
        async with get_db_session():
            return await start_engine_jobs(code)
    running = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(slow_started.wait(), 5)
        await asyncio.wait_for(fast_done.wait(), 5)
        # The still-running admission is committed and its lease uses the
        # engine's 660-second bound, not the generic short start timeout.
        async with get_db_session() as db:
            from datetime import datetime, timedelta, timezone
            job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == ids[0]))
            job.locked_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        assert await worker() == 0
    finally:
        release.set()
        await running
    assert sorted(admitted) == sorted(ids)
    async with get_db_session() as db:
        assert set(await db.scalars(select(ProcessRun.status).where(ProcessRun.id.in_(ids)))) == {"running"}
