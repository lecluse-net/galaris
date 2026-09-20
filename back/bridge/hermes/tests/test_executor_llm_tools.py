from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

# pyright: reportPrivateUsage=false

from app.agent.contracts import (
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    AIMessage,
    AIResult,
    ExecutionResult,
    ResolvedModel,
)
from bridge.hermes import driver as hermes_driver
from bridge.hermes import executor


@pytest.mark.asyncio
async def test_llm_tool_recovery_is_disabled_when_high_kanban_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_calls = AsyncMock()
    from app.llm import llm_call_service

    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)

    result = AIResult(prompt="prompt")
    await executor.sync_llm_tool_messages(uuid4(), result, {})

    assert hermes_driver.HERMES_HIGH_KANBAN_ENABLED is False
    list_calls.assert_not_awaited()
    assert result.messages == []


@pytest.mark.asyncio
async def test_sync_llm_tool_messages_adds_and_updates_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    task_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tool_calls=[
            {
                "id": "tool-1",
                "name": "mcp__galaris__galaris_search",
                "arguments": {"query": "demo"},
                "status": "requested",
                "started_at": "2026-07-09T10:00:00+00:00",
            }
        ],
    )

    async def list_calls(*, task_id: object = None, limit: int = 200):
        return [call]

    from app.llm import llm_call_service

    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)

    result = AIResult(prompt="prompt")
    seen: dict[str, AIMessage] = {}
    await executor.sync_llm_tool_messages(task_id, result, seen)

    assert len(result.messages) == 1
    assert result.messages[0].type == "tool"
    assert result.messages[0].tool_name == "search"
    assert result.messages[0].tool_arguments == {"query": "demo"}
    assert result.messages[0].content == "Running..."
    assert result.messages[0].tool_call_external_id == "tool-1"
    assert result.tools_used == ["search"]

    call.tool_calls[0]["status"] = "completed"
    call.tool_calls[0]["result"] = {"items": [1, 2]}
    call.tool_calls[0]["completed_at"] = "2026-07-09T10:00:02.500000+00:00"
    await executor.sync_llm_tool_messages(task_id, result, seen)

    assert len(result.messages) == 1
    assert result.messages[0].content == '{"items": [1, 2]}'
    assert result.messages[0].execution_time == 2.5
    assert result.messages[0].success is True
    assert result.messages[0].tool_call_external_id == "tool-1"


@pytest.mark.asyncio
async def test_sync_llm_tool_messages_unwraps_deferred_hermes_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    task_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tool_calls=[
            {
                "id": "tool-1",
                "name": "tool_call",
                "arguments": {
                    "name": "mcp__galaris__messenger_room_send_message",
                    "arguments": {
                        "room_id": "room-42",
                        "message": "Bonjour",
                    },
                },
                "status": "completed",
                "result": {"result": "Message envoyé."},
            }
        ],
    )

    async def list_calls(*, task_id: object = None, limit: int = 200):
        return [call]

    from app.llm import llm_call_service

    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)

    result = AIResult(prompt="prompt")
    await executor.sync_llm_tool_messages(task_id, result, {})

    assert len(result.messages) == 1
    assert result.messages[0].tool_name == "messenger_room_send_message"
    assert result.messages[0].tool_arguments == {
        "room_id": "room-42",
        "message": "Bonjour",
    }
    assert result.tools_used == ["messenger_room_send_message"]


@pytest.mark.asyncio
async def test_sync_llm_tool_messages_skips_dispatcher_final_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    task_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tool_calls=[
            {
                "id": "dispatch-tool",
                "name": "final_result",
                "arguments": {
                    "route": "EXEC",
                    "effort": "standard",
                    "language": "fr",
                },
                "status": "requested",
            }
        ],
    )

    async def list_calls(*, task_id: object = None, limit: int = 200):
        return [call]

    from app.llm import llm_call_service

    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)

    result = AIResult(prompt="prompt")
    seen: dict[str, AIMessage] = {}
    await executor.sync_llm_tool_messages(task_id, result, seen)

    assert result.messages == []
    assert result.tools_used == []
    assert seen == {}


@pytest.mark.asyncio
async def test_sync_llm_tool_messages_excludes_previous_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    task_id = uuid4()
    previous = SimpleNamespace(
        id=uuid4(),
        tool_calls=[{"id": "old", "name": "messenger_room_send_message"}],
    )
    current = SimpleNamespace(
        id=uuid4(),
        tool_calls=[{"id": "new", "name": "search", "result": "ok"}],
    )

    async def list_calls(*, task_id: object = None, limit: int = 200):
        return [previous, current]

    from app.llm import llm_call_service

    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)
    result = AIResult(prompt="reprise")
    await executor.sync_llm_tool_messages(
        task_id,
        result,
        {},
        excluded_call_ids={str(previous.id)},
    )

    assert result.tools_used == ["search"]
    assert [message.tool_name for message in result.messages] == ["search"]


@pytest.mark.asyncio
async def test_sync_hermes_session_messages_restores_native_reasoning_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"id": 10, "role": "user", "content": "current objective"},
        {
            "id": 11,
            "role": "assistant",
            "content": "",
            "reasoning": "I should inspect the workspace.",
            "reasoning_content": "I should inspect the workspace.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"pwd"}',
                    },
                }
            ],
        },
        {
            "id": 12,
            "role": "tool",
            "tool_call_id": "call-1",
            "tool_name": "terminal",
            "content": "/opt/data",
        },
    ]
    monkeypatch.setattr(
        executor.client,
        "get_session_messages",
        AsyncMock(return_value=messages),
    )
    result = AIResult(prompt="prompt")
    seen = {"10"}
    tools: dict[str, AIMessage] = {}

    await executor._sync_hermes_session_messages(
        SimpleNamespace(),
        "session-1",
        result,
        seen,
        tools,
    )
    await executor._sync_hermes_session_messages(
        SimpleNamespace(),
        "session-1",
        result,
        seen,
        tools,
    )

    assert [(message.tool_name, message.content) for message in result.messages] == [
        ("thinking", "I should inspect the workspace."),
        ("terminal", "/opt/data"),
    ]
    assert result.messages[1].tool_arguments == {"command": "pwd"}
    assert result.messages[1].tool_call_external_id == "call-1"
    assert result.tools_used == ["terminal"]
    assert seen == {"10", "11", "12"}


@pytest.mark.asyncio
async def test_sync_hermes_session_messages_unwraps_deferred_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {
            "id": 11,
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "tool_call",
                        "arguments": (
                            '{"name":"mcp__galaris__messenger_room_send_message",'
                            '"arguments":{"room_id":"room-42","message":"Bonjour"}}'
                        ),
                    },
                }
            ],
        },
        {
            "id": 12,
            "role": "tool",
            "tool_call_id": "call-1",
            "tool_name": "mcp__galaris__messenger_room_send_message",
            "content": "Message envoyé.",
        },
    ]
    monkeypatch.setattr(
        executor.client,
        "get_session_messages",
        AsyncMock(return_value=messages),
    )
    result = AIResult(prompt="prompt")

    await executor._sync_hermes_session_messages(
        SimpleNamespace(),
        "session-1",
        result,
        set(),
        {},
    )

    assert len(result.messages) == 1
    assert result.messages[0].tool_name == "messenger_room_send_message"
    assert result.messages[0].tool_arguments == {
        "room_id": "room-42",
        "message": "Bonjour",
    }
    assert result.messages[0].content == "Message envoyé."
    assert result.tools_used == ["messenger_room_send_message"]


def test_llm_failure_detects_cancelled_or_error_terminal_call() -> None:
    cancelled = SimpleNamespace(
        status="cancelled", error="Client disconnected", finish_reason=None
    )
    assert executor._llm_failure_text([cancelled]) == "Client disconnected"

    completed_before_done = SimpleNamespace(
        status="cancelled", error="Client disconnected", finish_reason="stop"
    )
    assert executor._llm_failure_text([completed_before_done]) is None

    failed = SimpleNamespace(status="error", error="DNS unavailable", finish_reason=None)
    assert executor._llm_failure_text([failed]) == "DNS unavailable"

    recovered = SimpleNamespace(status="completed", error=None, finish_reason="stop")
    assert executor._llm_failure_text([failed, recovered]) is None


def test_explicit_completed_run_is_not_overridden_by_auxiliary_running_call() -> None:
    background_review = SimpleNamespace(
        status="running", error=None, finish_reason=None
    )

    assert executor._resolve_run_error(
        "completed", [background_review], None
    ) is None


def test_explicit_failed_run_remains_authoritative() -> None:
    later_completed = SimpleNamespace(
        status="completed", error=None, finish_reason="stop"
    )

    assert executor._resolve_run_error(
        "failed", [later_completed], "Hermes quota exhausted"
    ) == "Hermes quota exhausted"


@pytest.mark.asyncio
async def test_resumed_run_is_polled_without_opening_a_new_event_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = [
        {"status": "running", "run_id": "run-existing"},
        {"status": "completed", "run_id": "run-existing", "output": "done"},
    ]

    async def get_run_status(_target: object, run_id: str):
        assert run_id == "run-existing"
        return statuses.pop(0)

    async def forbidden_events(*_args: object, **_kwargs: object):
        raise AssertionError("A resumed run must not reopen its destructive SSE queue")
        yield {}

    monkeypatch.setattr(executor.client, "get_run_status", get_run_status)
    monkeypatch.setattr(executor.client, "run_events", forbidden_events)
    monkeypatch.setattr(executor.asyncio, "sleep", AsyncMock())

    events = [
        event
        async for event in executor._run_lifecycle_events(
            SimpleNamespace(),
            "run-existing",
            resume=True,
            language="en",
        )
    ]

    assert [event["event"] for event in events] == ["run.status", "run.completed"]
    assert events[-1]["data"]["output"] == "done"


def test_checkpoint_with_real_tool_effects_cannot_be_replayed() -> None:
    checkpoint = AgentRunCheckpoint(
        driver_code="hermes",
        runtime_run_id="run-existing",
        status="running",
        result=ExecutionResult(
            prompt="create a file",
            tools_used=["file_write"],
        ),
    )

    assert executor._checkpoint_has_effects(checkpoint) is True


@pytest.mark.asyncio
async def test_executor_resumes_checkpoint_without_starting_another_hermes_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    save_checkpoint = AsyncMock()
    checkpoint = AgentRunCheckpoint(
        driver_code="hermes",
        runtime_run_id="run-existing",
        status="running",
        result=ExecutionResult(prompt="Sample", result="", success=True),
        data={
            "session_id": "session-1",
            "effective_session_id": "session-tip-2",
            "cost_before": 0.0,
            "prior_llm_call_ids": [],
        },
    )
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=task_id,
        agent=AgentSnapshot(
            id=1,
            code="aster",
            first_name="Aster",
            last_name="Test",
            driver_code="hermes",
            driver_config={
                "url": "http://hermes:8642/v1",
                "api_key": "key",
                "model": "hermes-agent",
            },
        ),
        driver_code="hermes",
        effort="standard",
        objective="Create one PDF",
        model=ResolvedModel(
            id=1,
            code="model",
            model_name="provider/model",
            label="Model",
            requested_effort="standard",
        ),
        resume_checkpoint=checkpoint,
        control=AgentRunControl(save_checkpoint=save_checkpoint),
    )

    from app.agent import executor_service
    from app.llm import llm_call_service

    monkeypatch.setattr(executor_service, "build_task_prompt", AsyncMock(return_value="Sample"))
    monkeypatch.setattr(executor, "build_context_instructions", AsyncMock(return_value="system"))
    monkeypatch.setattr(executor, "current_content", AsyncMock(return_value="Sample"))
    monkeypatch.setattr(
        executor.session_binding,
        "get_or_create_session_id",
        # A newer task may have advanced the shared binding while this checkpoint
        # was interrupted. The resumed compare-and-swap must still use its origin.
        AsyncMock(return_value="session-newer"),
    )
    monkeypatch.setattr(executor.session_binding, "follow_rotation", AsyncMock())
    monkeypatch.setattr(executor.client, "ensure_session", AsyncMock())
    monkeypatch.setattr(executor.client, "get_session", AsyncMock(return_value={}))
    session_messages: list[dict[str, object]] = []
    monkeypatch.setattr(
        executor.client,
        "get_session_messages",
        AsyncMock(side_effect=lambda *_args: list(session_messages)),
    )
    monkeypatch.setattr(
        executor.client,
        "get_run_status",
        AsyncMock(return_value={"status": "running"}),
    )
    start_run = AsyncMock(return_value="run-new")
    monkeypatch.setattr(executor.client, "start_run", start_run)
    monkeypatch.setattr(llm_call_service, "list_calls", AsyncMock(return_value=[]))
    sync_llm_tools = AsyncMock()
    monkeypatch.setattr(executor, "sync_llm_tool_messages", sync_llm_tools)

    async def resumed_events(*_args: object, **_kwargs: object):
        yield {
            "event": "reasoning.available",
            "data": {"text": "Inspecting the workspace."},
        }
        session_messages.extend([
            {
                "id": 20,
                "role": "assistant",
                "tool_calls": [{
                    "id": "call-live",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"pwd"}',
                    },
                }],
            },
            {
                "id": 21,
                "role": "tool",
                "tool_call_id": "call-live",
                "tool_name": "terminal",
                "content": "/workspace",
            },
        ])
        yield {"event": "tool.completed", "data": {"call_id": "call-live"}}
        yield {"event": "assistant.delta", "data": {"delta": "\n\n"}}
        yield {"event": "assistant.delta", "data": {"delta": "do"}}
        yield {"event": "assistant.delta", "data": {"delta": "ne"}}
        yield {"event": "assistant.delta", "data": {"delta": " "}}
        yield {
            "event": "run.completed",
            "data": {"status": "completed", "output": "done"},
        }

    monkeypatch.setattr(executor, "_run_lifecycle_events", resumed_events)

    events = [event async for event in executor.stream(request)]

    start_run.assert_not_awaited()
    save_checkpoint.assert_awaited()
    executor.client.ensure_session.assert_awaited_once()  # type: ignore[attr-defined]
    assert executor.client.ensure_session.await_args.args[1] == "session-tip-2"  # type: ignore[attr-defined]
    assert executor.client.get_session_messages.await_count >= 1  # type: ignore[attr-defined]
    assert all(  # type: ignore[attr-defined]
        call.args == (ANY, "session-tip-2")
        for call in executor.client.get_session_messages.await_args_list
    )
    assert executor.session_binding.follow_rotation.await_args.args[1:] == (  # type: ignore[attr-defined]
        "session-1",
        "session-tip-2",
    )
    sync_llm_tools.assert_not_awaited()
    last_checkpoint = save_checkpoint.await_args.args[0]
    assert last_checkpoint.data["effective_session_id"] == "session-tip-2"
    assert [
        event.message.tool_name
        for event in events
        if event.message is not None and event.message.type == "tool"
    ] == ["thinking", "terminal"]
    assert events[-1].result is not None
    assert events[-1].result.result == "done"
    live_tool = next(
        event.message for event in events
        if event.message is not None and event.message.tool_name == "terminal"
    )
    terminal_tool = next(
        message for message in events[-1].result.messages if message.tool_name == "terminal"
    )
    checkpoint_tool = next(
        message for message in last_checkpoint.result.messages if message.tool_name == "terminal"
    )
    assert live_tool.tool_call_external_id == "call-live"
    assert terminal_tool.tool_call_external_id == live_tool.tool_call_external_id
    assert checkpoint_tool.tool_call_external_id == live_tool.tool_call_external_id
    assert checkpoint_tool.stream_id == live_tool.stream_id == terminal_tool.stream_id
    live_thought = next(
        event.message for event in events
        if event.message is not None and event.message.tool_name == "thinking"
    )
    checkpoint_thought = next(
        message for message in last_checkpoint.result.messages if message.tool_name == "thinking"
    )
    assert live_thought.stream_id
    assert live_thought.stream_id == checkpoint_thought.stream_id
    assert live_thought.stream_mode == checkpoint_thought.stream_mode == "snapshot"
    live_text = [
        event.message for event in events
        if event.message is not None and event.message.type == "text"
    ]
    assert [message.content for message in live_text] == ["do", "done", "done "]
    assert live_text[0].stream_id == live_text[1].stream_id
    assert all(message.stream_mode == "snapshot" for message in live_text)
