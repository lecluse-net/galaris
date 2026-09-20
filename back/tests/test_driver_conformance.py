"""Run the shared conformance kit against the installed adapter entry points.

Runtime I/O is scripted; the driver itself and portable envelope are real.
"""
import asyncio
from dataclasses import replace
from importlib import import_module
from uuid import uuid4

import pytest

from app.agent import AIMessage, AgentEvent, ExecutionResult, ResolvedExecutionTarget
from app.agent.driver_testkit import exercise_driver_stream
from app.agent.registry import all_driver_specs, create_driver
from app.agent.tests.test_driver_testkit import _request


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["internal", "hermes", "openai_messages"])
@pytest.mark.parametrize("failure", [False, True])
async def test_registered_adapter_preserves_stream_identity_and_closes(monkeypatch, code, failure):
    driver = create_driver(code)
    request = replace(
        _request(), driver_code=code,
        agent=replace(_request().agent, driver_code=code),
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

        class Client:
            async def stream(self, envelope):
                async for event in stream(envelope):
                    yield event

        async def client(_self, received):
            assert received.to_envelope() == request.to_envelope()
            return Client()

        monkeypatch.setattr(OpenAIMessagesDriver, "_client", client)
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


def test_new_driver_requires_a_conformance_case():
    assert {spec.code for spec in all_driver_specs()} == {"internal", "hermes", "openai_messages"}
