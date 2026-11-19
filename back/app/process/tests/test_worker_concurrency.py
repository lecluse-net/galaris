"""Real independent transactions around the durable admission boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from core.database import get_db_session
from core.user.models import User
from app.agent.models import Agent, Title
from app.services.models import Service
from app.process.models import ProcessDefinition, ProcessRun, ProcessStartJob
from app.process.schemas import EngineRunSnapshot, EngineStartResult
from app.process import registry
from app.process.workers import EffectSlots, start_engine_jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("different_workflow", [False, True])
async def test_parallel_external_execution_discovery_creates_one_canonical_run(committed_database, monkeypatch, different_workflow):
    from app.process.process_service import resolve_engine_run

    code = f"discovery-{uuid4().hex[:8]}"
    async with get_db_session() as db:
        title = Title(label=code, gender="X")
        tool = Service(code=code, label=code, connection_schema={})
        user = User(email=f"{code}@example.test", hashed_password="unused", is_active=True)
        db.add_all([title, tool, user])
        await db.flush()
        agent = Agent(user_id=user.id, code=code, first_name="Discovery", last_name="Test", title_id=title.id)
        db.add(agent)
        await db.flush()
        db.add(ProcessDefinition(service_id=tool.id, agent_id=agent.id, engine_process_id=code, label=code))
        if different_workflow:
            db.add(ProcessDefinition(service_id=tool.id, agent_id=agent.id, engine_process_id=code + "-other", label="Other workflow"))

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
        tool = Service(code=code, label=code, connection_schema={})
        user = User(email=f"{code}@example.test", hashed_password="unused", is_active=True)
        db.add_all([title, tool, user]); await db.flush()
        agent = Agent(user_id=user.id, code=code, first_name="Worker", last_name="Test", title_id=title.id)
        db.add(agent); await db.flush()
        definition = ProcessDefinition(service_id=tool.id, agent_id=agent.id, engine_process_id=code, label=code)
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


@pytest.mark.asyncio
async def test_slow_effect_keeps_other_slots_available_on_later_ticks(committed_database):
    slow, first_fast, next_fast = [uuid4() for _ in range(3)]
    ready = [slow, first_fast]
    started = asyncio.Event()
    release = asyncio.Event()
    executed = []

    async def discover(limit, exclude):
        return [identity for identity in ready if identity not in exclude][:limit]

    async def execute(identity):
        executed.append(identity)
        ready.remove(identity)
        if identity == slow:
            started.set()
            await release.wait()

    slots = EffectSlots(discover, execute, capacity=2)
    try:
        async with get_db_session():
            await slots.tick()
        initial = slots.active[first_fast]
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.wait_for(initial, 5)
        ready.append(next_fast)
        async with get_db_session():
            await slots.tick()
        await asyncio.wait_for(slots.active[next_fast], 5)
        assert len(executed) == 3 and set(executed) == {slow, first_fast, next_fast}
        assert not release.is_set() and slow in slots.active
    finally:
        release.set()
        await slots.stop()


@pytest.mark.asyncio
async def test_dedicated_worker_restarts_and_consumes_a_durable_admission(committed_database, monkeypatch):
    from os import getpid
    from app.process import process_service
    from app.process.bpmn import Flow, Node, Workflow
    from app.process.models import ProcessNodeRun
    from app.process.native_definitions import create
    from app.process.values import Variable
    from core.runtime import RuntimeComponent, RuntimeSupervisor
    from scripts.process_worker import ProcessWorker

    async with get_db_session() as db:
        database_name = await db.scalar(select(func.current_database()))
        assert database_name.startswith("test_concurrency_")
        monkeypatch.setenv("POSTGRES_DB", database_name)
        title = Title(label="Synthetic worker recovery", gender="X")
        user = User(email="worker-recovery@example.test", hashed_password="synthetic", is_active=True)
        db.add_all([title, user])
        await db.flush()
        agent = Agent(user_id=user.id, code="worker-recovery", first_name="Synthetic", last_name="Worker", title_id=title.id)
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        definition = await create(actor_agent_id=agent.id, title="Synthetic worker recovery", graph=Workflow(
            schema_version="galaris.bpmn/v2", variables=[Variable(name="proof", type="int", nullable=False)],
            nodes=[Node(id="start", kind="start"), Node(id="compute", kind="code", outputs=["proof"],
                config={"dataset_code": True, "code": "return {'proof': 7}"}),
                Node(id="end", kind="end", outputs=["proof"])],
            flows=[Flow(id="admit", source="start", target="compute"), Flow(id="finish", source="compute", target="end")],
        ))
        code = definition.code

    worker = ProcessWorker()
    supervisor = RuntimeSupervisor(monitor_interval=.1, jitter=lambda delay: delay)
    supervisor.configure((RuntimeComponent(
        name="process_worker", start=worker.start, stop=worker.stop, is_running=worker.is_running,
        start_timeout=30, stop_timeout=20, restart_initial_delay=.1, restart_max_delay=1,
    ),))
    try:
        await supervisor.start()
        assert worker.is_running() and worker.process.pid != getpid()
        previous = worker.process
        previous.kill()
        await previous.wait()
        async with get_db_session():
            admitted = await process_service.start_process(agent_id=agent_id, workflow_id=code, input_data={})
        async with asyncio.timeout(30):
            while True:
                async with get_db_session():
                    run = await process_service.get_run_detail(admitted.run_id, refresh_if_stale=True)
                if run.status in process_service.TERMINAL_STATUSES:
                    break
                await asyncio.sleep(.1)
        assert worker.is_running() and worker.process.pid != previous.pid
        assert run.status == "success" and run.output == {"proof": {"type": "int", "value": 7}}
        async with get_db_session() as db:
            assert await db.scalar(select(func.count()).select_from(ProcessNodeRun).where(
                ProcessNodeRun.run_id == run.id, ProcessNodeRun.node_key == "compute")) == 1
    finally:
        await supervisor.stop()
