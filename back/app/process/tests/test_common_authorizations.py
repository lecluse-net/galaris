"""A real MCP agreement survives admission, but never authorizes a second effect."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastmcp import Client
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent import Agent, Title
from app.connection import Connection
from app.process import process_service as service
from app.process.engine import ProcessEngineError
from app.process.models import ProcessDefinition, ProcessRun, ProcessStartJob
from app.process.schemas import EngineRunSnapshot, EngineStartResult, ProcessCallbackEvent
from app.task import task_service
from app.task.models import Task, TaskStatus
from app.tools import ToolModel, build_agent_galaris_fastmcp
from app.tools.authorization import AuthorizationClosed, answer_action
from app.tools.authorization_models import ActionAuthorization
from core.database import get_db_session
from core.user import UserModel
from core.util import BufferedAdmissionDeferred


@pytest_asyncio.fixture
async def governed_process(committed_database, monkeypatch):
    code = f"approval-process-{uuid4().hex}"
    async with get_db_session() as db:
        user = UserModel(email=f"{code}@example.test", hashed_password="synthetic")
        title = Title(label=code, gender="X")
        remote = ToolModel(code=code, label="Synthetic process engine", connection_schema={})
        db.add_all([user, title, remote])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=code,
                      first_name="Process", last_name="Approval")
        db.add(agent)
        await db.flush()
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
        connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
        task = Task(agent_id=agent.id, label="Synthetic workflow", status=TaskStatus.EXEC,
                    objective="<p>Prepare the approved result.</p>")
        definition = ProcessDefinition(agent_id=agent.id, tool_id=remote.id,
                                       engine_process_id="approved-workflow", label="Approved workflow")
        db.add_all([connection, task, definition])
        await db.flush()
        fixture = SimpleNamespace(agent_id=agent.id, connection_id=connection.id,
                                  task_id=task.id, definition_id=definition.id)
    engine = SimpleNamespace(
        start_timeout_seconds=5, refresh_timeout_seconds=5,
        prepare_input=AsyncMock(side_effect=lambda _agent, _workflow, payload: payload),
        start_run=AsyncMock(return_value=EngineStartResult(accepted=True, engine_run_id="accepted-remote")),
        get_run=AsyncMock(return_value=EngineRunSnapshot(status="success", output={"receipt": "durable"})),
    )
    monkeypatch.setitem(service.registry._engines, code, engine)
    async with get_db_session():
        fixture.server = await build_agent_galaris_fastmcp(fixture.agent_id,
            allowed_tool_names={"process_start"}, task_id=fixture.task_id)
    fixture.engine = engine
    return fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "changed_definition", "revoked_connection",
                                     "lost_response", "buffered", "paused"])
async def test_process_worker_revalidates_and_consumes_exact_mcp_agreement(governed_process, scenario):
    fixture = governed_process
    arguments = {"workflow_id": "approved-workflow", "input": {"period": "synthetic"}}
    async with Client(fixture.server) as client:
        pending = await client.call_tool("process_start", arguments, raise_on_error=False)
        control = pending.meta["galaris.authorization/v1"]
        identifier = UUID(control["request_id"])
        fixture.engine.start_run.assert_not_awaited()
        async with get_db_session() as db:
            assert not list(await db.scalars(select(ProcessRun).where(ProcessRun.launcher_agent_id == fixture.agent_id)))
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        meta = {"galaris.authorization/v1": {"continuation": control["continuation"]}}
        admitted = await client.call_tool("process_start", arguments, meta=meta, raise_on_error=False)
        assert not admitted.is_error
        async with get_db_session() as db:
            run = await db.scalar(select(ProcessRun).where(ProcessRun.launcher_agent_id == fixture.agent_id))
            run_id, callback_token = run.id, run.callback_token
            assert run.launch_snapshot["authorization_permit"] == str(identifier)
            assert await service.refresh_run(run_id) is run
            fixture.engine.get_run.assert_not_awaited()
            if scenario == "changed_definition":
                (await db.get(ProcessDefinition, fixture.definition_id)).engine_process_id = "different-workflow"
            elif scenario == "revoked_connection":
                (await db.get(Connection, fixture.connection_id)).active = False
            elif scenario == "paused":
                task_service.suspend(await db.get(Task, fixture.task_id), task_service.PAUSE_USER)
            else:
                # A durable continuation remains authorized after its launching Task finishes.
                (await db.get(Task, fixture.task_id)).status = TaskStatus.SUCCESS
        if scenario == "lost_response":
            fixture.engine.start_run.side_effect = TimeoutError("Accepted start reply lost")
        elif scenario == "buffered":
            fixture.engine.start_run.side_effect = [BufferedAdmissionDeferred("No effect admitted"),
                EngineStartResult(accepted=True, engine_run_id="accepted-remote")]
        async with get_db_session():
            assert await service.process_start_jobs(batch_size=1) == 1
        if scenario in {"buffered", "paused"}:
            async with get_db_session() as db:
                row = await db.get(ActionAuthorization, identifier)
                job = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run_id))
                assert row.status == "executing" and row.dispatch_claimed_at is None
                assert job.attempts == 0 and job.locked_at is None
                task_service.release(await db.get(Task, fixture.task_id), task_service.PAUSE_USER)
                job.available_at = datetime.now(timezone.utc)
            async with get_db_session():
                assert await service.process_start_jobs(batch_size=1) == 1
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            run = await db.get(ProcessRun, run_id)
            if scenario in {"changed_definition", "revoked_connection"}:
                fixture.engine.start_run.assert_not_awaited()
                assert run.status == "error" and run.error_code == "authorization_invalidated"
            elif scenario == "lost_response":
                assert run.status == "unknown" and row.status == "outcome_unknown"
                await service.receive_callback(run_id, callback_token, ProcessCallbackEvent(
                    event_id="authoritative-completion", status="success", engine_run_id="accepted-remote",
                    output={"receipt": "durable"}))
            else:
                assert run.status == "running" and row.status == "completed"
                task = await db.get(Task, fixture.task_id)
                task_service.suspend(task, task_service.PAUSE_USER)
                await db.commit()
                assert (await service.refresh_run(run_id)).status == "running"
                fixture.engine.get_run.assert_not_awaited()
                task_service.release(task, task_service.PAUSE_USER)
                await db.commit()
                assert (await service.refresh_run(run_id)).status == "success"
            await db.refresh(row)
            if scenario not in {"changed_definition", "revoked_connection"}:
                assert row.status == "completed"
                assert fixture.engine.start_run.await_count == (2 if scenario == "buffered" else 1)
            assert await service.process_start_jobs(batch_size=1) == 0
        replay = await client.call_tool("process_start", arguments, meta=meta, raise_on_error=False)
        assert replay.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_callback", [False, True])
async def test_process_refresh_revocation_preserves_authoritative_completion(governed_process, terminal_callback):
    fixture = governed_process
    arguments = {"workflow_id": "approved-workflow", "input": {"period": "synthetic"}}
    async with Client(fixture.server) as client:
        pending = await client.call_tool("process_start", arguments, raise_on_error=False)
        control = pending.meta["galaris.authorization/v1"]
        identifier = UUID(control["request_id"])
        async with get_db_session() as db:
            row = await db.get(ActionAuthorization, identifier)
            assert await answer_action(identifier, user_id=row.approver_user_id, approved=True)
        assert not (await client.call_tool("process_start", arguments, raise_on_error=False,
            meta={"galaris.authorization/v1": {"continuation": control["continuation"]}})).is_error
    async with get_db_session() as db:
        assert await service.process_start_jobs(batch_size=1) == 1
        run = await db.scalar(select(ProcessRun).where(ProcessRun.launcher_agent_id == fixture.agent_id))
        run_id, token = run.id, run.callback_token
        if not terminal_callback:
            (await db.get(Connection, fixture.connection_id)).active = False
    if terminal_callback:
        async def complete_then_report_revoked(_reference):
            await service.receive_callback(run_id, token, ProcessCallbackEvent(
                event_id="completion-before-revoked-observation", status="success",
                output={"receipt": "authoritative"}))
            raise AuthorizationClosed(identifier, "invalidated")
        fixture.engine.get_run.side_effect = complete_then_report_revoked
    async with get_db_session():
        with pytest.raises(ProcessEngineError, match="authorization was revoked"):
            await service.refresh_run(run_id)
    async with get_db_session() as db:
        run = await db.get(ProcessRun, run_id)
        assert run.status == ("success" if terminal_callback else "error")
        if terminal_callback:
            assert run.output == {"receipt": "authoritative"} and run.error_code is None
        else:
            assert run.error_code == "authorization_invalidated"
            fixture.engine.get_run.assert_not_awaited()
        fixture.engine.start_run.assert_awaited_once()
