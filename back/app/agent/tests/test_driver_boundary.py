"""Exercise the real registry and facade with a hostile, runtime-neutral harness."""

import asyncio
import importlib
import itertools
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import facade, registry
from app.agent.contracts import (
    AIMessage, AgentDriverSpec, AgentEvent, AgentRunRequest, AgentSnapshot,
    DriverPipelinePolicy, ExecutionResult, ResolvedModel, ToolExposureProfile,
)
from app.agent.driver_testkit import ScriptedDriver


def with_policy(request, **settings):
    from app.agent import HarnessExecutionPolicy, negotiate_capabilities
    from app.agent.contracts import ResolvedExecutionTarget
    return replace(request, target=ResolvedExecutionTarget(
        provider_code=request.driver_code, target_ref="test:runtime",
        descriptor=negotiate_capabilities({"execute", "streaming"}, policy=HarnessExecutionPolicy(**settings)),
    ))


@pytest.fixture
def boundary(monkeypatch):
    from app.agent.contracts import HarnessExecutionPolicy
    from app.agent.harness_port import harness_selection_port

    monkeypatch.setattr(harness_selection_port, "configuration", AsyncMock(return_value=(HarnessExecutionPolicy(), 0)))
    spec = AgentDriverSpec(
        code="hostile-test", label_key="test", factory_path="test:factory",
        tool_profile=ToolExposureProfile(),
        pipeline_policy=DriverPipelinePolicy(use_planner=False, use_briefing=False),
    )
    driver = ScriptedDriver(spec)
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    monkeypatch.setattr(registry, "_resolve_entrypoint", lambda _: lambda: driver)
    live, semantic, outcome = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.agent.live.publish_live_event", live)
    monkeypatch.setattr(facade, "_publish_run_event", semantic)
    monkeypatch.setattr(facade, "_record_run_outcome", outcome)
    request = AgentRunRequest(
        run_id=uuid4(), task_id=uuid4(),
        agent=AgentSnapshot(id=3, code="test", first_name="Test", last_name="Agent", driver_code=spec.code),
        driver_code=spec.code, effort="standard", objective="Exercise the contract",
        model=ResolvedModel(id=1, code="test", model_name="test", label="Test", requested_effort="standard"),
    )
    return SimpleNamespace(driver=driver, request=request, live=live, semantic=semantic, outcome=outcome)


def terminal():
    return AgentEvent.from_result(ExecutionResult(prompt="", result="done"))


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["run", "stream"])
async def test_failed_harness_preparation_prevents_driver_effects(boundary, monkeypatch, entrypoint):
    from app.agent.harness_port import harness_selection_port

    monkeypatch.setattr(
        harness_selection_port, "prepare_execution",
        AsyncMock(side_effect=RuntimeError("Skill synchronization failed")),
    )
    invoked = False

    async def forbidden_stream(_request):
        nonlocal invoked
        invoked = True
        yield terminal()

    monkeypatch.setattr(boundary.driver, "stream", forbidden_stream)
    with pytest.raises(RuntimeError, match="Skill synchronization failed"):
        if entrypoint == "run":
            await facade.run(boundary.request)
        else:
            async for _event in facade.stream(boundary.request):
                pass
    assert not invoked
    assert [c.kwargs["kind"] for c in boundary.semantic.await_args_list] == ["run.started", "run.failed"]
    assert boundary.outcome.await_args.args[1].success is False


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["run", "stream"])
@pytest.mark.parametrize("tail", ["message", "result", "exception"])
async def test_invalid_tail_never_publishes_success(boundary, entrypoint, tail):
    extra = {
        "message": AgentEvent.from_message(AIMessage(type="text", content="late")),
        "result": terminal(), "exception": RuntimeError("late failure"),
    }[tail]
    boundary.driver.steps = (terminal(), extra)
    received = []
    with pytest.raises(RuntimeError):
        if entrypoint == "run":
            await facade.run(boundary.request)
        else:
            async for event in facade.stream(boundary.request):
                received.append(event)
    assert received == []
    assert [c.kwargs["kind"] for c in boundary.semantic.await_args_list] == ["run.started", "run.failed"]
    assert [c.args[0].kind for c in boundary.live.await_args_list] == ["started", "failed"]
    assert boundary.outcome.await_count == 1
    assert boundary.outcome.await_args.args[1].success is False
    assert boundary.driver.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"kind": "message"}, {"kind": "result"},
    {"kind": "message", "result": {"prompt": ""}},
    {"kind": "result", "result": {"prompt": ""}, "message": {"type": "text", "content": "ambiguous"}},
])
async def test_malformed_event_fails_and_closes_driver(boundary, invalid):
    boundary.driver.steps = (invalid, terminal())
    with pytest.raises(ValueError):
        await facade.run(boundary.request)
    assert boundary.driver.closed
    assert boundary.semantic.await_args.kwargs["kind"] == "run.failed"


@pytest.mark.asyncio
async def test_empty_stream_closes_live_activity(boundary):
    with pytest.raises(RuntimeError, match="no terminal"):
        await facade.run(boundary.request)
    assert boundary.live.await_args.args[0].kind == "failed"


@pytest.mark.asyncio
async def test_task_cancellation_is_propagated_and_closes_driver(boundary):
    entered = asyncio.Event()

    # The script's event is a synchronization barrier, with no wall-clock race.
    boundary.driver.steps = (asyncio.Event(),)
    original = boundary.driver.stream

    async def stream(request):
        entered.set()
        async for event in original(request):
            yield event

    boundary.driver.stream = stream
    task = asyncio.create_task(facade.run(boundary.request))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert boundary.driver.closed
    assert boundary.semantic.await_args.kwargs["kind"] == "run.cancelled"
    boundary.outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_streaming_driver_has_same_terminal_contract(boundary, monkeypatch):
    spec = replace(boundary.driver.spec, supports_streaming=False)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    events = [event async for event in facade.stream(boundary.request)]
    assert [event.kind for event in events] == ["result"]
    assert events[0].result.result == "done"
    assert len(boundary.driver.requests) == 1
    received = boundary.driver.requests[0]
    assert received.run_id == boundary.request.run_id
    assert received.objective == boundary.request.objective
    assert received.target.descriptor is not None


@pytest.mark.asyncio
async def test_hanging_terminal_tail_is_bounded(boundary, monkeypatch):
    spec = replace(boundary.driver.spec, stream_close_timeout_seconds=0.01)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    boundary.driver.steps = (terminal(), asyncio.Event())
    with pytest.raises(RuntimeError, match="did not close"):
        await asyncio.wait_for(facade.run(boundary.request), 2)
    assert boundary.driver.closed
    assert boundary.semantic.await_args.kwargs["kind"] == "run.failed"


@pytest.mark.asyncio
async def test_consumer_can_close_stream_while_driver_is_suspended(boundary):
    boundary.driver.steps = (AgentEvent.from_message(AIMessage(type="text", content="progress")), asyncio.Event())
    stream = facade.stream(boundary.request)
    event = await anext(stream)
    assert event.message.content == "progress"
    await stream.aclose()
    assert boundary.driver.closed
    assert boundary.live.await_args.args[0].kind == "cancelled"
    assert all(call.kwargs["kind"] != "run.completed" for call in boundary.semantic.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_valid_result_is_published_once_after_driver_cleanup(boundary, success):
    boundary.driver.steps = (
        AgentEvent.from_message(AIMessage(type="text", content="progress")),
        AgentEvent.from_result(ExecutionResult(prompt="", result="done", success=success)),
    )
    events = []
    async for event in facade.stream(boundary.request):
        if event.kind == "result":
            assert boundary.driver.closed
        events.append(event)
    assert [event.kind for event in events] == ["message", "result"]
    assert events[-1].result.success is success
    assert boundary.outcome.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["run", "stream"])
async def test_invalid_request_is_rejected_before_driver_execution(boundary, entrypoint):
    request = replace(boundary.request, task_id=None)
    with pytest.raises(ValueError, match="durable Task"):
        if entrypoint == "run":
            await facade.run(request)
        else:
            async for _ in facade.stream(request):
                pass
    assert boundary.driver.requests == []


@pytest.mark.asyncio
async def test_taskless_capability_is_available_to_any_driver(boundary, monkeypatch):
    spec = replace(boundary.driver.spec, execution_capabilities=frozenset({"taskless_runs"}))
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    boundary.driver.steps = (terminal(),)
    result = await facade.run(replace(boundary.request, task_id=None))
    assert result.result == "done"


@pytest.mark.asyncio
async def test_mutated_terminal_result_is_revalidated(boundary):
    event = terminal()
    event.result.success = "not-a-boolean"
    boundary.driver.steps = (event,)
    with pytest.raises(ValueError):
        await facade.run(boundary.request)
    assert boundary.driver.closed


@pytest.mark.asyncio
async def test_cancel_is_dispatched_only_when_declared(boundary, monkeypatch):
    with pytest.raises(RuntimeError, match="does not support cancellation"):
        await facade.cancel(boundary.request.driver_code, boundary.request.run_id)
    assert boundary.driver.cancellations == []
    spec = replace(boundary.driver.spec, supports_cancellation=True)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    await facade.cancel(spec.code, boundary.request.run_id)
    assert boundary.driver.cancellations == [boundary.request.run_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["app.harness", "bridge.hermes", "app.harnesses"])
async def test_concrete_adapter_closes_its_runtime_stream(boundary, monkeypatch, module):
    driver = importlib.import_module(f"{module}.driver").create_driver()
    closed = False

    async def runtime_stream(_):
        nonlocal closed
        try:
            yield AgentEvent.from_message(AIMessage(type="text", content="progress"))
            await asyncio.Event().wait()
        finally:
            closed = True

    if module == "app.harnesses":
        monkeypatch.setattr(type(driver), "_client", AsyncMock(return_value=SimpleNamespace(stream=runtime_stream)))
    else:
        monkeypatch.setattr(importlib.import_module(f"{module}.executor"), "stream", runtime_stream)
    stream = driver.stream(boundary.request)
    await anext(stream)
    await stream.aclose()
    assert closed


@pytest.mark.asyncio
async def test_generated_event_sequences_admit_only_one_clean_terminal(boundary):
    from app.agent.driver_testkit import exercise_driver_stream
    from app.agent import HarnessExecutionError

    for length in range(5):
        for sequence in itertools.product("mrx", repeat=length):
            boundary.driver.steps = tuple(
                terminal() if symbol == "r" else
                AgentEvent.from_message(AIMessage(type="text", content="hello")) if symbol == "m" else
                RuntimeError("transport lost") for symbol in sequence
            )
            valid = bool(sequence) and sequence[-1] == "r" and all(symbol == "m" for symbol in sequence[:-1])
            if valid:
                report = await exercise_driver_stream(boundary.driver, boundary.request)
                assert report.message_events == length - 1
            else:
                with pytest.raises(HarnessExecutionError):
                    await exercise_driver_stream(boundary.driver, boundary.request)
            assert boundary.driver.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["message", "result", "total", "total_with_progress"])
async def test_byte_budgets_reject_before_publishing_terminal(boundary, kind):
    from app.agent import HarnessProtocolError
    from app.agent.contracts import AgentRunControl

    if kind == "message":
        boundary.driver.steps = (AgentEvent.from_message(AIMessage(type="text", content="é" * 1024)), terminal())
        policy = {"max_message_bytes": 1024}
    elif kind == "result":
        boundary.driver.steps = (AgentEvent.from_result(ExecutionResult(prompt="", result="é" * 1024)),)
        policy = {"max_result_bytes": 1024}
    else:
        boundary.driver.steps = tuple(AgentEvent.from_message(AIMessage(type="text", content="hello" * 40)) for _ in range(20)) + (terminal(),)
        policy = {"max_stream_bytes": 1024}
    request = with_policy(boundary.request, **policy)
    if kind == "total_with_progress":
        request = replace(request, control=AgentRunControl(save_progress=AsyncMock()))
        original = boundary.driver.stream

        async def with_progress(received):
            async for event in original(received):
                await received.save_progress(ExecutionResult(prompt="", result="progress"))
                yield event

        boundary.driver.stream = with_progress
    scope = "stream" if kind.startswith("total") else kind
    with pytest.raises(HarnessProtocolError, match=f"Harness {scope}.*byte budget"):
        await facade.run(request)
    assert all(call.kwargs["kind"] != "run.completed" for call in boundary.semantic.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", ["execution_timeout_seconds", "idle_timeout_seconds"])
async def test_execution_deadlines_close_stalled_driver(boundary, timeout):
    from app.agent import HarnessExecutionError

    boundary.driver.steps = (asyncio.Event(),)
    with pytest.raises(HarnessExecutionError) as error:
        await facade.run(with_policy(boundary.request, **{timeout: 0.01}))
    assert error.value.failure.code == "timeout"
    assert error.value.failure.retry == "reconcile"
    assert boundary.driver.closed


@pytest.mark.asyncio
async def test_mutating_driver_cannot_change_caller_or_previously_yielded_event(boundary):
    request = replace(boundary.request, task_data={"nested": {"value": "original"}})
    message = AIMessage(type="text", content="original")

    async def hostile(received):
        received.task_data["nested"]["value"] = "corrupted"
        yield AgentEvent.from_message(message)
        message.content = "corrupted"
        yield terminal()

    boundary.driver.stream = hostile
    events = [event async for event in facade.stream(request)]
    assert request.task_data == {"nested": {"value": "original"}}
    assert events[0].message.content == "original"


@pytest.mark.asyncio
async def test_cancellation_uses_active_driver_and_does_not_invent_acknowledgment(boundary, monkeypatch):
    from app.agent.run_control import own_run

    spec = replace(boundary.driver.spec, supports_cancellation=True)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    replacement = ScriptedDriver(spec)
    monkeypatch.setattr(registry, "_resolve_entrypoint", lambda _: lambda: replacement)
    with own_run(boundary.driver, boundary.request):
        receipt = await facade.cancel(spec.code, boundary.request.run_id)
        repeated = await facade.cancel(spec.code, boundary.request.run_id)
    assert receipt.state == "requested"
    assert repeated == receipt
    assert boundary.driver.cancellations == [boundary.request.run_id]
    assert replacement.cancellations == []


@pytest.mark.asyncio
async def test_acknowledging_driver_can_progress_from_requested_to_confirmed(boundary, monkeypatch):
    from app.agent.contracts import HarnessCancellationReceipt

    spec = replace(boundary.driver.spec, supports_cancellation=True)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    boundary.driver.request_cancellation = AsyncMock(side_effect=[
        HarnessCancellationReceipt(run_id=boundary.request.run_id, scope="remote", state="requested"),
        HarnessCancellationReceipt(run_id=boundary.request.run_id, scope="remote", state="confirmed"),
    ])
    assert (await facade.cancel(spec.code, boundary.request.run_id)).state == "requested"
    assert (await facade.cancel(spec.code, boundary.request.run_id)).state == "confirmed"
    assert (await facade.cancel(spec.code, boundary.request.run_id)).state == "confirmed"
    assert boundary.driver.request_cancellation.await_count == 2


@pytest.mark.asyncio
async def test_lost_cancellation_reply_is_unknown(boundary, monkeypatch):
    spec = replace(boundary.driver.spec, supports_cancellation=True, stream_close_timeout_seconds=0.01)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    boundary.driver.cancel = AsyncMock(side_effect=ConnectionError("lost"))
    assert (await facade.cancel(spec.code, boundary.request.run_id)).state == "unknown"


@pytest.mark.asyncio
async def test_concurrent_cancellations_issue_one_control_request(boundary, monkeypatch):
    spec = replace(boundary.driver.spec, supports_cancellation=True)
    boundary.driver.spec = spec
    monkeypatch.setitem(registry._DRIVER_SPECS, spec.code, spec)
    entered, release = asyncio.Event(), asyncio.Event()
    async def cancel(_):
        entered.set()
        await release.wait()
    boundary.driver.cancel = AsyncMock(side_effect=cancel)
    first = asyncio.create_task(facade.cancel(spec.code, boundary.request.run_id))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(facade.cancel(spec.code, boundary.request.run_id))
    release.set()
    assert (await first) == (await second)
    boundary.driver.cancel.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["foreign_checkpoint", "oversized_progress", "oversized_checkpoint"])
async def test_control_callbacks_cannot_bypass_driver_validation(boundary, monkeypatch, fault):
    from app.agent.contracts import AgentRunCheckpoint, AgentRunControl
    from app.agent import HarnessProtocolError
    checkpoint, progress, publish = AsyncMock(), AsyncMock(), AsyncMock()
    request = replace(with_policy(boundary.request, max_result_bytes=1024), control=AgentRunControl(
        save_checkpoint=checkpoint, save_progress=progress, publish_event=publish,
    ))
    boundary.driver.spec = replace(boundary.driver.spec, execution_capabilities=frozenset({"checkpoints"}))
    monkeypatch.setitem(registry._DRIVER_SPECS, boundary.driver.spec.code, boundary.driver.spec)
    async def hostile(received):
        assert received.publish_event is None
        if fault == "foreign_checkpoint":
            await received.save_checkpoint(AgentRunCheckpoint(driver_code="another", runtime_run_id="r", status="running"))
        elif fault == "oversized_checkpoint":
            await received.save_checkpoint(AgentRunCheckpoint(
                driver_code=received.driver_code, runtime_run_id="r", status="running",
                data={"history": "é" * 1024},
            ))
        else:
            await received.save_progress(ExecutionResult(prompt="", result="x" * 2048))
        yield terminal()
    boundary.driver.stream = hostile
    with pytest.raises(HarnessProtocolError):
        await facade.run(request)
    checkpoint.assert_not_awaited()
    progress.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["run", "stream"])
@pytest.mark.parametrize("snapshot_kind", ["progress", "checkpoint"])
async def test_repeated_state_snapshots_do_not_exhaust_output_stream_budget(boundary, monkeypatch, entrypoint, snapshot_kind):
    """Saving growing recovery state must not prematurely stop a valid long run."""
    from app.agent.contracts import AgentRunCheckpoint, AgentRunControl

    progress, checkpoint = AsyncMock(), AsyncMock()
    boundary.driver.spec = replace(boundary.driver.spec, execution_capabilities=frozenset({"checkpoints"}))
    monkeypatch.setitem(registry._DRIVER_SPECS, boundary.driver.spec.code, boundary.driver.spec)
    request = replace(with_policy(boundary.request, max_result_bytes=4096, max_stream_bytes=4096),
        control=AgentRunControl(save_progress=progress, save_checkpoint=checkpoint))

    async def evolving(received):
        for step in range(12):
            partial = ExecutionResult(prompt="context" * 100, result=f"Step {step}")
            if snapshot_kind == "progress":
                await received.save_progress(partial)
            else:
                await received.save_checkpoint(AgentRunCheckpoint(
                    driver_code=received.driver_code, runtime_run_id="r", status="running",
                    data={"history": list(range(step + 1))}, result=partial,
                ))
        yield AgentEvent.from_message(AIMessage(type="text", content="Finished"))
        yield terminal()

    boundary.driver.stream = evolving
    if entrypoint == "run":
        result = await facade.run(request)
    else:
        events = [event async for event in facade.stream(request)]
        assert [event.kind for event in events] == ["message", "result"]
        result = events[-1].result
    assert result.success and result.result == "done"
    saved = progress if snapshot_kind == "progress" else checkpoint
    assert saved.await_count == 12
    latest = saved.await_args.args[0]
    assert (latest if snapshot_kind == "progress" else latest.result).result == "Step 11"
    assert boundary.semantic.await_args.kwargs["kind"] == "run.completed"
