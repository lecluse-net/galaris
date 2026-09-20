"""Integration tests for failure capture at existing runtime boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness import runtime
from app.incident.models import FailureIncident, FailureIncidentTrace
from app.llm import llm_call_service
from app.llm.models import LLMCall


async def _request(db: AsyncSession):
    from app.agent.contracts import AgentRunRequest, AgentSnapshot, ResolvedModel
    from app.agent.models import Agent, Title
    from app.task.models import Task, TaskAttempt

    title = Title(label="Mx", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(code=f"journal-{uuid4().hex[:8]}", first_name="Ari", last_name="Test", title_id=title.id)
    task = Task(label="Synthetic journal recovery", objective="<p>Check recovery.</p>")
    db.add_all([agent, task])
    await db.flush()
    attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", worker_id="test", lease_token=uuid4())
    db.add(attempt)
    await db.commit()
    return AgentRunRequest(
        run_id=uuid4(), task_id=task.id, attempt_id=attempt.id,
        agent=AgentSnapshot(id=agent.id, code=agent.code, first_name="Ari", last_name="Test", driver_code="internal"),
        driver_code="internal", effort="standard", objective="<p>Check recovery.</p>",
        model=ResolvedModel(id=1, code="test", model_name="test/model", label="Test", requested_effort="standard"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_retried_run_preserves_each_attempt_without_duplicate_observations(db, monkeypatch, legacy):
    from app.agent import facade
    from app.agent.contracts import ExecutionResult, ReasoningDegenerationError
    from app.incident import service
    from app.task.models import TaskAttempt
    from core import failure_journal

    monkeypatch.setattr(failure_journal, "_record_isolated", service.record_failure_isolated)
    request = await _request(db)
    first = RuntimeError("Responses stream ended before its terminal event")
    if legacy:
        await service.record_failure(db, failure_journal.FailureEvent(
            idempotency_key=f"agent-run:{request.run_id}:terminal", kind="llm", phase="agent_run",
            task_id=request.task_id, task_attempt_id=request.attempt_id, run_uuid=request.run_id,
            error_type=type(first).__name__, error_message=str(first),
        ))
        await db.commit()
    await facade._record_run_outcome(request, ExecutionResult(prompt="synthetic", success=False, result=str(first)), exc=first)
    await facade._record_run_outcome(request, ExecutionResult(prompt="synthetic", success=False, result=str(first)), exc=first)
    attempt = TaskAttempt(task_id=request.task_id, attempt_number=2, phase="DISPATCH", worker_id="test", lease_token=uuid4())
    db.add(attempt)
    await db.commit()
    second = ReasoningDegenerationError("Repeated reasoning")
    resumed = replace(request, attempt_id=attempt.id)
    await facade._record_run_outcome(resumed, ExecutionResult(prompt="synthetic", success=False, result=str(second)), exc=second)
    await facade._record_run_outcome(resumed, ExecutionResult(prompt="synthetic", success=False, result=str(second)), exc=second)
    rows = list(await db.scalars(select(FailureIncident).where(FailureIncident.run_uuid == request.run_id)))
    assert len(rows) == 2
    assert {row.error_type for row in rows} == {"RuntimeError", "ReasoningDegenerationError"}
    assert {row.task_attempt_id for row in rows} == {request.attempt_id, attempt.id}
    assert all(row.will_retry is None for row in rows)
    monkeypatch.setattr(failure_journal, "_mark_recovered", service.mark_run_recovered_isolated)
    await facade._record_run_outcome(resumed, ExecutionResult(prompt="synthetic", success=True, result="Recovered"))
    for row in rows:
        await db.refresh(row)
        assert row.recovered_at is not None


@pytest.mark.asyncio
async def test_native_diagnostic_is_durable_private_and_enriched_without_duplicates(db, monkeypatch):
    from fastmcp.exceptions import ToolError
    from app.agent import facade
    from app.agent.contracts import AIMessage
    from pydantic_ai.messages import ToolReturnPart
    from app.incident import service
    from app.tools import mcp_loader
    from core import failure_journal
    from core.database import get_db
    from app.task.models import Task
    from sqlalchemy import update

    monkeypatch.setattr(failure_journal, "_record_isolated", service.record_failure_isolated)
    request = await _request(db)

    async def broken(ctx):
        await get_db().execute(update(Task).where(Task.id == ctx.task_id).values(label="Must roll back"))
        raise ValueError("Invalid offset 900; password=synthetic-password-value; https://example.test/a?signature=synthetic-signature")

    definition = mcp_loader.McpToolDefinition(
        tool_code="file_sharing", name="file_read", description="Read", required_capabilities=frozenset(), function=broken,
    )
    monkeypatch.setattr("app.agent.effective_capabilities", AsyncMock(return_value={"execute"}))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(definition,)))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value="en"))
    wrapped = mcp_loader._wrap_tool(definition, mcp_loader.McpToolContext(agent_id=request.agent.id, runtime="internal", task_id=request.task_id))
    with pytest.raises(ToolError) as error:
        await wrapped()
    public_message = str(error.value)
    assert "Invalid offset 900" not in public_message
    assert "synthetic-password-value" not in public_message
    message = AIMessage(type="tool", tool_name="file_read", content=public_message, success=False, tool_call_external_id="call-synthetic")
    observer = runtime.Agent(
        llm=SimpleNamespace(code="synthetic"), task_id=request.task_id,
        agent_id=request.agent.id, agent_run_id=request.run_id,
    )
    await observer._record_tool_failure(
        FunctionToolResultEvent(ToolReturnPart(tool_name="file_read", tool_call_id="call-synthetic", content={
            "schema": "galaris.tool-error/v1", "status": "error", "error": public_message,
        })), None, message,
    )
    await facade._record_tool_failure(request, message, sequence=1)
    await facade._record_tool_failure(request, message, sequence=1)
    rows = list(await db.scalars(select(FailureIncident).where(FailureIncident.task_id == request.task_id)))
    assert len(rows) == 1
    row = rows[0]
    assert row.run_uuid == request.run_id
    assert row.task_attempt_id == request.attempt_id
    assert row.error_code == "invalid_arguments"
    trace = await db.get(FailureIncidentTrace, row.id)
    assert trace is not None
    assert "Invalid offset 900" in str(trace.payload)
    assert "synthetic-password-value" not in str(trace.payload)
    assert "synthetic-signature" not in str(trace.payload)
    assert trace.payload["message"]["tool_call_external_id"] == "call-synthetic"
    assert trace.payload["native_failure"]["exceptions"][0]["locations"]
    assert trace.payload["tool_result"]["tool_call_id"] == "call-synthetic"
    assert await db.scalar(select(Task.label).where(Task.id == request.task_id)) == "Synthetic journal recovery"


@pytest.mark.asyncio
async def test_old_tool_checkpoint_does_not_duplicate_its_failure_after_upgrade(db, monkeypatch):
    from app.agent import facade
    from app.agent.contracts import AIMessage
    from app.incident import service
    from core import failure_journal

    monkeypatch.setattr(failure_journal, "_record_isolated", service.record_failure_isolated)
    request = await _request(db)
    message = "Native call rejected. Error reference: abc123def456"
    old = await service.record_failure(db, failure_journal.FailureEvent(
        idempotency_key=f"tool-call:{request.run_id}:historical-call",
        kind="tool", error_message=message, run_uuid=request.run_id,
        task_id=request.task_id, tool_call_external_id="historical-call",
        trace={"historical": True},
    ))
    await db.commit()
    await facade._record_tool_failure(request, AIMessage(
        type="tool", tool_name="file_read", content=message, success=False,
        tool_call_external_id="historical-call",
    ), sequence=1)
    rows = list(await db.scalars(select(FailureIncident).where(FailureIncident.run_uuid == request.run_id)))
    assert [row.id for row in rows] == [old.id]
    trace = await db.get(FailureIncidentTrace, old.id)
    assert trace.payload["historical"] is True


def test_administrative_exception_diagnostics_redact_quoted_secrets_and_urls():
    from app.tools.tool_errors import exception_diagnostic

    exception = ValueError('Offset refused: {"password": "hidden words", "token": "hidden-token"}; Authorization: Bearer hidden-bearer; https://user:hidden-pass@example.test/?signature=hidden-signature')
    diagnostic = str(exception_diagnostic(exception))
    assert "Offset refused" in diagnostic
    assert "hidden" not in diagnostic


@pytest.mark.asyncio
async def test_failed_llm_finalization_snapshots_full_trace(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = LLMCall(
        id=uuid4(),
        provider_name="Provider",
        provider_code="provider",
        requested_model="model",
        effective_model="model",
        status="running",
        stream=False,
        request_messages=[{"role": "user", "content": "private prompt"}],
        prompt="private prompt",
        system_prompt="private system prompt",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.commit()
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())

    await llm_call_service.finalize_call(
        call.id,
        trace={"response_text": "partial", "usage": {"total_tokens": 3}},
        raw_response='{"error":"provider failure"}',
        status="error",
        error="ProviderError: unavailable",
    )

    incident = await db.scalar(
        select(FailureIncident).where(
            FailureIncident.llm_call_id == call.id
        )
    )
    assert incident is not None
    trace = await db.get(FailureIncidentTrace, incident.id)
    assert trace is not None
    assert trace.payload["llm_call"]["prompt"] == "private prompt"
    assert trace.payload["llm_call"]["raw_response"] == '{"error":"provider failure"}'


def test_retry_prompt_keeps_tool_call_identifier() -> None:
    class RetryPromptPart:
        tool_name = "skill_galaris_read_file"
        tool_call_id = "call-42"
        data = "Unknown section"

    call_event = cast(
        FunctionToolCallEvent,
        SimpleNamespace(
            part=SimpleNamespace(
                tool_name="skill_galaris_read_file",
                tool_call_id="call-42",
                args={"section": "missing"},
            )
        ),
    )
    result_event = cast(
        FunctionToolResultEvent,
        SimpleNamespace(part=RetryPromptPart()),
    )

    message = runtime._function_to_message(  # pyright: ignore[reportPrivateUsage]
        result_event,
        call_event,
    )

    assert message.success is False
    assert message.tool_call_external_id == "call-42"
    assert message.tool_retry_limit == 3
