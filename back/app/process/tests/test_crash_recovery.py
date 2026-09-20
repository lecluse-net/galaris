"""Real commits and SIGKILL at the boundary between a result and its acknowledgment."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import sys
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agent.models import Agent, Title
from app.process.models import ProcessDefinition, ProcessRun, ProcessRunEvent, ProcessStartJob
from app.task import collab, runner
from app.task.models import Task, TaskStatus
from app.tools.models import Tool
from core.database import get_db_session
from core.user.models import User


async def run_worker(factory, mode, run_id, receipt, crash):
    database = factory.kw["bind"].url.database
    worker = await asyncio.create_subprocess_exec(
        sys.executable, "tests/process_crash_worker.py", mode, str(run_id), str(receipt), crash,
        env={**os.environ, "POSTGRES_DB": database},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(worker.communicate(), 45)
    finally:
        if worker.returncode is None:
            worker.kill()
            await worker.communicate()
    assert worker.returncode == (-signal.SIGKILL if crash == "crash" else 0), (stdout.decode(), stderr.decode())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["callback", "admission"])
async def test_worker_crash_preserves_committed_result_and_external_identity(committed_database, monkeypatch, tmp_path, mode):
    monkeypatch.setattr(runner, "go_next", lambda *args, **kwargs: None)
    code = uuid4().hex
    async with get_db_session() as db:
        user = User(email=f"crash-{code}@example.test", hashed_password="unused")
        title = Title(label=code, gender="X")
        tool = Tool(code=code, label=code, connection_schema={})
        db.add_all([user, title, tool])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=code, first_name="Crash", last_name="Test")
        db.add(agent)
        await db.flush()
        definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id, engine_process_id=code, label=code)
        parent = Task(label="Waiting for receipt", agent_id=agent.id, status=TaskStatus.DISPATCH,
                      paused=True, data={"pause_reasons": ["await"]})
        db.add_all([definition, parent])
        await db.flush()
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code="crash-test",
                         correlation_id=code, callback_token="token", status="running" if mode == "callback" else "queued",
                         launch_snapshot={"workflow_id": code}, task_id=parent.id)
        db.add(run)
        await db.flush()
        run_id, parent_id = run.id, parent.id
        if mode == "admission":
            db.add(ProcessStartJob(run_id=run_id))
        await db.commit()
        child = await collab.dispatch_process_wait(parent=parent, run_id=run_id, process_label=code, timeout_seconds=600)
        run.await_task_id = child.id
        child_id = child.id

    receipt = tmp_path / "provider-ledger.json"
    await run_worker(committed_database, mode, run_id, receipt, "crash")
    async with get_db_session() as db:
        run = await db.get(ProcessRun, run_id)
        assert run.await_resolved_at is None
        assert (await db.get(Task, parent_id)).paused
        if mode == "callback":
            assert run.status == "success" and run.output == {"receipt": "kept"}
            assert (await db.get(Task, child_id)).status != TaskStatus.SUCCESS
        else:
            assert run.status == "queued" and run.engine_run_id is None
            ledger = json.loads(receipt.read_text())
            assert ledger == {"requests": [code], "effects": {code: "remote-effect"}}
            job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run_id))
            assert job.attempts == 1 and job.locked_at is not None
            # Advance the durable lease beyond expiry, without sleeping in the test.
            job.locked_at = datetime.now(timezone.utc) - timedelta(days=1)
    await run_worker(committed_database, mode, run_id, receipt, "resume")
    async with get_db_session() as db:
        run = await db.get(ProcessRun, run_id)
        if mode == "callback":
            assert run.status == "success" and run.output == {"receipt": "kept"}
            assert run.await_resolved_at is not None
            assert (await db.get(Task, child_id)).status == TaskStatus.SUCCESS
            assert not (await db.get(Task, parent_id)).paused
            assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(
                ProcessRunEvent.run_id == run_id, ProcessRunEvent.event_id == "durable-completion")) == 1
        else:
            assert run.status == "running" and run.engine_run_id == "remote-effect"
            ledger = json.loads(receipt.read_text())
            assert ledger["requests"] == [code, code]
            assert ledger["effects"] == {code: "remote-effect"}
            job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run_id))
            assert job.status == "done" and job.attempts == 2
