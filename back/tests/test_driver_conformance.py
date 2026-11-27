"""Run the shared conformance kit against the installed adapter entry points.

Runtime I/O is scripted; the driver itself and portable envelope are real.
"""
import asyncio
from contextlib import aclosing
from dataclasses import replace
from importlib import import_module
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import AIMessage, AgentEvent, ExecutionResult, ResolvedExecutionTarget
from app.agent.driver_testkit import exercise_driver_stream
from app.agent.registry import all_driver_specs, create_driver
from app.agent.tests.test_driver_testkit import _request


_DRIVER_CODES = ("internal", "claude_embedded", "hermes", "openai_messages")


@pytest.mark.asyncio
@pytest.mark.parametrize("code", _DRIVER_CODES)
@pytest.mark.parametrize("failure", [False, True])
async def test_registered_adapter_preserves_stream_identity_and_closes(monkeypatch, code, failure):
    driver = create_driver(code)
    initial = _request()
    request = replace(
        initial, driver_code=code, attempt_id=uuid4(),
        agent=replace(initial.agent, driver_code=code),
        target=ResolvedExecutionTarget(provider_code=code, target_ref=f"harness:{uuid4()}"),
    )
    closed = False
    seen = []

    async def stream(received):
        nonlocal closed
        seen.append(received)
        try:
            yield AgentEvent.from_message(AIMessage(type="text", content="partial"))
            yield AgentEvent.from_result(ExecutionResult(prompt="", result="partial", success=not failure))
        finally:
            closed = True

    if code == "openai_messages":
        from app.harnesses.driver import OpenAIMessagesDriver

        async def controlled_run(_self, received, *, on_progress=None):
            assert received.to_envelope() == request.to_envelope()
            async with aclosing(stream(received.to_envelope())) as events:
                async for event in events:
                    if event.message is not None:
                        await on_progress(event.message)
                    if event.result is not None:
                        return event.result

        monkeypatch.setattr(OpenAIMessagesDriver, "_managed_run", controlled_run)
    elif code == "claude_embedded":
        from app.harness import claude_driver

        def sdk_stream(origin, **options):
            assert options["prompt"] == request.objective
            assert origin.model_id == request.model.id and origin.model_code == request.model.code
            return stream(origin)

        monkeypatch.setattr(claude_driver.executor_service, "build_task_prompt", AsyncMock(return_value=request.objective))
        monkeypatch.setattr(claude_driver, "resolve_ssh_connection", AsyncMock(return_value=None))
        monkeypatch.setattr(claude_driver, "build_mounted_mcp_client", AsyncMock(return_value=None))
        monkeypatch.setattr(claude_driver, "aggregate_llm_run_usage", AsyncMock(return_value=None))
        monkeypatch.setattr(claude_driver, "stream_inference", sdk_stream)
    else:
        path = "app.harness.executor" if code == "internal" else "bridge.hermes.executor"
        monkeypatch.setattr(import_module(path), "stream", stream)

    async with asyncio.timeout(5):
        report = await exercise_driver_stream(driver, request)
    assert closed
    assert report.message_events == 1
    assert report.terminal_result.success is not failure
    identity = seen[0].identity if code == "openai_messages" else seen[0]
    assert identity.task_id == request.task_id
    assert identity.run_id == request.run_id
    assert identity.attempt_id == request.attempt_id


def test_new_driver_requires_a_conformance_case():
    assert {spec.code for spec in all_driver_specs()} == set(_DRIVER_CODES)
