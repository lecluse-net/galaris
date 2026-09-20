from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest

from app.agent.contracts import (
    AIMessage,
    AgentDriverSpec,
    AgentEvent,
    AgentRunRequest,
    AgentSnapshot,
    DriverPipelinePolicy,
    ExecutionResult,
    ResolvedModel,
    ToolExposureProfile,
)
from pydantic import ValidationError
from app.agent.driver_testkit import exercise_driver_stream


SPEC = AgentDriverSpec(
    code="fixture",
    label_key="fixture",
    factory_path="fixture:create",
    tool_profile=ToolExposureProfile(),
    pipeline_policy=DriverPipelinePolicy(use_planner=False, use_briefing=False),
)


def _request() -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=4,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="fixture",
            driver_config={"api_key": "must-not-leak"},
        ),
        driver_code="fixture",
        effort="standard",
        objective="Produce a report",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
    )


@dataclass(frozen=True)
class _Driver:
    spec: AgentDriverSpec = SPEC

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        _ = request
        return ExecutionResult(prompt="p", result="done")

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        _ = request
        yield AgentEvent.from_message(AIMessage(type="text", content="done"))
        yield AgentEvent.from_result(ExecutionResult(prompt="p", result="done"))

    async def cancel(self, run_id: UUID) -> None:
        _ = run_id


@pytest.mark.asyncio
async def test_driver_testkit_validates_stream_and_secret_free_envelope() -> None:
    report = await exercise_driver_stream(_Driver(), _request())

    assert report.message_events == 1
    assert report.terminal_result.result == "done"
    assert "must-not-leak" not in report.envelope_json
    assert '"schema_version":"galaris.agent-run/v1"' in report.envelope_json


@pytest.mark.asyncio
async def test_driver_testkit_rejects_events_after_terminal() -> None:
    class Broken(_Driver):
        async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
            _ = request
            yield AgentEvent.from_result(ExecutionResult(prompt="p", result="done"))
            yield AgentEvent.from_message(AIMessage(type="text", content="late"))

    with pytest.raises(RuntimeError, match="after its terminal"):
        await exercise_driver_stream(Broken(), _request())


def test_portable_envelope_rejects_oversized_dynamic_history() -> None:
    request = _request()
    oversized = [{"role": "user", "content": "x" * 600_001}]

    with pytest.raises(ValidationError, match="600000 UTF-8 bytes"):
        replace(request, conversation_history=oversized).to_envelope()


def test_portable_envelope_projects_known_sender_and_room_context() -> None:
    request = replace(
        _request(),
        messenger_connection_id=19,
        message_platform="internal",
        message_group_id="chat:direct:1:1",
        task_data={
            "language": "fr",
            "room_label": "Aster Test",
            "sender.user_id": "user:1",
            "sender.nickname": "Nicolas",
            "message_type": "direct",
        },
    )

    context = request.to_envelope().messaging_context

    assert context["connection_id"] == "19"
    assert context["room_id"] == "chat:direct:1:1"
    assert context["room_label"] == "Aster Test"
    assert context["user_id"] == "user:1"
    assert context["user_name"] == "Nicolas"


def test_portable_envelope_uses_the_complete_executor_system_prompt() -> None:
    envelope = replace(
        _request(),
        executor_system_prompt="Canonical identity and personality prompt",
        system_instructions="Provider contribution already included in the canonical prompt",
    ).to_envelope()

    assert envelope.system_instructions == "Canonical identity and personality prompt"
