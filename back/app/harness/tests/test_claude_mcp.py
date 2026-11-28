import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mcp.types import CallToolRequestParams, TextContent, Tool

from app.agent.contracts import ExecutionResult
from app.harness.claude_checkpoint import ClaudeCheckpointPolicy, ClaudeEffectJournal, checkpoint_tool_calls_used
from app.harness.claude_mcp import ClaudeMcp
from app.harness.claude_session import ClaudeSession
from app.services.facade import AuthorizationRequired


@pytest.mark.asyncio
async def test_sdk_mcp_dispatch_requires_a_matching_unconsumed_proposal_and_live_attempt():
    name = "file_schemes"
    tool = Tool(name=name, inputSchema={"type": "object", "properties": {}})
    native_call = AsyncMock(return_value=SimpleNamespace(
        content=[TextContent(type="text", text="synthetic receipt")], structured_content=None, is_error=False,
    ))
    authorize = AsyncMock()
    bridge = ClaudeMcp(SimpleNamespace(call_tool=native_call), {name: tool}, authorize=authorize, tool_limit=2)
    hook = bridge.hook().hooks[0]

    async def propose(call_id: str, tool_name: str = f"mcp__galaris__{name}"):
        return await hook({"hook_event_name": "PreToolUse", "tool_name": tool_name,
                           "tool_use_id": call_id, "tool_input": {"n": 1}}, call_id, {})

    async def invoke(call_id: str, arguments: dict):
        params = CallToolRequestParams(name=name, arguments=arguments, meta={"claudecode/toolUseId": call_id})
        return await bridge._call_tool(None, params)

    assert (await propose("native-command", "Bash"))["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (await invoke("unproposed", {"n": 1})).is_error
    assert await propose("first") == {}
    assert (await invoke("first", {"n": True})).is_error
    assert not (await invoke("first", {"n": 1})).is_error
    assert (await invoke("first", {"n": 1})).is_error

    assert await propose("second") == {}
    authorize.side_effect = PermissionError("Task lease expired")
    assert (await invoke("second", {"n": 1})).is_error
    assert (await propose("third"))["hookSpecificOutput"]["permissionDecision"] == "deny"
    native_call.assert_awaited_once_with(name, {"n": 1})
    receipts = bridge.drain()
    assert [(receipt.tool_call_external_id, receipt.success) for receipt in receipts] == [("first", True), ("second", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("call_ids", "limit"), [
    pytest.param(("first", "second"), 1, id="last-slot"),
    pytest.param(("same", "same"), 2, id="duplicate-id"),
])
async def test_concurrent_conversation_tool_hooks_cannot_reserve_the_same_slot(call_ids, limit):
    name = "file_schemes"
    tool = Tool(name=name, inputSchema={"type": "object", "properties": {}})
    native_call = AsyncMock(return_value=SimpleNamespace(content=[], structured_content=None, is_error=False))
    bridge = ClaudeMcp(SimpleNamespace(call_tool=native_call), {name: tool}, authorize=AsyncMock(),
                       tool_limit=limit, conversation=True)
    hook = bridge.hook().hooks[0]
    await bridge.observe_assistant({"type": "message_start"})
    for call_id in set(call_ids):
        await bridge.observe_assistant({"type": "content_block_start", "content_block": {"type": "tool_use", "id": call_id}})

    pending = asyncio.gather(*(hook({"hook_event_name": "PreToolUse", "tool_name": f"mcp__galaris__{name}",
        "tool_use_id": call_id, "tool_input": {"value": value}}, call_id, {})
        for value, call_id in enumerate(call_ids)))
    await asyncio.sleep(0)
    assert not pending.done()
    await bridge.observe_assistant({"type": "message_stop"})
    decisions = await pending

    [allowed] = [value for value, decision in enumerate(decisions) if decision == {}]
    denied = 1 - allowed
    assert decisions[denied]["hookSpecificOutput"]["permissionDecision"] == "deny"
    for value in (denied, allowed):
        result = await bridge._call_tool(None, CallToolRequestParams(name=name, arguments={"value": value},
            meta={"claudecode/toolUseId": call_ids[value]}))
        assert result.is_error == (value == denied)
    native_call.assert_awaited_once_with(name, {"value": allowed})


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_receipt", [False, True], ids=["confirmed", "uncertain"])
async def test_chat_task_run_can_correct_rejected_arguments_through_claude_mcp(monkeypatch, lost_receipt):
    from fastmcp import FastMCP
    from sqlalchemy import false

    from app import agent
    from app.conversation import ConversationTurn
    from app.conversation import mcp as conversation_mcp
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from app.services import mcp_authorization, mcp_loader
    from app.services.execution_evidence import ExecutionEvidenceMiddleware

    definitions = {
        tool.__galaris_mcp_tool__.name: tool.__galaris_mcp_tool__
        for tool in (conversation_mcp.task_run, conversation_mcp.task_list)
    }
    task_uri = f"galaris://task/{uuid4()}"
    submit = AsyncMock(return_value={"created": True, "resource_uri": task_uri},
                       side_effect=TimeoutError("Synthetic lost receipt") if lost_receipt else None)
    authorize_native = AsyncMock(return_value=None)
    before_effect = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "task_submit", submit)
    monkeypatch.setattr(conversation_mcp, "agent_task_filter", AsyncMock(return_value=false()))
    monkeypatch.setattr(agent, "effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=tuple(definitions.values())))
    monkeypatch.setattr(mcp_authorization, "authorize_native_call", authorize_native)
    monkeypatch.setattr("core.failure_journal.record_failure_event", AsyncMock())

    turn = ConversationTurn(
        room_id=uuid4(), round_id=uuid4(), agent_id=7, language="en", objective="Prepare a synthetic report.",
        messages=(), messaging_context={"connection_id": 19, "room_id": "test"},
    )
    ctx = mcp_loader.McpToolContext(
        agent_id=7, runtime="internal", conversation_only=True,
        resources={"conversation_turn": turn, "before_tool_effect": before_effect},
    )
    server = FastMCP("claude-task-admission")
    server.add_middleware(ExecutionEvidenceMiddleware(set(definitions)))
    for definition in definitions.values():
        server.add_tool(mcp_loader._native_tool_template(definition).bind(ctx))
    journal = ClaudeEffectJournal(driver_code="claude_embedded", run_id=turn.round_id, save=AsyncMock())
    args = {"objective": "<p>Prepare a synthetic report.</p>", "label": "Synthetic report"}

    async with ExecutionEvidenceClient(server) as client:
        bridge = ClaudeMcp(
            client, {tool.name: tool for tool in await client.list_tools()},
            authorize=AsyncMock(), tool_limit=4, conversation=True, journal=journal,
            policies={name: definition.effect_policy for name, definition in definitions.items()},
        )

        async def invoke(name, call_id, arguments):
            await bridge.observe_assistant({"type": "message_start"})
            await bridge.observe_assistant({"type": "content_block_start", "content_block": {"type": "tool_use", "id": call_id}})
            await bridge.observe_assistant({"type": "message_stop"})
            assert await bridge.hook().hooks[0]({"hook_event_name": "PreToolUse", "tool_name": f"mcp__galaris__{name}",
                "tool_use_id": call_id, "tool_input": arguments}, call_id, {}) == {}
            return await bridge._call_tool(None, CallToolRequestParams(name=name, arguments=arguments,
                meta={"claudecode/toolUseId": call_id}))

        assert not (await invoke("task_list", "list", {})).is_error
        invalid = await invoke("task_run", "invalid", {**args, "effort": "high"})
        assert invalid.is_error and "only available for delegation" in invalid.content[0].text
        submit.assert_not_awaited()
        assert not journal.unresolved
        assert not journal.applied
        assert [call.args[1].name for call in authorize_native.await_args_list] == ["task_list"]
        before_effect.assert_not_awaited()

        corrected = await invoke("task_run", "corrected", args)
        assert corrected.is_error == lost_receipt
        if lost_receipt:
            assert journal.unresolved
            blocked = await invoke("task_run", "after-lost-receipt", {**args, "label": "Another report"})
            assert blocked.is_error and "must be reconciled" in blocked.content[0].text
        else:
            assert not journal.unresolved
            assert corrected.structured_content == {"result": {"created": True, "resource_uri": task_uri}}

    result = ExecutionResult(prompt=args["objective"], result="Submitted.", success=True)
    await journal.finalize(result)
    assert result.success is not lost_receipt
    assert (result.failure.code if result.failure else None) == ("effect_unknown" if lost_receipt else None)
    submit.assert_awaited_once_with(ctx, **args, mode="auto", disposition="CREATE_NEW",
                                   target_task_id=None, expected_revision=None, reason=None)
    assert [call.args[1].name for call in authorize_native.await_args_list] == ["task_list", "task_run"]
    before_effect.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("save_fails", [False, True], ids=["read-consumes-budget", "no-read-without-checkpoint"])
async def test_task_tool_budget_fences_reads_without_recording_a_mutation(save_fails):
    name = "file_schemes"
    tool = Tool(name=name, inputSchema={"type": "object", "properties": {}})
    checkpoints = []

    async def save(checkpoint):
        if save_fails:
            raise OSError("Synthetic checkpoint write failure")
        checkpoints.append(checkpoint)

    native_call = AsyncMock(return_value=SimpleNamespace(content=[], structured_content=None, is_error=False))
    run_id = uuid4()
    journal = ClaudeEffectJournal(driver_code="claude_embedded", run_id=run_id, save=save)

    def mount(effect_journal):
        return ClaudeMcp(SimpleNamespace(call_tool=native_call), {name: tool}, authorize=AsyncMock(),
                         tool_limit=1, journal=effect_journal, durable_tool_budget=True)

    async def propose(bridge, call_id):
        return await bridge.hook().hooks[0]({"hook_event_name": "PreToolUse", "tool_name": f"mcp__galaris__{name}",
            "tool_use_id": call_id, "tool_input": {}}, call_id, {})

    bridge = mount(journal)
    assert await propose(bridge, "first") == {}
    params = CallToolRequestParams(name=name, arguments={}, meta={"claudecode/toolUseId": "first"})
    if save_fails:
        with pytest.raises(OSError, match="checkpoint write failure"):
            await bridge._call_tool(None, params)
        native_call.assert_not_awaited()
        return

    assert not (await bridge._call_tool(None, params)).is_error
    [saved] = checkpoints
    assert saved.data["effects"] == [] and saved.data["tool_calls_used"] == 1
    assert ClaudeCheckpointPolicy().assess(saved).resumable
    resumed = ClaudeEffectJournal(driver_code=journal.driver_code, run_id=run_id, save=save,
                                  tool_calls_used=checkpoint_tool_calls_used(saved))
    denied = await propose(mount(resumed), "second")
    assert "tool call limit" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    native_call.assert_awaited_once_with(name, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", ["before_dispatch", "after_dispatch", "revoked", None])
async def test_mutation_is_fenced_by_durable_effect_evidence(failure_at):
    checkpoints = []
    policy = ClaudeCheckpointPolicy()

    async def save(checkpoint):
        status = checkpoint.data["effects"][-1]["status"]
        if ((failure_at == "before_dispatch" and status == "started")
                or (failure_at == "after_dispatch" and status == "completed")):
            raise OSError("synthetic checkpoint write failure")
        checkpoints.append(checkpoint)

    async def mutate(*_):
        assert checkpoints[-1].data["effects"][-1]["status"] == "started"
        assert policy.assess(checkpoints[-1]).state == "unsafe"
        return SimpleNamespace(content=[TextContent(type="text", text="synthetic receipt")],
                               structured_content={"uri": "data://synthetic"}, is_error=False)

    name = "file_create"
    tool = Tool(name=name, inputSchema={"type": "object", "properties": {}})
    native_call = AsyncMock(side_effect=mutate)
    authorize = AsyncMock(side_effect=[None, PermissionError("synthetic revocation")] if failure_at == "revoked" else None)
    journal = ClaudeEffectJournal(driver_code="claude_embedded", run_id=uuid4(), save=save)
    bridge = ClaudeMcp(SimpleNamespace(call_tool=native_call), {name: tool}, authorize=authorize, tool_limit=3,
                       policies={name: "non_idempotent"}, journal=journal)
    hook = bridge.hook().hooks[0]

    async def invoke(call_id):
        assert await hook({"hook_event_name": "PreToolUse", "tool_name": f"mcp__galaris__{name}",
                           "tool_use_id": call_id, "tool_input": {}}, call_id, {}) == {}
        return await bridge._call_tool(None, CallToolRequestParams(name=name, meta={"claudecode/toolUseId": call_id}))

    result = ExecutionResult(prompt="Synthetic write", result="Done.", success=True)
    if failure_at == "revoked":
        assert (await invoke("first")).is_error
        native_call.assert_not_awaited()
        assert checkpoints[-1].data["effects"][-1]["status"] == "rejected"
        assert policy.assess(checkpoints[-1]).state == "safe"
        return
    if failure_at is None:
        assert not (await invoke("first")).is_error
        assert policy.assess(checkpoints[-1]).state == "unsafe"
        await journal.finalize(result)
        terminal = checkpoints[-1]
        assert terminal.result == result and terminal.status == "completed"
        assert policy.assess(terminal).state == "safe"
        assert policy.rebase(terminal) is None
        assert policy.tool_history(terminal, limit=1)[0].tool_result == {"uri": "data://synthetic"}
        native_call.assert_awaited_once()
        return

    with pytest.raises(OSError, match="synthetic checkpoint write failure"):
        await invoke("first")
    if failure_at == "before_dispatch":
        native_call.assert_not_awaited()
        assert checkpoints == []
        return

    assert (await invoke("second")).is_error
    native_call.assert_awaited_once()
    assert checkpoints[-1].data["effects"][-1]["status"] == "started"
    assert policy.prepare_retry(checkpoints[-1]) == checkpoints[-1]
    await journal.finalize(result)
    assert not result.success and result.failure.code == "effect_unknown"


@pytest.mark.asyncio
async def test_requested_tool_authorization_is_retained_as_pending_and_not_as_an_unknown_effect():
    checkpoints = []

    async def save(checkpoint):
        checkpoints.append(checkpoint)

    request_id = uuid4()
    name = "file_create"
    tool = Tool(name=name, inputSchema={"type": "object", "properties": {}})
    native_call = AsyncMock(side_effect=AuthorizationRequired(request_id, "synthetic-encrypted-continuation"))
    journal = ClaudeEffectJournal(driver_code="claude_embedded", run_id=uuid4(), save=save)
    bridge = ClaudeMcp(SimpleNamespace(call_tool=native_call), {name: tool}, authorize=AsyncMock(), tool_limit=3,
                       policies={name: "non_idempotent"}, journal=journal)
    hook = bridge.hook().hooks[0]
    for call_id in ("requested-effect", "later-effect"):
        assert await hook({"hook_event_name": "PreToolUse", "tool_name": f"mcp__galaris__{name}",
                           "tool_use_id": call_id, "tool_input": {}}, call_id, {}) == {}
        outcome = await bridge._call_tool(None, CallToolRequestParams(name=name, meta={"claudecode/toolUseId": call_id}))
        assert outcome.is_error and "synthetic-encrypted-continuation" not in outcome.content[0].text
    native_call.assert_awaited_once()
    assert checkpoints[-1].status == "waiting_for_authorization"
    assert checkpoints[-1].data["effects"][0]["status"] == "waiting_for_authorization"
    result = ExecutionResult(prompt="Synthetic request", result="Premature success claim", success=True)
    await journal.finalize(result)
    assert result.disposition == "waiting_for_authorization" and result.authorization_requests == [request_id]
    assert result.failure is None and not result.success and not result.result

    policy = ClaudeCheckpointPolicy()
    assert policy.assess(checkpoints[-1]).state == "unsafe"
    session = ClaudeSession(uuid4(), '{"synthetic":true}\n')
    await journal.retain_session(session)
    checkpoint = checkpoints[-1]
    assert policy.assess(checkpoint).state == "reconcile"
    assert session.transcript not in checkpoint.data["sdk_session"]
    restored = ClaudeEffectJournal(driver_code=journal.driver_code, run_id=journal.run_id, save=save,
                                  previous=checkpoint)
    assert restored.restore_session() == session
    assert restored.pending is not None
    assert restored.pending.continuation(journal.run_id) == "synthetic-encrypted-continuation"
    with pytest.raises(ValueError, match="does not belong"):
        restored.pending.continuation(uuid4())
    another_run = uuid4()
    swapped = ClaudeEffectJournal(driver_code=journal.driver_code, run_id=another_run, save=save,
                                  previous=replace(checkpoint, runtime_run_id=str(another_run)))
    with pytest.raises(ValueError, match="belongs to another run"):
        swapped.restore_session()
