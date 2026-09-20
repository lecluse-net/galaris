from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import facade
from app.agent.contracts import (
    AIMessage,
    AgentEvent,
    AgentContextCapsule,
    AgentContextRequest,
    AgentRunCheckpoint,
    AgentRunContext,
    AgentRunRequest,
    AgentSnapshot,
    BriefingResult,
    ExecutionResult,
    ResolvedModel,
)
from app.agent.models import Agent, Title
from app.agent.registry import INTERNAL_HARNESS
from app.agent.harness_port import harness_selection_port
from bridge.hermes.agent_driver import HERMES_DRIVER
from app.agent.task_port import task_port
from app.task import TaskMessage
from app.task.models import Task, TaskStatus
from core.database import get_db


@pytest.fixture(autouse=True)
def _detached_unit_harness_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Facade unit tests do not own the DB session used by persisted selections."""

    monkeypatch.setattr(
        harness_selection_port,
        "resolve",
        AsyncMock(return_value=None),
    )
    from app.agent import executor_service
    from app.agent.contracts import HarnessExecutionPolicy

    monkeypatch.setattr(harness_selection_port, "configuration", AsyncMock(return_value=(HarnessExecutionPolicy(), 0)))

    monkeypatch.setattr(executor_service.params_service, "get", AsyncMock(return_value=""))


def test_stream_metadata_filter_removes_split_cartouche() -> None:
    filter_ = facade._LeadingMessageMetadataFilter()  # pyright: ignore[reportPrivateUsage]

    assert filter_.feed("[2026-08-13 23") == ""
    assert filter_.feed(":02 | Lyra d'Exemple | AI] Bonsoir") == "Bonsoir"
    assert filter_.feed(" !") == " !"


def test_stream_metadata_filter_releases_normal_bracketed_text() -> None:
    filter_ = facade._LeadingMessageMetadataFilter()  # pyright: ignore[reportPrivateUsage]

    assert filter_.feed("[Important]") == "[Important]"


@pytest.mark.asyncio
async def test_internal_harness_has_no_task_parallelism_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service

    monkeypatch.setattr(
        agent_service,
        "get",
        AsyncMock(return_value=SimpleNamespace(agent_driver="internal")),
    )

    assert await facade.max_parallel_tasks_for_agent(7) is None


@pytest.mark.asyncio
async def test_selected_external_harness_exposes_its_task_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service

    agent = SimpleNamespace(agent_driver="openai_messages")
    monkeypatch.setattr(agent_service, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        harness_selection_port,
        "resolve",
        AsyncMock(return_value=SimpleNamespace(max_parallel_tasks=1, provider_code="openai_messages")),
    )

    assert await facade.max_parallel_tasks_for_agent(7) == 1


@pytest.mark.asyncio
async def test_external_harness_cannot_be_resolved_as_unbounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service

    agent = SimpleNamespace(agent_driver="openai_messages")
    monkeypatch.setattr(agent_service, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        harness_selection_port,
        "resolve",
        AsyncMock(return_value=SimpleNamespace(max_parallel_tasks=None)),
    )

    with pytest.raises(RuntimeError, match="positive task parallelism"):
        await facade.max_parallel_tasks_for_agent(7)


def _model() -> ResolvedModel:
    return ResolvedModel(
        id=7,
        code="fast",
        model_name="provider/model",
        label="Fast",
        requested_effort="high",
    )


def _task() -> Task:
    agent = Agent(
        id=3,
        title_id=1,
        code="alice",
        first_name="Alice",
        last_name="Martin",
        agent_driver="internal",
        personality="<p>precise</p>",
        job_description="<p>test</p>",
    )
    agent.title = Title(id=1, label="Ms", gender="F")
    task = Task(
        id=uuid4(),
        label="Test",
        objective="Verify the contract",
        status=TaskStatus.DISPATCH,
        effort="high",
        agent_id=agent.id,
        data={"language": "fr", "plan_tools": ["search_web"]},
        messages=[TaskMessage(external_message_id="m1", text="Hello")],
    )
    task.agent = agent
    return task


@pytest.mark.asyncio
async def test_task_context_is_committed_before_crossing_the_llm_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    contact_id = uuid4()
    capsule = AgentContextCapsule(
        contact_memory_item_id=contact_id,
        rendered="frozen context",
    )
    built = AgentRunContext(context_capsule=capsule)
    events: list[str] = []

    async def freeze(
        _task: object,
        _capsule: AgentContextCapsule,
    ) -> AgentContextCapsule:
        events.append("freeze")
        return capsule

    async def save(_task: object) -> object:
        events.append("save")
        return _task

    from app.agent import context as context_module

    monkeypatch.setattr(
        context_module,
        "build_agent_run_context",
        AsyncMock(return_value=built),
    )
    monkeypatch.setattr(task_port, "get_context_capsule", AsyncMock(return_value=None))
    monkeypatch.setattr(task_port, "freeze_context_capsule", freeze)
    monkeypatch.setattr(task_port, "save", save)

    result = await facade._build_task_run_context(  # pyright: ignore[reportPrivateUsage]
        task,
        AgentContextRequest(
            task_id=task.id,
            agent=AgentSnapshot(
                id=3,
                code="alice",
                first_name="Alice",
                last_name="Martin",
                driver_code="internal",
            ),
            objective="Verify the contract",
            contact_memory_item_id=contact_id,
        ),
    )

    assert result is built
    assert events == ["freeze", "save"]


def test_apply_run_result_exposes_safe_memory_context_telemetry() -> None:
    task = _task()
    memory_id = uuid4()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="high",
        objective=task.objective,
        model=_model(),
        metadata={
            "memory_context_enabled": True,
            "memory_context_query": "prior deployment decision",
            "memory_context_count": 1,
            "memory_context_retrieved_count": 4,
            "memory_context_truncated": False,
            "memory_context_ids": [str(memory_id)],
            "memory_context_rendered": "sensitive recalled text",
        },
    )
    result = ExecutionResult(prompt="p", result="done", success=True)

    facade._apply_run_result(task, result, request)  # pyright: ignore[reportPrivateUsage]

    assert result.metadata["memory_context"] == {
        "enabled": True,
        "query": "prior deployment decision",
        "count": 1,
        "retrieved_count": 4,
        "truncated": False,
        "memory_ids": [str(memory_id)],
        "error": None,
    }
    assert "sensitive recalled text" not in str(result.metadata)


def test_internal_checkpoint_requires_explicit_effect_safety_marker() -> None:
    task = SimpleNamespace(
        data={
            facade.RUN_CHECKPOINT_DATA_KEY: {
                "driver_code": "internal",
                "runtime_run_id": "run-1",
                "status": "running",
                "data": {"version": 1, "resume_safe": False},
            }
        }
    )

    assert facade.has_resumable_run_checkpoint(task) is False
    task.data[facade.RUN_CHECKPOINT_DATA_KEY]["data"]["resume_safe"] = True
    assert facade.has_resumable_run_checkpoint(task) is True


def test_failed_run_preserves_safe_checkpoint_for_automatic_retry() -> None:
    task = _task()
    checkpoint = {
        "request_run_id": str(uuid4()),
        "driver_code": "internal",
        "runtime_run_id": "run-interrupted",
        "status": "running",
        "result": None,
        "data": {"version": 2, "resume_safe": True},
    }
    task.data = {
        **(task.data or {}),
        facade.RUN_CHECKPOINT_DATA_KEY: checkpoint,
        facade.RUN_IDENTITY_DATA_KEY: {"request_run_id": str(uuid4())},
    }
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="high",
        objective=task.objective,
        model=_model(),
    )
    result = ExecutionResult(
        prompt="Create the artifact",
        result=(
            "RemoteProtocolError: peer closed connection without sending complete "
            "message body (incomplete chunked read)"
        ),
        success=False,
        tools_used=["console_exec"],
    )

    facade._apply_run_result(task, result, request)  # pyright: ignore[reportPrivateUsage]

    assert task.data is not None
    assert task.data[facade.RUN_CHECKPOINT_DATA_KEY] == checkpoint
    assert facade.RUN_IDENTITY_DATA_KEY not in task.data
    assert facade.has_resumable_run_checkpoint(task) is True


@pytest.mark.asyncio
async def test_run_task_builds_and_runs_one_immutable_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    request = SimpleNamespace(objective=task.objective)
    build = AsyncMock(return_value=request)
    run = AsyncMock(return_value=ExecutionResult(prompt="p", result="done"))
    monkeypatch.setattr(facade, "build_run_request", build)
    monkeypatch.setattr(facade, "run", run)
    monkeypatch.setattr(facade, "_apply_run_result", lambda *_args: None)
    monkeypatch.setattr(task_port, "refresh", AsyncMock(return_value=task))

    await facade.run_task(task)

    build.assert_awaited_once_with(task)
    run.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_build_run_request_freezes_the_orm_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    request = await facade.build_run_request(task)

    assert isinstance(request, AgentRunRequest)
    assert request.task_id == task.id
    assert request.agent == AgentSnapshot(
        id=3,
        code="alice",
        first_name="Alice",
        last_name="Martin",
        driver_code="internal",
        gender="F",
        llm_id=7,
        personality="<p>precise</p>",
        job_description="<p>test</p>",
        driver_config={},
    )
    assert request.model.id == 7
    assert request.execution_strategy == "direct"
    assert "# Your identity" in request.executor_system_prompt
    assert "**Your name:** **Alice Martin**" in request.executor_system_prompt
    assert "# Your personality\n\n<p>precise</p>" in request.executor_system_prompt
    assert "# Job description\n\n<p>test</p>" in request.executor_system_prompt
    assert "# Apply your profile" in request.executor_system_prompt
    assert request.to_envelope().system_instructions == request.executor_system_prompt
    assert request.conversation_history[0]["text"] == "Hello"
    task.data["language"] = "en"
    assert request.task_data["language"] == "fr"


@pytest.mark.asyncio
async def test_internal_high_does_not_inherit_a_historical_briefing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.effort = "high"
    task.set_briefing_result(BriefingResult(result="historical briefing"))
    monkeypatch.setattr(
        facade,
        "resolve_execution_model",
        AsyncMock(return_value=_model()),
    )
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    request = await facade.build_run_request(task)

    assert request.briefing_result is None
    assert request.metadata["briefing_text"] == ""


@pytest.mark.asyncio
async def test_hermes_high_uses_direct_without_inheriting_a_briefing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.agent.agent_driver = "hermes"
    task.set_briefing_result(BriefingResult(result="stale internal briefing"))
    monkeypatch.setattr(facade, "validate_agent_driver", lambda _code: "hermes")
    monkeypatch.setattr(facade, "resolve_driver", lambda _code: HERMES_DRIVER)
    monkeypatch.setattr(
        facade,
        "_execution_driver_configuration",
        AsyncMock(
            return_value={
                "kanban": {
                    "transport": "legacy",
                    "board": "default",
                    "assignee": "default",
                    "workspace_path": "/opt/data/galaris",
                }
            }
        ),
    )
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    request = await facade.build_run_request(task)

    assert request.execution_strategy == "direct"
    assert request.briefing_result is None
    assert request.metadata["briefing_text"] == ""

    task.data[facade.RUN_CHECKPOINT_DATA_KEY] = {
        "driver_code": "hermes",
        "runtime_run_id": "legacy-direct-run",
        "status": "running",
        "result": None,
        "data": {"session_id": "legacy-session"},
    }
    resumed = await facade.build_run_request(task)
    assert resumed.execution_strategy == "direct"

    task.data[facade.RUN_CHECKPOINT_DATA_KEY] = {
        "driver_code": "hermes",
        "runtime_run_id": "t_existing",
        "status": "running",
        "result": None,
        "data": {"execution_strategy": "kanban"},
    }
    resumed_kanban = await facade.build_run_request(task)
    assert resumed_kanban.execution_strategy == "kanban"


@pytest.mark.asyncio
async def test_run_checkpoint_updates_live_trace_and_is_loaded_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    persist = AsyncMock()
    monkeypatch.setattr(task_port, "persist_agent_run_state", persist)

    request = await facade.build_run_request(task)
    logical_run_id = request.run_id
    assert request.save_checkpoint is not None
    await request.save_checkpoint(AgentRunCheckpoint(
        driver_code="internal",
        runtime_run_id="run-existing",
        status="running",
        result=ExecutionResult(
            prompt="Sample",
            messages=[AIMessage(type="tool", tool_name="file_write", content="created")],
            tools_used=["file_write"],
        ),
        data={"version": 1, "resume_safe": True, "session_id": "session-1"},
    ))

    persist.assert_awaited_once()
    persisted = persist.await_args.kwargs
    assert persisted["expected_objective"] == task.objective
    saved_result = persisted["execution_result"]
    assert saved_result.tools_used == ["file_write"]
    checkpoint_patch = persisted["data_patch"]
    checkpoint_payload = checkpoint_patch[facade.RUN_CHECKPOINT_DATA_KEY]
    assert checkpoint_payload["runtime_run_id"] == "run-existing"
    assert checkpoint_payload["data"][
        "objective_fingerprint"
    ] == facade._objective_fingerprint(task.objective or "")  # pyright: ignore[reportPrivateUsage]

    # A later scheduler transaction reloads the independently persisted state.
    task.data = {
        **(task.data or {}),
        "working_set": {"version": 1, "resources": []},
        **checkpoint_patch,
    }
    task.set_execution_result(saved_result)

    resumed = await facade.build_run_request(task)
    assert resumed.run_id == logical_run_id
    assert resumed.resume_checkpoint is not None
    assert resumed.resume_checkpoint.runtime_run_id == "run-existing"
    assert resumed.resume_checkpoint.result is not None
    assert resumed.resume_checkpoint.result.tools_used == ["file_write"]

    facade._apply_run_result(  # pyright: ignore[reportPrivateUsage]
        task,
        ExecutionResult(prompt="Sample", result="done", success=True),
        resumed,
    )
    assert facade.RUN_CHECKPOINT_DATA_KEY not in (task.data or {})


@pytest.mark.asyncio
async def test_amended_objective_rebases_internal_checkpoint_without_old_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.objective = "Move Galaris and MaLibFin into the development directory."
    task.data = {
        **(task.data or {}),
        "amendment_count": 1,
        facade.RUN_CHECKPOINT_DATA_KEY: {
            "driver_code": "internal",
            "runtime_run_id": "old-run",
            "status": "running",
            "result": ExecutionResult(
                prompt="Reset Galaris only.",
                result="Reset complete.",
                tools_used=["console_exec"],
            ).model_dump(mode="json"),
            "data": {
                "version": 1,
                "resume_safe": True,
                "effects": [
                    {
                        "tool_name": "console_exec",
                        "status": "completed",
                        "signature": "reset-effect",
                    }
                ],
                "message_history": [{"kind": "old-provider-history"}],
            },
        },
    }
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    request = await facade.build_run_request(task)

    assert request.objective == task.objective
    assert request.resume_checkpoint is not None
    assert request.resume_checkpoint.result is None
    assert request.resume_checkpoint.data["message_history"] == []
    assert request.resume_checkpoint.data["effects"] == [
        {
            "tool_name": "console_exec",
            "status": "completed",
            "signature": "reset-effect",
        }
    ]
    assert request.resume_checkpoint.data["objective_fingerprint"] == (
        facade._objective_fingerprint(task.objective or "")  # pyright: ignore[reportPrivateUsage]
    )


@pytest.mark.asyncio
async def test_stale_run_cannot_restore_checkpoint_after_objective_amendment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))

    persist = AsyncMock(
        side_effect=facade.StaleAgentRunError(
            "The Task objective changed while this agent run was active"
        )
    )
    monkeypatch.setattr(task_port, "persist_agent_run_state", persist)
    request = await facade.build_run_request(task)
    assert request.save_checkpoint is not None

    with pytest.raises(facade.StaleAgentRunError, match="objective changed"):
        await request.save_checkpoint(
            AgentRunCheckpoint(
                driver_code="internal",
                runtime_run_id="stale-run",
                status="running",
                data={"version": 1, "resume_safe": True},
            )
        )

    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_progress_updates_live_trace_without_creating_resume_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    monkeypatch.setattr(facade, "resolve_execution_model", AsyncMock(return_value=_model()))
    monkeypatch.setattr(task_port, "approval_action", AsyncMock(return_value="ask"))
    persist = AsyncMock()
    monkeypatch.setattr(task_port, "persist_agent_run_state", persist)

    request = await facade.build_run_request(task)
    assert request.save_progress is not None
    await request.save_progress(ExecutionResult(
        prompt="Sample",
        messages=[AIMessage(type="tool", tool_name="search_web", content="found")],
        tools_used=["search_web"],
    ))

    assert task.get_execution_result() is None
    assert facade.RUN_CHECKPOINT_DATA_KEY not in (task.data or {})
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["execution_result"].tools_used == ["search_web"]
    assert "data_patch" not in persist.await_args.kwargs


@pytest.mark.asyncio
async def test_stream_has_exactly_one_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="high",
        objective=task.objective,
        model=_model(),
    )

    class FakeDriver:
        spec = INTERNAL_HARNESS

        async def stream(self, _request: AgentRunRequest):
            yield AgentEvent.from_message(AIMessage(type="text", content="ok"))
            yield AgentEvent.from_result(ExecutionResult(prompt="p", result="ok"))

    monkeypatch.setattr(facade, "build_run_request", AsyncMock(return_value=request))
    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: FakeDriver())
    monkeypatch.setattr(task_port, "refresh", AsyncMock(return_value=task))

    messages = [
        message
        async for message in facade.stream_task(task)
    ]

    assert [message.content for message in messages] == ["ok"]
    stored = task.get_execution_result()
    assert stored is not None
    assert stored.result == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["message", "result", "exception"])
async def test_invalid_driver_tail_fails_before_publishing_a_terminal_success(monkeypatch, extra):
    request = AgentRunRequest(
        run_id=uuid4(), task_id=uuid4(),
        agent=AgentSnapshot(id=3, code="alice", first_name="Alice", last_name="Martin", driver_code="internal"),
        driver_code="internal", effort="high", objective="Do the work", model=_model(),
    )

    class Driver:
        async def stream(self, _request):
            yield AgentEvent.from_result(ExecutionResult(prompt="", result="Done"))
            if extra == "exception":
                raise RuntimeError("late transport failure")
            if extra == "message":
                yield AgentEvent.from_message(AIMessage(type="text", content="late"))
            else:
                yield AgentEvent.from_result(ExecutionResult(prompt="", result="Wrong"))

    publish = AsyncMock()
    monkeypatch.setattr("app.agent.live.publish_live_event", publish)
    monkeypatch.setattr(facade, "_publish_run_event", AsyncMock())
    monkeypatch.setattr(facade, "_record_run_outcome", AsyncMock())
    with pytest.raises(RuntimeError):
        async for _ in facade._stream_driver(request, spec=INTERNAL_HARNESS, driver=Driver()):
            pass
    assert [call.args[0].kind for call in publish.await_args_list] == ["started", "failed"]


@pytest.mark.asyncio
async def test_stale_stream_is_cancelled_without_recording_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective=task.objective,
        model=_model(),
    )

    class StaleDriver:
        async def stream(self, _request: AgentRunRequest):
            raise facade.StaleAgentRunError("objective changed")
            yield  # pragma: no cover

    record_outcome = AsyncMock()
    publish_run_event = AsyncMock()
    publish_live_event = AsyncMock()
    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: StaleDriver())
    monkeypatch.setattr(facade, "_record_run_outcome", record_outcome)
    monkeypatch.setattr(facade, "_publish_run_event", publish_run_event)
    monkeypatch.setattr("app.agent.live.publish_live_event", publish_live_event)

    with pytest.raises(facade.StaleAgentRunError, match="objective changed"):
        async for _event in facade.stream(request):
            pass

    record_outcome.assert_not_awaited()
    assert publish_run_event.await_args_list[-1].kwargs["kind"] == "run.cancelled"
    assert publish_live_event.await_args.args[0].kind == "cancelled"


@pytest.mark.asyncio
async def test_task_stream_keeps_db_context_available_for_driver_setup(
    monkeypatch: pytest.MonkeyPatch,
    db,
) -> None:
    task = _task()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="high",
        objective=task.objective,
        model=_model(),
    )

    class FakeDriver:
        spec = INTERNAL_HARNESS

        async def stream(self, _request: AgentRunRequest):
            assert get_db() is db
            yield AgentEvent.from_message(AIMessage(type="text", content="isolated"))
            assert get_db() is db
            yield AgentEvent.from_result(ExecutionResult(prompt="p", result="ok"))

    monkeypatch.setattr(facade, "build_run_request", AsyncMock(return_value=request))
    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: FakeDriver())
    monkeypatch.setattr(task_port, "refresh", AsyncMock(return_value=task))

    messages = facade.stream_task(task)
    message = await anext(messages)

    assert message.content == "isolated"
    assert get_db() is db
    with pytest.raises(StopAsyncIteration):
        await anext(messages)
    assert get_db() is db


@pytest.mark.asyncio
async def test_terminal_result_for_superseded_objective_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    request = SimpleNamespace(objective=task.objective)
    monkeypatch.setattr(facade, "build_run_request", AsyncMock(return_value=request))
    monkeypatch.setattr(
        facade,
        "run",
        AsyncMock(return_value=ExecutionResult(prompt="old", result="stale")),
    )

    async def refresh_with_amendment(current: Task) -> Task:
        current.objective = "Revised objective"
        return current

    monkeypatch.setattr(task_port, "refresh", refresh_with_amendment)
    apply_result = AsyncMock()
    monkeypatch.setattr(facade, "_apply_run_result", apply_result)

    with pytest.raises(facade.StaleAgentRunError, match="objective changed"):
        await facade.run_task(task)

    apply_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_rejects_a_driver_without_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task.id,
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="test",
        model=_model(),
    )

    class BrokenDriver:
        async def stream(self, _request: object):
            yield AgentEvent.from_message(AIMessage(type="text", content="partial"))

    monkeypatch.setattr(facade, "build_run_request", AsyncMock(return_value=request))
    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: BrokenDriver())

    with pytest.raises(RuntimeError, match="emitted no terminal result"):
        async for _ in facade.stream_task(task):
            pass


@pytest.mark.asyncio
async def test_stream_conversation_turn_is_taskless_and_deduplicates_final_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service, context

    requests: list[AgentRunRequest] = []
    run_id = uuid4()
    conversation_round_id = uuid4()

    monkeypatch.setattr(
        agent_service,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                id=7,
                code="alice",
                first_name="Alice",
                last_name="Martin",
                agent_driver="hermes",
                title=SimpleNamespace(gender="F"),
                personality="<p>precise</p>",
                job_description="<p>test</p>",
                job_title="Agent",
            )
        ),
    )
    monkeypatch.setattr(
        facade,
        "resolve_conversation_model",
        AsyncMock(return_value=_model()),
    )
    monkeypatch.setattr(
        facade,
        "_execution_driver_configuration",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        context,
        "build_agent_run_context",
        AsyncMock(
            return_value=AgentRunContext(
                conversation_history=({"role": "assistant", "text": "Salut"},),
            )
        ),
    )

    class FakeDriver:
        async def stream(self, request: AgentRunRequest):
            requests.append(request)
            yield AgentEvent.from_message(AIMessage(type="text", content="Bonjour"))
            yield AgentEvent.from_message(AIMessage(type="text", content=" Nicolas."))
            yield AgentEvent.from_message(
                AIMessage(type="text", content="Bonjour Nicolas.")
            )
            yield AgentEvent.from_result(
                ExecutionResult(prompt="Dis bonjour", result="Bonjour Nicolas.")
            )

    monkeypatch.setattr(facade, "resolve_driver", lambda _code: INTERNAL_HARNESS)
    monkeypatch.setattr(facade, "create_driver", lambda _spec: FakeDriver())

    messages = [
        message
        async for message in facade.stream_conversation_turn(
            agent_id=7,
            objective="Dis bonjour",
            conversation_id="room-1",
            room_locator="transport-room-1",
            messenger_connection_id=19,
            language="fr",
            transport_kind="test",
            run_id=run_id,
            conversation_round_id=conversation_round_id,
        )
    ]

    assert [message.content for message in messages] == ["Bonjour", " Nicolas."]
    assert len(requests) == 1
    request = requests[0]
    assert request.run_id == run_id
    assert request.task_id is None
    assert request.driver_code == "internal"
    assert request.objective == "Dis bonjour"
    assert request.messenger_connection_id == 19
    assert request.message_platform == "voice:test"
    assert request.message_group_id == "room-1"
    assert request.messaging_context["room_locator"] == "transport-room-1"
    assert request.task_data["connection_id"] == 19
    assert request.task_data["room_locator"] == "transport-room-1"
    assert request.task_data["messenger_connection_id"] == 19
    assert request.task_data["conversation_round_id"] == str(conversation_round_id)
    assert request.task_data["conversation_only"] is True
    assert request.conversation_history[0]["text"] == "Salut"

    current_message_id = uuid4()
    pending_message_id = uuid4()
    events = [
        event
        async for event in facade.stream_conversation_turn_events(
            agent_id=7,
            objective="Dis bonjour",
            conversation_id="room-1",
            room_locator="transport-room-1",
            messenger_connection_id=19,
            language="fr",
            transport_kind="test",
            run_id=run_id,
            conversation_round_id=conversation_round_id,
            current_message_id=current_message_id,
            excluded_message_ids=(pending_message_id, current_message_id),
        )
    ]
    assert requests[-1].task_data["message_id"] == str(current_message_id)
    assert requests[-1].task_data["excluded_message_ids"] == (
        str(pending_message_id), str(current_message_id),
    )
    assert [event.kind for event in events] == ["message", "message", "result"]
    terminal = events[-1].result
    assert terminal is not None
    assert terminal.result == "Bonjour Nicolas."
    assert terminal.metadata["run_id"] == str(run_id)
    assert terminal.metadata["driver_code"] == "internal"


@pytest.mark.parametrize("version", [None, 1])
def test_checkpoint_reads_previous_unversioned_and_current_formats(version):
    from app.agent.facade import _read_run_checkpoint, RUN_CHECKPOINT_DATA_KEY
    payload = {"driver_code": "internal", "runtime_run_id": "old-run", "status": "interrupted", "data": {"effects": [{"status": "completed", "result": "saved"}]}}
    if version is not None:
        payload["schema_version"] = version
    checkpoint = _read_run_checkpoint({RUN_CHECKPOINT_DATA_KEY: payload})
    assert checkpoint is not None
    assert checkpoint.data["effects"][0]["result"] == "saved"


def test_unknown_checkpoint_version_cannot_silently_restart_effects():
    from app.agent.facade import _read_run_checkpoint, RUN_CHECKPOINT_DATA_KEY
    with pytest.raises(ValueError, match="Unsupported agent checkpoint"):
        _read_run_checkpoint({RUN_CHECKPOINT_DATA_KEY: {"schema_version": 2, "driver_code": "internal", "runtime_run_id": "future", "status": "interrupted"}})
