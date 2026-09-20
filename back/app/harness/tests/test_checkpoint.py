from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agent.contracts import (
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    ExecutionResult,
    ResolvedModel,
)
from app.harness.checkpoint import (
    HarnessRunCheckpoint,
    UnsafeCheckpointError,
    _execution_policy_for_toolset_tool,
    checkpoint_is_safe,
    wrap_toolsets,
)


@pytest.mark.asyncio
async def test_checkpoint_snapshot_does_not_change_after_later_acknowledgement():
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    effect_id = await journal.started(name="file_write", arguments={"content": "original"},
        messages=_tool_history(), tool_call_id="call-1")
    before = save.await_args.args[0]
    await journal.completed(effect_id=effect_id, name="file_write", result="done",
        messages=_tool_history(), tool_call_id="call-1")
    assert before.data["effects"][0]["status"] == "started"
    assert before.data["effects"][0]["arguments"] == {"content": "original"}


@pytest.mark.asyncio
async def test_resumed_read_can_observe_new_state_instead_of_cached_result():
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    effect = await journal.started(name="external_status", arguments={}, messages=[],
        tool_call_id="read", effect_policy="read", concurrency_policy="safe")
    await journal.completed(effect_id=effect, name="external_status", result="running", messages=[], tool_call_id="read")
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
    wrapped = SimpleNamespace(call_tool=AsyncMock(return_value="completed"))
    toolset = wrap_toolsets([wrapped], resumed)[0]
    result = await toolset.call_tool("external_status", {}, SimpleNamespace(messages=[], tool_call_id="new-read"),
        SimpleNamespace(tool_def=SimpleNamespace(metadata={"annotations": {"readOnlyHint": True}})))
    assert result == "completed"
    wrapped.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_text_error_is_not_proof_of_rejection():
    checkpoint = AgentRunCheckpoint(driver_code="internal", runtime_run_id="legacy", status="interrupted", data={
        "version": 2, "resume_safe": True,
        "effects": [{"id": "old", "tool_call_id": "old", "tool_name": "console_exec", "status": "failed", "error": "timeout"}],
        "message_history": HarnessRunCheckpoint._dump_messages([
            ModelResponse(parts=[ToolCallPart("console_exec", {"command": "send"}, "old")]),
            ModelRequest(parts=[RetryPromptPart(content="timeout", tool_name="console_exec", tool_call_id="old")]),
        ]),
    })
    with pytest.raises(UnsafeCheckpointError):
        await HarnessRunCheckpoint(_request(resume_checkpoint=checkpoint)).prepare_resume()


@pytest.mark.asyncio
async def test_cancelling_a_queued_result_does_not_deadlock_following_tools():
    first_gate = asyncio.Event()
    second_done = asyncio.Event()

    class Reads:
        async def call_tool(self, name, arguments, ctx, tool):
            if arguments["number"] == 1:
                await first_gate.wait()
            elif arguments["number"] == 2:
                second_done.set()
            return arguments["number"]

    wrapped = wrap_toolsets([Reads()], None, max_parallel=3)[0]
    tool = SimpleNamespace(tool_def=SimpleNamespace(metadata={"annotations": {"readOnlyHint": True}}))
    async def call(number):
        return await wrapped.call_tool("read", {"number": number}, SimpleNamespace(), tool)
    first = asyncio.create_task(call(1))
    second = asyncio.create_task(call(2))
    await second_done.wait()
    second.cancel()
    third = asyncio.create_task(call(3))
    first_gate.set()
    results = await asyncio.wait_for(asyncio.gather(first, second, third, return_exceptions=True), 2)
    assert results[0] == 1 and results[2] == 3
    assert isinstance(results[1], asyncio.CancelledError)


@pytest.mark.parametrize("destructive", [False, True])
def test_external_mcp_read_annotations_make_checkpoint_replay_safe(
    monkeypatch: pytest.MonkeyPatch,
    destructive: bool,
) -> None:
    from app.tools import mcp_loader

    monkeypatch.setattr(
        mcp_loader,
        "execution_policy_for_tool",
        lambda _name: ("non_idempotent", "exclusive"),
    )
    tool = SimpleNamespace(
        tool_def=SimpleNamespace(
            metadata={"annotations": {"readOnlyHint": True, "destructiveHint": destructive}}
        )
    )

    assert _execution_policy_for_toolset_tool("gitlab_get_project", tool) == (
        ("non_idempotent", "exclusive") if destructive else ("read", "safe")
    )


def _request(
    *,
    save_checkpoint: AsyncMock | None = None,
    resume_checkpoint: AgentRunCheckpoint | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Create the report",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        resume_checkpoint=resume_checkpoint,
        control=AgentRunControl(save_checkpoint=save_checkpoint),
    )


def _tool_history() -> list[Any]:
    return [
        ModelRequest(parts=[UserPromptPart(content="Create the report")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    "file_write",
                    {"path": "report.txt", "content": "done"},
                    "call-1",
                )
            ]
        ),
    ]


@pytest.mark.asyncio
async def test_checkpoint_preserves_native_responses_reasoning_and_ids() -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    native_history = [
        ModelRequest(parts=[UserPromptPart(content="Find the answer")]),
        ModelResponse(
            parts=[
                ThinkingPart(
                    content="Need an authoritative lookup.",
                    id="rs-1",
                    signature="opaque-reasoning",
                    provider_name="galaris",
                ),
                ToolCallPart(
                    "lookup",
                    {"query": "answer"},
                    "call-1",
                    id="fc-1",
                    provider_name="galaris",
                ),
            ],
            provider_response_id="resp-1",
            provider_name="galaris",
        ),
    ]

    await journal.interrupted(native_history)
    checkpoint = cast(AgentRunCheckpoint, save.await_args.args[0])
    restored = HarnessRunCheckpoint(
        _request(resume_checkpoint=checkpoint)
    ).restored_messages()

    response = cast(ModelResponse, restored[1])
    assert response.provider_response_id == "resp-1"
    reasoning = cast(ThinkingPart, response.parts[0])
    assert reasoning.id == "rs-1"
    assert reasoning.signature == "opaque-reasoning"
    tool_call = cast(ToolCallPart, response.parts[1])
    assert tool_call.id == "fc-1"
    assert tool_call.tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_checkpoint_marks_effect_before_call_and_records_result_after() -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    journal.result_factory = lambda: ExecutionResult(
        prompt="Create the report",
    )

    effect_id = await journal.started(
        name="file_write",
        arguments={"path": "report.txt", "content": "done"},
        messages=_tool_history(),
        tool_call_id="call-1",
    )
    started = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert started.data["effects"][0]["status"] == "started"
    assert checkpoint_is_safe(started) is False

    await journal.completed(
        effect_id=effect_id,
        name="file_write",
        result={"path": "report.txt"},
        messages=_tool_history(),
        tool_call_id="call-1",
    )
    completed = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert completed.data["effects"][0]["status"] == "completed"
    assert checkpoint_is_safe(completed) is True
    assert completed.result is not None
    assert completed.result.tools_used == ["file_write"]
    restored = HarnessRunCheckpoint(
        _request(resume_checkpoint=completed)
    ).restored_messages()
    assert isinstance(restored[-1], ModelRequest)
    assert isinstance(restored[-1].parts[0], ToolReturnPart)


@pytest.mark.asyncio
async def test_resume_returns_recorded_tool_result_without_replaying_effect() -> None:
    save = AsyncMock()
    first = HarnessRunCheckpoint(_request(save_checkpoint=save))
    effect_id = await first.started(
        name="file_write",
        arguments={"path": "report.txt", "content": "done"},
        messages=_tool_history(),
        tool_call_id="call-1",
    )
    await first.completed(
        effect_id=effect_id,
        name="file_write",
        result={"path": "report.txt"},
        messages=_tool_history(),
        tool_call_id="call-1",
    )
    completed = cast(AgentRunCheckpoint, save.await_args.args[0])
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=completed))

    class Wrapped:
        call_tool = AsyncMock(return_value={"unexpected": True})

    wrapped = Wrapped()
    toolset = wrap_toolsets([wrapped], resumed)[0]
    result = await toolset.call_tool(
        "file_write",
        {"path": "report.txt", "content": "done"},
        cast(
            Any,
            SimpleNamespace(messages=_tool_history(), tool_call_id="call-resumed"),
        ),
        cast(Any, None),
    )

    assert result == {"path": "report.txt"}
    wrapped.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfinished_effect_blocks_automatic_resume() -> None:
    save = AsyncMock()
    first = HarnessRunCheckpoint(_request(save_checkpoint=save))
    await first.started(
        name="messenger_send_message_to_user",
        arguments={"user_id": "42", "message": "Hello"},
        messages=_tool_history(),
        tool_call_id="call-1",
    )
    await first.interrupted(_tool_history())
    unsafe = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert unsafe.status == "interrupted"
    assert unsafe.data["resume_safe"] is False
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=unsafe))

    with pytest.raises(UnsafeCheckpointError, match="outcome is unknown"):
        resumed.ensure_resumable()


@pytest.mark.asyncio
async def test_recorded_tool_failure_does_not_block_resume_or_reexecute() -> None:
    from app.tools.contracts import current_tool_execution

    async def rejected(*_args):
        execution = current_tool_execution()
        assert execution is not None
        execution.outcome = "rejected"
        raise ModelRetry("command required")

    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    wrapped = SimpleNamespace(call_tool=AsyncMock(side_effect=rejected))
    toolset = wrap_toolsets([wrapped], journal)[0]
    history = [ModelResponse(parts=[ToolCallPart("console_exec", {}, "call-1")])]
    ctx = SimpleNamespace(messages=history, tool_call_id="call-1")

    failure = await toolset.call_tool("console_exec", {}, ctx, None)
    assert failure["error"] == "command required"
    assert failure["outcome"] == "rejected"

    saved = cast(AgentRunCheckpoint, save.await_args.args[0])
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=saved))
    await resumed.prepare_resume()
    assert checkpoint_is_safe(saved)
    assert isinstance(resumed.restored_messages()[-1].parts[0], ToolReturnPart)
    assert await wrap_toolsets([wrapped], resumed)[0].call_tool("console_exec", {}, ctx, None) == failure
    assert wrapped.call_tool.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "call", "tool"])
async def test_legacy_unknown_effect_uses_only_its_own_recorded_failure(
    mismatch: str | None,
) -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    history = [ModelResponse(parts=[ToolCallPart("console_exec", {}, "call-1")])]
    await journal.started(name="console_exec", arguments={}, messages=history, tool_call_id="call-1")
    history.append(ModelRequest(parts=[RetryPromptPart(
        content=[{"type": "missing", "loc": ("command",), "msg": "command required", "input": {}}],
        tool_name="another_tool" if mismatch == "tool" else "console_exec",
        tool_call_id="another-call" if mismatch == "call" else "call-1",
    )]))
    await journal.interrupted(history)
    saved = cast(AgentRunCheckpoint, save.await_args.args[0])
    saved.data["effects"][0]["status"] = "outcome_unknown"
    resumed = HarnessRunCheckpoint(_request(save_checkpoint=save, resume_checkpoint=saved))
    if mismatch is not None:
        with pytest.raises(UnsafeCheckpointError, match="outcome is unknown"):
            await resumed.prepare_resume()
        return
    await resumed.prepare_resume()
    repaired = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert checkpoint_is_safe(repaired)
    assert resumed.restored_messages() == history
    with pytest.raises(ModelRetry, match="command required"):
        resumed.take_replay("console_exec", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.CancelledError(), OSError("connection lost password=secret")])
async def test_interrupted_transport_keeps_effect_outcome_unknown(error: BaseException) -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    wrapped = SimpleNamespace(call_tool=AsyncMock(side_effect=error))
    toolset = wrap_toolsets([wrapped], journal)[0]
    ctx = SimpleNamespace(messages=[], tool_call_id="call-unknown")
    if isinstance(error, Exception):
        failure = await toolset.call_tool("console_exec", {}, ctx, None)
        assert failure["outcome"] == "unknown"
        assert "secret" not in failure["error"]
        saved = cast(AgentRunCheckpoint, save.await_args.args[0])
        saved.data["effects"][0]["recovery_scope"] = "same-server"
        resumed = HarnessRunCheckpoint(
            _request(resume_checkpoint=saved), recovery_scope="same-server",
            recover_effect=AsyncMock(side_effect=OSError("receipt lookup unavailable")),
        )
        await resumed.prepare_resume()
        assert resumed.take_replay("console_exec", {}) == (True, failure)
        wrapped.call_tool.assert_awaited_once()
        return
    with pytest.raises(type(error)):
        await toolset.call_tool("console_exec", {}, ctx, None)
    saved = cast(AgentRunCheckpoint, save.await_args.args[0])
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=saved))
    with pytest.raises(UnsafeCheckpointError, match="outcome is unknown"):
        resumed.ensure_resumable()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_failed", [False, True])
async def test_parallel_tool_results_become_resumable_only_when_all_are_durable(
    first_failed: bool,
) -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    history = [
        ModelRequest(parts=[UserPromptPart(content="Create two files")]),
        ModelResponse(
            parts=[
                ToolCallPart("file_write", {"path": "a.txt"}, "call-a"),
                ToolCallPart("file_write", {"path": "b.txt"}, "call-b"),
            ]
        ),
    ]
    effect_a = await journal.started(
        name="file_write",
        arguments={"path": "a.txt"},
        messages=history,
        tool_call_id="call-a",
    )
    effect_b = await journal.started(
        name="file_write",
        arguments={"path": "b.txt"},
        messages=history,
        tool_call_id="call-b",
    )
    await journal.completed(
        effect_id=effect_a,
        name="file_write",
        result={"path": "a.txt"},
        messages=history,
        tool_call_id="call-a",
        retry_error="invalid path" if first_failed else None,
    )
    first_completion = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert first_completion.data["resume_safe"] is False

    await journal.completed(
        effect_id=effect_b,
        name="file_write",
        result={"path": "b.txt"},
        messages=history,
        tool_call_id="call-b",
    )
    completed = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert completed.data["resume_safe"] is True
    restored = HarnessRunCheckpoint(
        _request(resume_checkpoint=completed)
    ).restored_messages()
    assert isinstance(restored[-1], ModelRequest)
    assert {
        part.tool_call_id
        for part in restored[-1].parts
        if isinstance(part, (ToolReturnPart, RetryPromptPart))
    } == {"call-a", "call-b"}
    assert isinstance(restored[-1].parts[0], RetryPromptPart if first_failed else ToolReturnPart)


def test_unknown_internal_checkpoint_version_is_not_replayed() -> None:
    checkpoint = AgentRunCheckpoint(
        driver_code="internal",
        runtime_run_id="run-old",
        status="running",
        data={"version": 999, "resume_safe": True},
    )
    journal = HarnessRunCheckpoint(_request(resume_checkpoint=checkpoint))

    assert checkpoint_is_safe(checkpoint) is False
    with pytest.raises(UnsafeCheckpointError, match="format is not supported"):
        journal.ensure_resumable()


@pytest.mark.asyncio
async def test_interrupted_read_is_closed_and_may_be_retried() -> None:
    save = AsyncMock()
    first = HarnessRunCheckpoint(_request(save_checkpoint=save))
    await first.started(
        name="search_web",
        arguments={"query": "Galaris"},
        messages=[ModelResponse(parts=[ToolCallPart("search_web", {"query": "Galaris"}, "call-read")])],
        tool_call_id="call-read",
        effect_policy="read",
        concurrency_policy="safe",
    )
    interrupted = cast(AgentRunCheckpoint, save.await_args.args[0])
    resumed = HarnessRunCheckpoint(
        _request(save_checkpoint=save, resume_checkpoint=interrupted)
    )

    await resumed.prepare_resume()

    repaired = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert repaired.data["resume_safe"] is True
    assert repaired.data["effects"][0]["status"] == "interrupted"
    restored = resumed.restored_messages()
    assert isinstance(restored[-1], ModelRequest)
    retry_return = cast(ToolReturnPart, restored[-1].parts[0])
    assert retry_return.tool_call_id == "call-read"
    assert cast(dict[str, Any], retry_return.content)["retryable"] is True


@pytest.mark.asyncio
async def test_resume_repairs_legacy_conservative_policy_for_safe_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    save = AsyncMock()
    first = HarnessRunCheckpoint(_request(save_checkpoint=save))
    await first.started(
        name="image_read",
        arguments={"file": "chat://room/image-id"},
        messages=[ModelResponse(parts=[ToolCallPart("image_read", {"file": "chat://room/image-id"}, "call-image-read")])],
        tool_call_id="call-image-read",
    )
    started = cast(AgentRunCheckpoint, save.await_args.args[0])
    started.data["effects"][0].pop("policy_version")
    monkeypatch.setattr(
        mcp_loader,
        "execution_policy_for_tool",
        lambda _name: ("non_idempotent", "exclusive"),
    )
    blocked = HarnessRunCheckpoint(
        _request(save_checkpoint=save, resume_checkpoint=started)
    )
    with pytest.raises(UnsafeCheckpointError, match="outcome is unknown"):
        await blocked.prepare_resume()
    legacy = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert legacy.data["effects"][0]["status"] == "outcome_unknown"

    monkeypatch.setattr(
        mcp_loader,
        "execution_policy_for_tool",
        lambda name: ("read", "safe")
        if name == "image_read"
        else ("non_idempotent", "exclusive"),
    )
    resumed = HarnessRunCheckpoint(
        _request(save_checkpoint=save, resume_checkpoint=legacy)
    )
    await resumed.prepare_resume()

    repaired = cast(AgentRunCheckpoint, save.await_args.args[0])
    effect = cast(list[dict[str, Any]], repaired.data["effects"])[0]
    assert repaired.data["resume_safe"] is True
    assert effect["effect_policy"] == "read"
    assert effect["concurrency_policy"] == "safe"
    assert effect["status"] == "interrupted"
    restored = resumed.restored_messages()
    assert isinstance(restored[-1], ModelRequest)
    retry_return = cast(ToolReturnPart, restored[-1].parts[0])
    assert retry_return.tool_name == "image_read"
    assert cast(dict[str, Any], retry_return.content)["retryable"] is True


@pytest.mark.asyncio
async def test_cancelled_run_persists_interrupted_pydantic_history() -> None:
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    history = [
        ModelRequest(parts=[UserPromptPart(content="Create the report")]),
        ModelResponse(
            parts=[TextPart(content="Partial answer")],
            state="interrupted",
        ),
    ]

    await journal.interrupted(history)

    checkpoint = cast(AgentRunCheckpoint, save.await_args.args[0])
    assert checkpoint.status == "interrupted"
    assert checkpoint.data["resume_safe"] is True
    restored = HarnessRunCheckpoint(
        _request(resume_checkpoint=checkpoint)
    ).restored_messages()
    response = cast(ModelResponse, restored[-1])
    assert response.state == "interrupted"
    assert cast(TextPart, response.parts[0]).content == "Partial answer"


@pytest.mark.asyncio
async def test_safe_tools_run_concurrently_but_exclusive_tool_is_a_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import mcp_loader

    policies = {
        "read_a": ("read", "safe"),
        "read_b": ("read", "safe"),
        "write": ("non_idempotent", "exclusive"),
    }
    monkeypatch.setattr(
        mcp_loader,
        "execution_policy_for_tool",
        lambda name: policies[name],
    )
    active = 0
    max_active = 0
    order: list[str] = []

    class Wrapped:
        async def call_tool(self, name: str, *_args: Any) -> str:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            order.append(f"start:{name}")
            await asyncio.sleep(0.01 if name != "read_a" else 0.03)
            order.append(f"end:{name}")
            active -= 1
            return name

    toolset = wrap_toolsets([Wrapped()], None, max_parallel=2)[0]

    async def call(name: str) -> str:
        return await toolset.call_tool(
            name,
            {},
            cast(Any, SimpleNamespace(messages=[], tool_call_id=name)),
            cast(Any, None),
        )

    results = await asyncio.gather(call("read_a"), call("read_b"), call("write"))

    assert results == ["read_a", "read_b", "write"]
    assert max_active == 2
    assert order.index("start:write") > order.index("end:read_a")
    assert order.index("start:write") > order.index("end:read_b")
