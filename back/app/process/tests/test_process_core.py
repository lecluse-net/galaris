from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.llm import resolve_runtime_process_run_id
from app.llm.trace import extract_process_context
from app.process import (
    list_process_resources,
    process_service,
    read_process_resource,
)
from app.process.engine import ProcessEngineError
from app.process.models import ProcessDefinition, ProcessRun, ProcessStartJob
from app.process.process_service import can_transition
from app.process.sanitizer import sanitize
from app.process.schemas import (
    EngineError,
    EngineRunSnapshot,
    ProcessDefinitionCreate,
    ProcessDefinitionUpdate,
    ProcessFileInput,
    ProcessLLMCallRead,
)
from app.tools.models import Tool


def test_transition_matrix_is_monotonic() -> None:
    assert can_transition("queued", "running")
    assert can_transition("queued", "success")
    assert can_transition("waiting", "running")
    assert not can_transition("success", "running")
    assert not can_transition("error", "success")
    assert not can_transition("cancelled", "running")


def test_definition_update_accepts_administrative_assignment_fields() -> None:
    update = ProcessDefinitionUpdate(
        agent_id=2,
        tool_id=3,
        engine_process_id="workflow-2",
        label="Updated workflow",
        description="New text",
    )

    assert update.model_dump(exclude_unset=True) == {
        "agent_id": 2,
        "tool_id": 3,
        "engine_process_id": "workflow-2",
        "label": "Updated workflow",
        "description": "New text",
    }
    with pytest.raises(ValidationError):
        ProcessDefinitionUpdate.model_validate({"unsupported": True})


def test_definition_stores_generic_engine_process_id() -> None:
    definition = ProcessDefinitionCreate(
        agent_id=1,
        tool_id=2,
        engine_process_id="Kw70xUO8uRWkXvtX",
        label="Weather",
    )

    assert definition.engine_process_id == "Kw70xUO8uRWkXvtX"


def test_process_llm_call_projects_detailed_token_usage() -> None:
    call = ProcessLLMCallRead.model_validate(
        SimpleNamespace(
            id=uuid4(),
            task_id=None,
            purpose="process.exec",
            provider_name="openai",
            requested_model="gpt-5",
            effective_model="gpt-5",
            status="completed",
            duration=1.5,
            input_tokens=120,
            cache_read_tokens=80,
            output_tokens=45,
            total_tokens=165,
            cost=0.01,
            error=None,
            started_at=datetime.now(timezone.utc),
        )
    )

    assert call.input_tokens == 120
    assert call.cache_read_tokens == 80
    assert call.output_tokens == 45
    assert call.purpose == "process.exec"


@pytest.mark.asyncio
async def test_definition_can_be_reassigned_without_leaking_between_agents(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Process admin {suffix}", gender="X")
    db.add(title)
    await db.flush()
    first = Agent(
        title_id=title.id,
        code=f"process-first-{suffix}",
        first_name="First",
        last_name="Agent",
        agent_driver="internal",
    )
    second = Agent(
        title_id=title.id,
        code=f"process-second-{suffix}",
        first_name="Second",
        last_name="Agent",
        agent_driver="internal",
    )
    engine_tool = Tool(
        code="fake",
        label="Fake process engine",
        description="",
        connection_schema={},
    )
    db.add_all([first, second, engine_tool])
    await db.flush()

    definition = await process_service.create_definition(
        ProcessDefinitionCreate(
            agent_id=first.id,
            tool_id=engine_tool.id,
            engine_process_id=f"workflow-{suffix}",
            label="Original workflow",
            description="Original description",
        )
    )

    assert [item["workflow_id"] for item in await process_service.list_for_agent(first.id)] == [
        f"workflow-{suffix}"
    ]
    assert await process_service.list_for_agent(second.id) == []
    projected = await read_process_resource(
        f"workflow-{suffix}",
        actor_agent_id=first.id,
    )
    assert projected is not None
    assert projected["tool_code"] == "fake"
    assert isinstance(projected["created_at"], str)
    assert await read_process_resource(
        f"workflow-{suffix}",
        actor_agent_id=second.id,
    ) is None
    assert [
        item["workflow_id"]
        for item in await list_process_resources(
            actor_agent_id=first.id,
            query="Original",
            offset=0,
            limit=1,
        )
    ] == [f"workflow-{suffix}"]

    updated = await process_service.update_definition(
        definition.id,
        ProcessDefinitionUpdate(
            agent_id=second.id,
            engine_process_id=f"workflow-updated-{suffix}",
            label="Updated workflow",
            description=None,
        ),
    )

    assert updated is not None
    assert updated.agent_id == second.id
    assert updated.description is None
    assert await process_service.list_for_agent(first.id) == []
    assert [item["workflow_id"] for item in await process_service.list_for_agent(second.id)] == [
        f"workflow-updated-{suffix}"
    ]


@pytest.mark.asyncio
async def test_paginated_runs_separate_active_execution_from_history(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Process activity {suffix}", gender="X")
    tool = Tool(
        code=f"process-activity-{suffix}",
        label="Process activity",
        description="",
        connection_schema={},
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code=f"process-activity-agent-{suffix}",
        first_name="Active",
        last_name="Process",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    definition = ProcessDefinition(
        agent_id=agent.id,
        tool_id=tool.id,
        engine_process_id=f"workflow-{suffix}",
        label="Activity workflow",
    )
    db.add(definition)
    await db.flush()
    running = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        engine_code=tool.code,
        correlation_id=f"running-{suffix}",
        callback_token=f"running-token-{suffix}",
        status="running",
        input={},
        launch_snapshot={},
        engine_metadata={},
    )
    completed = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        engine_code=tool.code,
        correlation_id=f"completed-{suffix}",
        callback_token=f"completed-token-{suffix}",
        status="success",
        input={},
        launch_snapshot={},
        engine_metadata={},
    )
    db.add_all([running, completed])
    await db.commit()

    active_rows, active_total = await process_service.paginate_runs(active=True)
    history_rows, history_total = await process_service.paginate_runs(active=False)

    assert active_total == 1
    assert [run.id for run in active_rows] == [running.id]
    assert history_total == 1
    assert [run.id for run in history_rows] == [completed.id]


def test_sanitizer_redacts_secrets_binary_depth_and_size() -> None:
    cleaned = sanitize(
        {
            "Authorization": "Bearer abc",
            "nested": {"api-key": "secret", "safe": "x" * 100},
            "binary": b"PDF",
        },
        max_bytes=40,
        max_depth=4,
    )
    serialized = str(cleaned)
    assert "Bearer abc" not in serialized
    assert "secret" not in serialized
    assert "binary omitted" in serialized or "truncated" in serialized


@pytest.mark.asyncio
async def test_process_files_keep_canonical_provider_uri_and_original_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.file_share import ResourceDescriptor

    async def info(ctx: object, uri: object) -> ResourceDescriptor:
        assert getattr(ctx, "agent_id") == 7
        assert getattr(ctx, "runtime") == "hermes"
        assert uri == "nextcloud://opaque-file-42"
        return ResourceDescriptor(
            uri=str(uri),
            name="rapport original.pdf",
            media_type="application/pdf",
            size=6,
        )

    import app.file_share as file_share_package

    monkeypatch.setattr(file_share_package, "resource_info", info)

    refs = await process_service._resolve_files(  # pyright: ignore[reportPrivateUsage]
        7,
        "hermes",
        [ProcessFileInput(uri="nextcloud://opaque-file-42")],
        run_id=uuid4(),
    )

    assert refs[0].uri == "nextcloud://opaque-file-42"
    assert refs[0].filename == "rapport original.pdf"
    assert refs[0].size == 6


def test_process_file_input_rejects_legacy_path_alias() -> None:
    with pytest.raises(ValidationError):
        ProcessFileInput.model_validate({"path": "reports/report.pdf"})


@pytest.mark.asyncio
async def test_llm_process_run_is_inherited_from_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    run_id = uuid4()

    async def fake_get_by_id(candidate_id: object) -> object:
        assert candidate_id == task_id
        return SimpleNamespace(data={"process_run_id": str(run_id)})

    monkeypatch.setattr("app.task.task_service.get_by_id", fake_get_by_id)

    resolved = await resolve_runtime_process_run_id(
        raw_process_run_id=None,
        workflow_id=None,
        engine_run_id=None,
        task_id=task_id,
        agent_ids=None,
    )

    assert resolved == run_id


@pytest.mark.asyncio
async def test_explicit_llm_process_run_has_priority() -> None:
    explicit_run_id = uuid4()

    resolved = await resolve_runtime_process_run_id(
        raw_process_run_id=str(explicit_run_id),
        workflow_id="ignored",
        engine_run_id="ignored",
        task_id=None,
        agent_ids=None,
    )

    assert resolved == explicit_run_id


@pytest.mark.asyncio
async def test_explicit_llm_process_run_rejects_task_lineage_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    stored_run_id = uuid4()
    explicit_run_id = uuid4()
    monkeypatch.setattr(
        "app.task.task_service.get_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                data={"process_run_id": str(stored_run_id)}
            )
        ),
    )

    with pytest.raises(ValueError, match="belongs to ProcessRun"):
        await resolve_runtime_process_run_id(
            raw_process_run_id=str(explicit_run_id),
            workflow_id=None,
            engine_run_id=None,
            task_id=task_id,
            agent_ids=None,
        )


@pytest.mark.asyncio
async def test_responses_api_propagates_and_authorizes_process_run(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.llm.call_router as call_router

    run_id = uuid4()
    record = AsyncMock()
    proxy = AsyncMock(return_value=JSONResponse({"id": "resp-process"}))
    monkeypatch.setattr(call_router, "_llm_api_auth", AsyncMock(return_value=None))
    monkeypatch.setattr(call_router, "_resolve_llm_task_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        call_router,
        "_llm_api_agent_ids",
        AsyncMock(return_value=frozenset({7})),
    )
    monkeypatch.setattr(process_service, "record_inbound_call", record)
    monkeypatch.setattr(call_router, "proxy_responses", proxy)

    response = await client.post(
        "/api/llm/openai/responses",
        headers={"X-Galaris-Process-Run-Id": str(run_id)},
        json={"model": "standard", "input": "Analyse this process output."},
    )

    assert response.status_code == 200
    assert proxy.await_args.kwargs["process_run_id"] == run_id
    record.assert_awaited_once_with(
        run_id,
        kind="llm",
        target_code="standard",
        metadata={"correlation_id": None},
        agent_ids=frozenset({7}),
    )


def test_openai_message_process_context_is_extracted_and_removed() -> None:
    body: dict[str, Any] = {
        "model": "aster-test",
        "messages": [
            {
                "role": "system",
                "content": (
                    "galaris_process_context:"
                    '{"workflow_id":"Kw70xUO8uRWkXvtX","run_id":"12345"}'
                ),
            },
            {"role": "user", "content": "Hello"},
        ],
    }

    extract_process_context(body)

    assert body["galaris_workflow_id"] == "Kw70xUO8uRWkXvtX"
    assert body["galaris_engine_run_id"] == "12345"
    assert body["messages"] == [{"role": "user", "content": "Hello"}]


@pytest.mark.asyncio
async def test_apply_snapshot_resets_refresh_failures_and_keeps_failed_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = ProcessRun(
        id=uuid4(),
        process_id=1,
        launcher_agent_id=1,
        engine_code="n8n",
        correlation_id="corr-snapshot",
        callback_token="callback",
        status="running",
        input={},
        launch_snapshot={},
        engine_metadata={"refresh_failures": 4, "last_refresh_error": "timeout"},
    )

    async def fake_transition(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(process_service, "_transition", fake_transition)

    await process_service._apply_snapshot(  # pyright: ignore[reportPrivateUsage]
        run,
        EngineRunSnapshot(
            status="error",
            engine_run_id="execution-1",
            error=EngineError(
                code="NodeApiError",
                message="Authorization data is wrong",
                node_name="Send to agent",
            ),
            raw={"status": "error"},
        ),
        "engine.refresh",
    )

    assert run.engine_run_id == "execution-1"
    assert run.engine_metadata["refresh_failures"] == 0
    assert run.engine_metadata["last_refresh_error"] is None
    assert run.engine_metadata["failed_node"] == "Send to agent"
    assert run.error_code == "NodeApiError"


@pytest.mark.asyncio
async def test_refresh_failure_threshold_degrades_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = ProcessRun(
        id=uuid4(),
        process_id=1,
        launcher_agent_id=1,
        engine_code="n8n",
        engine_run_id="execution-1",
        correlation_id="corr-refresh",
        callback_token="callback",
        status="running",
        input={},
        launch_snapshot={"workflow_id": "Kw70xUO8uRWkXvtX"},
        engine_metadata={"refresh_failures": 1},
    )

    class FakeDB:
        async def commit(self) -> None:
            return None

    async def fake_locked_run(run_id: object) -> ProcessRun:
        assert run_id == run.id
        return run

    async def fake_append_event(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace()

    async def fake_emit(*args: Any, **kwargs: Any) -> None:
        return None

    def fake_increment(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(process_service, "_locked_run", fake_locked_run)
    monkeypatch.setattr(process_service, "_append_event", fake_append_event)
    monkeypatch.setattr(process_service, "get_db", lambda: FakeDB())
    monkeypatch.setattr(process_service.websocket, "emit", fake_emit)
    monkeypatch.setattr(process_service.metrics, "increment", fake_increment)
    monkeypatch.setattr(
        process_service.runtime_settings,
        "PROCESS_REFRESH_MAX_FAILURES",
        2,
    )

    await process_service._record_refresh_failure(  # pyright: ignore[reportPrivateUsage]
        run.id,
        ProcessEngineError("engine_timeout", "timeout", retryable=True),
    )

    assert run.status == "unknown"
    assert run.error_code == "observation_unavailable"
    assert run.engine_metadata["refresh_failures"] == 2


@pytest.mark.asyncio
async def test_terminal_start_failure_resolves_process_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    run = ProcessRun(
        id=uuid4(),
        process_id=1,
        launcher_agent_id=1,
        await_task_id=uuid4(),
        engine_code="fake",
        correlation_id="corr-start-failure",
        callback_token="callback",
        status="queued",
        input={},
        launch_snapshot={"input": {}, "files": []},
        engine_metadata={},
    )
    process = ProcessDefinition(
        id=1,
        agent_id=1,
        tool_id=1,
        engine_process_id="workflow-start-failure",
        label="Start failure",
    )
    job = ProcessStartJob(
        id=1,
        run_id=run.id,
        status="pending",
        attempts=0,
        available_at=now,
        created_at=now,
    )

    class FakeResult:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar_one_or_none(self) -> object:
            return self.value

        def scalar_one(self) -> object:
            return self.value

    class FakeDB:
        def __init__(self) -> None:
            self.results = iter((job, process, job, None))

        async def execute(self, statement: object) -> FakeResult:
            return FakeResult(next(self.results))

        async def get(self, model: type[object], identifier: object) -> object:
            assert (model, identifier) == (ProcessRun, run.id)
            return run

        async def commit(self) -> None:
            return None

    class FailingEngine:
        async def start_run(self, *args: object, **kwargs: object) -> None:
            raise ProcessEngineError("invalid_configuration", "invalid", retryable=False)

    resolved: list[ProcessRun] = []

    async def fake_locked_run(run_id: object) -> ProcessRun:
        assert run_id == run.id
        return run

    async def fake_transition(
        target: ProcessRun,
        status: str,
        **kwargs: object,
    ) -> bool:
        target.status = status
        return True

    async def fake_resolve(target: ProcessRun) -> None:
        resolved.append(target)

    fake_db = FakeDB()
    monkeypatch.setattr(process_service, "get_db", lambda: fake_db)
    monkeypatch.setattr(process_service, "_locked_run", fake_locked_run)
    monkeypatch.setattr(process_service, "_transition", fake_transition)
    monkeypatch.setattr(process_service, "_resolve_await_if_terminal", fake_resolve)
    monkeypatch.setattr(process_service.registry, "get", lambda code: FailingEngine())
    monkeypatch.setattr(process_service.metrics, "increment", lambda *args, **kwargs: None)
    monkeypatch.setattr(process_service.metrics, "observe", lambda *args, **kwargs: None)

    assert await process_service.process_start_jobs(batch_size=2) == 1
    assert run.status == "error"
    assert resolved == [run]


@pytest.mark.asyncio
async def test_compatible_api_correlation_rejects_foreign_agent_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = ProcessRun(
        id=uuid4(),
        process_id=1,
        launcher_agent_id=7,
        engine_code="n8n",
        correlation_id="corr-foreign-agent",
        callback_token="callback",
        status="running",
        input={},
        launch_snapshot={},
    )
    monkeypatch.setattr(
        process_service,
        "_locked_run",
        AsyncMock(return_value=run),
    )

    with pytest.raises(LookupError):
        await process_service.record_inbound_call(
            run_id=run.id,
            kind="llm",
            target_code="model",
            agent_ids=frozenset({8}),
        )


@pytest.mark.asyncio
async def test_correlated_agent_call_rejects_unassigned_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = ProcessRun(
        id=uuid4(),
        process_id=1,
        launcher_agent_id=1,
        engine_code="n8n",
        correlation_id="corr-agent",
        callback_token="callback",
        status="running",
        input={},
        launch_snapshot={},
    )
    process = ProcessDefinition(
        id=1,
        agent_id=2,
        tool_id=1,
        engine_process_id="Kw70xUO8uRWkXvtX",
        label="Invoice recording",
    )

    class FakeDB:
        async def get(self, model: type[Any], identifier: object) -> Any:
            if model is ProcessDefinition and identifier == process.id:
                return process
            return SimpleNamespace(code="assigned-agent")

    async def fake_locked_run(run_id: object) -> ProcessRun:
        assert run_id == run.id
        return run

    monkeypatch.setattr(process_service, "_locked_run", fake_locked_run)
    monkeypatch.setattr(process_service, "get_db", lambda: FakeDB())

    with pytest.raises(PermissionError):
        await process_service.record_inbound_call(
            run_id=run.id,
            kind="agent",
            target_code="another-agent",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("late_status", ["running", "success", "error", "cancelled"])
async def test_late_snapshot_preserves_terminal_payload(monkeypatch, late_status):
    run = ProcessRun(
        id=uuid4(), process_id=1, launcher_agent_id=1, engine_code="n8n",
        status="success", engine_run_id="original", output={"result": "kept"},
        raw_snapshot={"original": True}, engine_metadata={"original": True},
    )
    event = AsyncMock()
    monkeypatch.setattr(process_service, "_append_event", event)
    await process_service._apply_snapshot(
        run,
        EngineRunSnapshot(
            status=late_status, engine_run_id="late", output={"result": "lost"},
            error=EngineError(code="late", message="late"), raw={"late": True},
        ),
        "engine.refresh",
    )
    assert run.status == "success"
    assert run.output == {"result": "kept"}
    assert run.raw_snapshot == {"original": True}
    assert run.engine_metadata == {"original": True}
    assert run.engine_run_id == "original"
    assert run.error_code is None
    assert event.await_args.kwargs["payload"]["accepted"] is False


@pytest.mark.asyncio
async def test_operations_summary_uses_persistent_run_and_outbox_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oldest = datetime.now(timezone.utc) - timedelta(seconds=12)

    class FakeResult:
        def __init__(
            self,
            *,
            rows: list[tuple[str, int]] | None = None,
            one: tuple[int, datetime | None] | None = None,
            scalar: int | None = None,
        ) -> None:
            self._rows = rows
            self._one = one
            self._scalar = scalar

        def all(self) -> list[tuple[str, int]]:
            assert self._rows is not None
            return self._rows

        def one(self) -> tuple[int, datetime | None]:
            assert self._one is not None
            return self._one

        def scalar_one(self) -> int:
            assert self._scalar is not None
            return self._scalar

    class FakeDB:
        def __init__(self) -> None:
            self.results = iter([
                FakeResult(rows=[("running", 2), ("error", 3)]),
                FakeResult(one=(1, oldest)),
                FakeResult(scalar=2),
                FakeResult(scalar=3),
            ])

        async def execute(self, statement: object) -> FakeResult:
            return next(self.results)

    monkeypatch.setattr(process_service, "get_db", lambda: FakeDB())

    summary = await process_service.get_operations()

    assert summary.status_counts == {"running": 2, "error": 3}
    assert summary.pending_start_jobs == 1
    assert summary.stale_active_runs == 2
    assert summary.failed_last_24h == 3
    assert summary.oldest_pending_job_seconds is not None
    assert summary.oldest_pending_job_seconds >= 12
