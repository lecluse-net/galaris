from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Literal
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

# pyright: reportPrivateUsage=false

from app.agent.contracts import (
    AgentDriverError,
    AgentEvent,
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    ExecutionResult,
    ResolvedModel,
)
from app.llm import llm_call_service
from bridge.hermes import driver as hermes_driver
from bridge.hermes import executor, kanban
from bridge.hermes.driver import HermesAgentDriver


def _request(
    *,
    effort: Literal["standard", "high"] = "high",
    execution_strategy: str = "kanban",
    checkpoint: AgentRunCheckpoint | None = None,
    save_progress: AsyncMock | None = None,
    save_checkpoint: AsyncMock | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=7,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="hermes",
            driver_config={
                "url": "http://hermes:8642/v1",
                "api_key": "secret",
                "model": "hermes-agent",
                "kanban": {
                    "transport": "legacy",
                    "board": "default",
                    "assignee": "default",
                    "workspace_path": "/opt/data/galaris",
                },
            },
        ),
        driver_code="hermes",
        effort=effort,
        objective="Produce the requested report",
        model=ResolvedModel(
            id=42,
            code="reasoning-model",
            model_name="provider/reasoning-model",
            label="Reasoning model",
            requested_effort=effort,
        ),
        execution_strategy=execution_strategy,
        label="Research report",
        resume_checkpoint=checkpoint,
        control=AgentRunControl(
            save_progress=save_progress,
            save_checkpoint=save_checkpoint,
        ),
    )


@pytest.mark.asyncio
async def test_driver_rejects_taskless_requests() -> None:
    request = replace(_request(), task_id=None)
    driver = HermesAgentDriver()

    with pytest.raises(AgentDriverError, match="requires a durable Galaris Task"):
        await driver.run(request)

    with pytest.raises(AgentDriverError, match="requires a durable Galaris Task"):
        async for _event in driver.stream(request):
            pass


@pytest.mark.asyncio
async def test_high_effort_card_is_correlated_checkpointed_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import executor_service

    save_checkpoint = AsyncMock()
    request = _request(save_checkpoint=save_checkpoint)
    create = AsyncMock(
        return_value={"task": {"id": "t_deadbeef", "status": "ready"}}
    )
    dispatch = AsyncMock()
    get = AsyncMock(
        side_effect=[
            {
                "task": {
                    "id": "t_deadbeef",
                    "status": "running",
                    "current_run_id": 12,
                    "consecutive_failures": 0,
                }
            },
            {
                "task": {
                    "id": "t_deadbeef",
                    "status": "done",
                    "current_run_id": None,
                    "consecutive_failures": 0,
                    "latest_summary": "The report is ready.",
                },
                "runs": [
                    {
                        "id": 12,
                        "status": "completed",
                        "summary": "The report is ready.",
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(
        executor_service,
        "build_task_prompt",
        AsyncMock(return_value="human prompt"),
    )
    monkeypatch.setattr(
        kanban,
        "build_context_instructions",
        AsyncMock(return_value="system prompt"),
    )
    monkeypatch.setattr(kanban, "hermes_context_values", lambda _request: {})
    monkeypatch.setattr(kanban.manager, "create_kanban_task", create)
    monkeypatch.setattr(kanban.manager, "dispatch_kanban", dispatch)
    monkeypatch.setattr(kanban.manager, "get_kanban_task", get)
    monkeypatch.setattr(llm_call_service, "list_calls", AsyncMock(return_value=[]))
    sync_llm_tools = AsyncMock()
    monkeypatch.setattr(executor, "sync_llm_tool_messages", sync_llm_tools)
    monkeypatch.setattr(kanban.asyncio, "sleep", AsyncMock())

    events = [event async for event in kanban._stream(request)]

    terminal_events = [event for event in events if event.kind == "result"]
    assert len(terminal_events) == 1
    terminal = terminal_events[0].result
    assert terminal is not None
    assert terminal.success is True
    assert terminal.result == "The report is ready."
    assert terminal.metadata["runtime_kind"] == "kanban"
    assert terminal.metadata["runtime_run_id"] == "t_deadbeef"
    assert "kanban_complete" in terminal.tools_used
    payload = create.await_args.kwargs["payload"]
    assert payload["assignee"] == "default"
    assert payload["workspace_path"] == "/opt/data/galaris"
    assert str(request.id) in payload["body"]
    assert '"llm_id": 42' in payload["body"]
    assert dispatch.await_args.kwargs["transport"] == "legacy"
    statuses = [call.args[0].status for call in save_checkpoint.await_args_list]
    assert statuses == ["creating", "ready", "running", "done", "done"]
    running_checkpoint = next(
        call.args[0]
        for call in save_checkpoint.await_args_list
        if call.args[0].status == "running"
    )
    assert running_checkpoint.result is not None
    assert running_checkpoint.result.metadata["trace_source"] == "kanban"
    assert running_checkpoint.result.messages[0].tool_name == "hermes_kanban"
    sync_llm_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_kanban_publishes_live_llm_trace_and_keeps_it_when_session_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    save_progress = AsyncMock()
    save_checkpoint = AsyncMock()
    request = _request(
        save_progress=save_progress,
        save_checkpoint=save_checkpoint,
    )
    call = SimpleNamespace(
        id=uuid4(),
        reasoning="",
        tool_calls=[
            {
                "id": "tool-1",
                "name": "mcp__galaris__galaris_search",
                "arguments": {"query": "live trace"},
                "status": "requested",
            }
        ],
        cost=0.04,
        error=None,
    )
    poll = 0

    async def get_kanban_task(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal poll
        poll += 1
        if poll == 1:
            call.reasoning = "Inspect the available sources."
            return {
                "task": {
                    "id": "t_deadbeef",
                    "status": "running",
                    "current_run_id": 12,
                }
            }
        if poll == 2:
            call.reasoning = "Inspect the available sources, then compare them."
            call.tool_calls[0].update(
                {
                    "status": "completed",
                    "result": {"items": 3},
                }
            )
            return {
                "task": {
                    "id": "t_deadbeef",
                    "status": "running",
                    "current_run_id": 12,
                }
            }
        return {
            "task": {
                "id": "t_deadbeef",
                "status": "done",
                "latest_summary": "Finished.",
            },
            "runs": [
                {
                    "id": 12,
                    "status": "completed",
                    "summary": "Finished.",
                    "metadata": {"worker_session_id": "worker-session-12"},
                }
            ],
        }

    async def list_calls(*, task_id: object = None, limit: int = 200):
        del task_id, limit
        return [] if poll == 0 else [call]

    monkeypatch.setattr(
        kanban,
        "_build_card_body",
        AsyncMock(return_value=("human prompt", "system prompt", "card body")),
    )
    monkeypatch.setattr(
        kanban.manager,
        "create_kanban_task",
        AsyncMock(return_value={"task": {"id": "t_deadbeef", "status": "ready"}}),
    )
    monkeypatch.setattr(kanban.manager, "dispatch_kanban", AsyncMock())
    monkeypatch.setattr(kanban.manager, "get_kanban_task", get_kanban_task)
    monkeypatch.setattr(llm_call_service, "list_calls", list_calls)
    monkeypatch.setattr(
        executor.client,
        "get_session_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        executor.client,
        "get_session",
        AsyncMock(return_value={"ended_at": "2026-07-22T21:00:00+00:00"}),
    )
    monkeypatch.setattr(kanban.asyncio, "sleep", AsyncMock())

    events = [event async for event in kanban._stream(request)]

    save_progress.assert_awaited_once()
    live = save_progress.await_args.args[0]
    assert live.metadata["trace_source"] == "llm_calls"
    assert live.metadata["trace_provisional"] is True
    assert [(message.tool_name, message.content) for message in live.messages] == [
        ("thinking", "Inspect the available sources, then compare them."),
        ("search", '{"items": 3}'),
    ]
    terminal = events[-1].result
    assert terminal is not None
    assert terminal.metadata["trace_source"] == "llm_calls"
    assert terminal.metadata["trace_provisional"] is False
    assert terminal.metadata["trace_reconciled"] is False
    assert terminal.messages[0].tool_name == "thinking"
    assert terminal.messages[0].content.endswith("then compare them.")
    executor.client.get_session_messages.assert_awaited_once_with(  # type: ignore[attr-defined]
        ANY,
        "worker-session-12",
    )


@pytest.mark.asyncio
async def test_kanban_replaces_provisional_progress_with_terminal_hermes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(save_checkpoint=AsyncMock())
    detail = {
        "task": {
            "id": "t_deadbeef",
            "status": "done",
            "latest_summary": "Canonical result.",
        },
        "runs": [
            {
                "id": 15,
                "status": "completed",
                "summary": "Canonical result.",
                "metadata": {"worker_session_id": "worker-session-15"},
            }
        ],
    }
    session_messages = [
        {"id": 1, "role": "user", "content": "work kanban task t_deadbeef"},
        {
            "id": 2,
            "role": "assistant",
            "content": "",
            "reasoning": "Canonical Hermes reasoning.",
            "tool_calls": [
                {
                    "id": "call-15",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"pwd"}',
                    },
                }
            ],
        },
        {
            "id": 3,
            "role": "tool",
            "tool_call_id": "call-15",
            "tool_name": "terminal",
            "content": "/opt/data",
        },
    ]
    monkeypatch.setattr(
        kanban,
        "_build_card_body",
        AsyncMock(return_value=("human prompt", "system prompt", "card body")),
    )
    monkeypatch.setattr(
        kanban.manager,
        "create_kanban_task",
        AsyncMock(return_value={"task": {"id": "t_deadbeef", "status": "ready"}}),
    )
    monkeypatch.setattr(kanban.manager, "dispatch_kanban", AsyncMock())
    monkeypatch.setattr(
        kanban.manager,
        "get_kanban_task",
        AsyncMock(return_value=detail),
    )
    monkeypatch.setattr(llm_call_service, "list_calls", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        executor.client,
        "get_session_messages",
        AsyncMock(return_value=session_messages),
    )
    monkeypatch.setattr(
        executor.client,
        "get_session",
        AsyncMock(return_value={"ended_at": "2026-07-22T21:00:00+00:00"}),
    )

    events = [event async for event in kanban._stream(request)]

    terminal = events[-1].result
    assert terminal is not None
    assert terminal.metadata["trace_source"] == "hermes_session"
    assert terminal.metadata["trace_provisional"] is False
    assert terminal.metadata["trace_reconciled"] is True
    assert "hermes_kanban" not in terminal.tools_used
    assert [(message.tool_name, message.content) for message in terminal.messages[:2]] == [
        ("thinking", "Canonical Hermes reasoning."),
        ("terminal", "/opt/data"),
    ]
    assert terminal.result == "Canonical result."


@pytest.mark.asyncio
async def test_kanban_resume_uses_the_transport_frozen_in_its_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_checkpoint = AsyncMock()
    checkpoint = AgentRunCheckpoint(
        driver_code="hermes",
        runtime_run_id="t_cafebabe",
        status="running",
        result=ExecutionResult(prompt="prior"),
        data={
            "execution_strategy": "kanban",
            "transport": "legacy",
            "board": "default",
            "assignee": "default",
            "workspace_path": "/opt/data/galaris",
            "idempotency_key": "galaris:frozen",
            "prior_llm_call_ids": [],
        },
    )
    request = _request(checkpoint=checkpoint, save_checkpoint=save_checkpoint)
    create = AsyncMock()
    dispatch = AsyncMock()
    get = AsyncMock(
        return_value={
            "task": {
                "id": "t_cafebabe",
                "status": "done",
                "result": "Resumed result",
            }
        }
    )
    monkeypatch.setattr(
        kanban,
        "_build_card_body",
        AsyncMock(return_value=("human prompt", "system prompt", "card body")),
    )
    monkeypatch.setattr(kanban.manager, "create_kanban_task", create)
    monkeypatch.setattr(kanban.manager, "dispatch_kanban", dispatch)
    monkeypatch.setattr(kanban.manager, "get_kanban_task", get)
    monkeypatch.setattr(llm_call_service, "list_calls", AsyncMock(return_value=[]))

    events = [event async for event in kanban._stream(request)]

    create.assert_not_awaited()
    dispatch.assert_awaited_once_with("alice", transport="legacy")
    get.assert_awaited_once_with("alice", "t_cafebabe", transport="legacy")
    terminal = events[-1].result
    assert terminal is not None
    assert terminal.result == "Resumed result"


@pytest.mark.asyncio
async def test_driver_disables_new_kanban_runs_but_preserves_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_run = AsyncMock(return_value=ExecutionResult(prompt="direct", result="direct"))
    kanban_run = AsyncMock(return_value=ExecutionResult(prompt="kanban", result="kanban"))
    monkeypatch.setattr(executor, "run", direct_run)
    monkeypatch.setattr(kanban, "run", kanban_run)
    driver = HermesAgentDriver()

    standard = _request(effort="standard", execution_strategy="direct")
    high = _request()
    legacy_high = _request(
        checkpoint=AgentRunCheckpoint(
            driver_code="hermes",
            runtime_run_id="legacy-v1-run",
            status="running",
            data={"session_id": "legacy-session"},
        )
    )
    resumed_kanban = _request(
        checkpoint=AgentRunCheckpoint(
            driver_code="hermes",
            runtime_run_id="t_existing",
            status="running",
            data={"execution_strategy": "kanban"},
        )
    )

    assert (await driver.run(standard)).result == "direct"
    assert (await driver.run(high)).result == "direct"
    assert (await driver.run(legacy_high)).result == "direct"
    assert (await driver.run(resumed_kanban)).result == "kanban"

    monkeypatch.setattr(hermes_driver, "HERMES_HIGH_KANBAN_ENABLED", True)
    assert (
        await driver.run(_request(execution_strategy="direct"))
    ).result == "kanban"

    assert direct_run.await_count == 3
    assert kanban_run.await_count == 2
    assert kanban_run.await_args.args[0].execution_strategy == "kanban"


@pytest.mark.asyncio
async def test_driver_stream_routes_new_high_directly_while_kanban_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def direct_stream(_request: AgentRunRequest):
        yield AgentEvent.from_result(ExecutionResult(prompt="direct", result="direct"))

    async def kanban_stream(_request: AgentRunRequest):
        yield AgentEvent.from_result(ExecutionResult(prompt="kanban", result="kanban"))

    monkeypatch.setattr(executor, "stream", direct_stream)
    monkeypatch.setattr(kanban, "stream", kanban_stream)

    events = [event async for event in HermesAgentDriver().stream(_request())]

    assert events[-1].result is not None
    assert events[-1].result.result == "direct"
