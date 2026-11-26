"""Simultaneous native toolset starts and a separate interactive stop, on PostgreSQL."""

import asyncio
import gc
from contextvars import ContextVar
from math import ceil
from statistics import median
from time import perf_counter

from httpx import ASGITransport, AsyncClient
from pydantic_ai import Agent as StreamingAgent
from pydantic_ai.models.function import FunctionModel
import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import Connection
from app.harness.mcp_toolset import build_agent_mcp_toolset, build_conversation_toolset
from app.services import ServiceModel, mcp_loader
from app.task import Task, TaskStatus
from core import settings
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session, middleware
from core.user import UserModel
from core.user.user_service import encrypt_password
from main import app


@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_count", "mount_limit", "conversation_slots"), [
    (1, 4, None), (8, 4, None), (30, 30, None), (30, 4, None), (50, 4, None), (50, 50, None),
    (30, 4, 30), (30, 4, 4), (30, 4, 8),
    (50, 4, 50), (50, 4, 4), (50, 4, 8), (50, 4, 12),
])
async def test_first_text_and_durable_stop_during_parallel_toolset_starts(
    committed_database, monkeypatch, agent_count, mount_limit, conversation_slots,
):
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    monkeypatch.setattr(settings, "AGENT_MCP_MOUNT_CONCURRENCY", mount_limit)
    if conversation_slots:
        monkeypatch.setattr(settings, "AGENT_MCP_CONVERSATION_MOUNT_CONCURRENCY", conversation_slots)
    owner_count = agent_count if agent_count >= 30 else 1
    credentials = {"email": "startup@example.com", "password": "Synthetic-startup-42!"}
    stop_offsets = (0.0, 0.15) if agent_count >= 30 else (0.0,)
    async with get_db_session() as db:
        password_hash = encrypt_password(credentials["password"])
        owners = [UserModel(email=credentials["email"] if index == 0 else f"startup-{index}@example.com",
                            hashed_password=password_hash, is_active=True) for index in range(owner_count)]
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "TASK_EDIT"))
        role = Role(code="startup-editor", privileges=[privilege])
        title = Title(label="Synthetic startup", gender="X")
        db.add_all([*owners, role, title])
        await db.flush()
        db.add_all(Assignment(user_id=owner.id, role_id=role.id, is_default=True) for owner in owners)
        services = (await db.scalars(select(ServiceModel.id).where(
            ServiceModel.code.in_(("document", "file_sharing", "process"))))).all()
        assert len(services) == 3
        agents = [Agent(code=f"startup-{i}", user_id=owners[i % owner_count].id, title_id=title.id,
            first_name="Synthetic", last_name=str(i), agent_driver="internal") for i in range(agent_count)]
        db.add_all(agents)
        await db.flush()
        db.add_all(Connection(agent_id=agent.id, service_id=service, active=True)
                   for agent in agents for service in services)
        tasks = [Task(label=f"Synthetic startup {i}", agent_id=agents[i % agent_count].id,
            status=TaskStatus.EXEC) for i in range(max(8, agent_count))]
        controls = [Task(label=f"Separate interactive stop {i}", agent_id=agents[0].id,
            status=TaskStatus.EXEC) for i in range(3 * len(stop_offsets))]
        db.add_all([*tasks, *controls])
        await db.flush()

    start = asyncio.Barrier(len(tasks) + len(stop_offsets))
    # The request's ASGI tasks inherit this marker. Measure acquisition
    # locally on this test's pool, including time to open a new connection.
    stop_acquisitions = ContextVar("startup_probe_acquisitions", default=None)
    pool = committed_database.kw["bind"].sync_engine.pool
    connect = pool.connect

    def measured_connect():
        before = perf_counter()
        try:
            return connect()
        finally:
            samples = stop_acquisitions.get()
            if samples is not None:
                samples.append(perf_counter() - before)

    monkeypatch.setattr(pool, "connect", measured_connect)

    async def stream_task(task, conversation):
        await start.wait()
        since = perf_counter()
        async with get_db_session():
            if conversation:
                tools, inventory = await build_conversation_toolset(task.agent_id, resources={})
                assert "file_list" in inventory.tool_names
            else:
                tools = await build_agent_mcp_toolset(task.agent_id, task_id=task.id)
        mount_seconds = perf_counter() - since

        async def synthetic_stream(_messages, info):
            names = {tool.name for tool in info.function_tools}
            assert "file_list" in names
            if not conversation:
                assert "process_analyze_run" in names
            await asyncio.sleep(0.02)
            yield "Synthetic reply"

        agent = StreamingAgent(FunctionModel(stream_function=synthetic_stream), toolsets=[tools])
        first = None
        output = ""
        async with agent.run_stream("Produce the synthetic reply") as result:
            async for part in result.stream_text(delta=True, debounce_by=None):
                if part and first is None:
                    first = perf_counter() - since
                output += part
        assert output == "Synthetic reply" and first is not None
        return mount_seconds, first

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
        login = await http.post("/api/auth/login-json", json=credentials)
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        async def stop(stop_target, offset):
            await start.wait()
            due = perf_counter() + offset
            if offset:
                await asyncio.sleep(offset)
            samples = []
            token = stop_acquisitions.set(samples)
            try:
                response = await http.post(f"/api/tasks/{stop_target.id}/cancel", headers=headers,
                    json={"expected_revision": stop_target.revision})
            finally:
                stop_acquisitions.reset(token)
            finished = perf_counter()
            assert samples
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "ERROR"
            return due, finished, sum(samples)

        for wave in range(3):
            initial_misses = mcp_loader._native_tool_template.cache_info().misses
            loop = asyncio.get_running_loop()
            loop_lags = []
            tick_seconds = 0.01
            gc_pauses = []
            gc_start = 0.0

            def sample_gc(phase, _info):
                nonlocal gc_start
                if phase == "start":
                    gc_start = perf_counter()
                elif gc_start:
                    gc_pauses.append((gc_start, perf_counter()))
                    gc_start = 0.0

            def sample_loop(due):
                nonlocal timer
                now = loop.time()
                loop_lags.append(max(0, now - due))
                timer = loop.call_at(now + tick_seconds, sample_loop, now + tick_seconds)

            due = loop.time() + tick_seconds
            timer = loop.call_at(due, sample_loop, due)
            gc.callbacks.append(sample_gc)
            try:
                async with asyncio.timeout(60), asyncio.TaskGroup() as group:
                    streams = [group.create_task(stream_task(task, conversation_slots is not None and index % 2 == 0))
                               for index, task in enumerate(tasks)]
                    commands = [group.create_task(stop(controls[wave * len(stop_offsets) + i], offset))
                                for i, offset in enumerate(stop_offsets)]
            finally:
                gc.callbacks.remove(sample_gc)
                timer.cancel()
            mounts, first_text = zip(*(stream.result() for stream in streams))
            assert loop_lags
            compiled = mcp_loader._native_tool_template.cache_info().misses - initial_misses
            first_text_p95 = sorted(first_text)[ceil(0.95 * len(first_text)) - 1]
            stop_timings = []
            for offset, command in zip(stop_offsets, commands):
                due, finished, acquisition = command.result()
                overlap = sum(max(0, min(end, finished) - max(begin, due)) for begin, end in gc_pauses)
                prefix = f"stop_{int(offset * 1000)}"
                stop_timings.append(f"{prefix}_http_ms={1000 * (finished - due):.1f} "
                                    f"{prefix}_pool_ms={1000 * acquisition:.1f} "
                                    f"{prefix}_gc_ms={1000 * overlap:.1f}")
            print(f"STARTUP agents={agent_count} owners={owner_count} limit={mount_limit} conversation_slots={conversation_slots} wave={wave + 1} "
                  f"compiled_native_tools={compiled} "
                  f"mount_median_ms={1000 * median(mounts):.1f} "
                  f"after_mount_median_ms={1000 * median(t - m for t, m in zip(first_text, mounts)):.1f} "
                  f"loop_lag_max_ms={1000 * max(loop_lags):.1f} "
                  f"first_text_median_ms={1000 * median(first_text):.1f} "
                  f"first_text_p95_ms={1000 * first_text_p95:.1f} "
                  f"first_text_max_ms={1000 * max(first_text):.1f} {' '.join(stop_timings)}")
    async with get_db_session() as db:
        for target in controls:
            assert (await db.get(Task, target.id)).status == TaskStatus.ERROR


@pytest.mark.asyncio
async def test_queued_mount_observes_revocation_after_cancel_and_failure(committed_database, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MCP_MOUNT_CONCURRENCY", 1)
    async with get_db_session() as db:
        owner = UserModel(email="catalog-owner@example.com", hashed_password="unused")
        title = Title(label="Catalog admission", gender="X")
        db.add_all([owner, title])
        await db.flush()
        agent = Agent(user_id=owner.id, title_id=title.id, code="catalog-admission",
                      first_name="Catalog", last_name="Admission", agent_driver="internal")
        db.add(agent)
        await db.flush()
        service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "process"))
        connection = Connection(agent_id=agent.id, service_id=service_id, active=True)
        db.add(connection)
        await db.flush()

    scenario = ContextVar("mount_request")
    holding = asyncio.Event()
    queued = asyncio.Event()
    entered = []
    read_bindings = mcp_loader.active_service_bindings

    async def read(agent_id):
        label = scenario.get()
        entered.append(label)
        bindings = await read_bindings(agent_id)
        if label == "holder":
            holding.set()
            await asyncio.Future()
        if label == "failure":
            raise RuntimeError("synthetic mount failure")
        return bindings

    monkeypatch.setattr(mcp_loader, "active_service_bindings", read)

    async def mount(label):
        scenario.set(label)
        if label == "withdrawn":
            queued.set()
        return await build_agent_mcp_toolset(agent.id)

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        holder = group.create_task(mount("holder"))
        await holding.wait()
        withdrawn = group.create_task(mount("withdrawn"))
        await queued.wait()
        # A concurrent operator can still acquire a connection to revoke access.
        async with get_db_session() as db:
            (await db.get(Connection, connection.id)).active = False
        assert entered == ["holder"]
        withdrawn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await withdrawn

        async def failing_mount():
            with pytest.raises(RuntimeError, match="synthetic mount failure"):
                await mount("failure")

        group.create_task(failing_mount())
        following = group.create_task(mount("following"))
        holder.cancel()
    assert entered == ["holder", "failure", "following"]
    scenario.set("discovery")
    async with following.result() as toolset:
        assert "process_analyze_run" not in {tool.name for tool in await toolset.list_tools()}

    # Explicit callers can inspect an uncommitted change without publishing it.
    async with get_db_session() as db:
        (await db.get(Connection, connection.id)).active = True
        await db.flush()
        local = await build_agent_mcp_toolset(agent.id)
        async with local:
            assert "process_analyze_run" in {tool.name for tool in await local.list_tools()}
        await db.rollback()
    async with get_db_session() as db:
        assert not (await db.get(Connection, connection.id)).active
