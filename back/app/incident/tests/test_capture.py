"""Integration tests for failure capture at existing runtime boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
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
