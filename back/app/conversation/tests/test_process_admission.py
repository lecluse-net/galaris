"""Conversation launches stay within the real request across retries and recovery."""

# Imported pytest fixtures are intentionally injected into test parameters.
# ruff: noqa: F811

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.connection import Connection
from app.conversation import ConversationTurn
from app.conversation.mcp import conversation_process_start
from app.conversation.models import ConversationProcessLink, ConversationRound, ConversationRoundMessage
from app.llm import llm_service, structured_service
from app.messenger import Message, Room
from app.process.models import ProcessRun
from app.process.native_definitions import create
from app.process.tests.test_native_bpmn import graph, native as native, committed_native as committed_native
from app.tools import McpToolContext, RecoverableToolError
from app.tools.models import Tool
from core.database import get_db_session


async def conversation(db, owner, text, *, room=None):
    if room is None:
        tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
        connection = Connection(agent_id=owner.id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(connection_id=connection.id, external_id=uuid4().hex, label="Synthetic room",
            kind="direct", conversation_type="text")
        db.add(room)
        await db.flush()
    round_ = ConversationRound(room_id=room.id, status="RUNNING")
    message = Message(connection_id=room.connection_id, platform="internal", direction="inbound",
        remote_message_id=uuid4().hex, messenger_room_id=room.id, text=text)
    db.add_all([round_, message])
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()
    turn = ConversationTurn(room_id=room.id, round_id=round_.id, agent_id=owner.id, language="en",
        objective=text, source_request=text, messages=({"text": text},))
    return turn, room


def context(turn):
    return McpToolContext(agent_id=turn.agent_id, runtime="internal", resources={"conversation_turn": turn})


def provider(monkeypatch, launches):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    requests = []

    def respond(messages, info):
        requests.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"launches": launches})])

    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=SimpleNamespace(id=987)))
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=FunctionModel(respond)))
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0.0)
    return requests


@pytest.mark.asyncio
async def test_answer_cannot_start_a_process_even_without_a_fake_transcript(db, native, monkeypatch):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic unrelated weather", graph=graph())
    turn, _ = await conversation(db, owner, "34 years")
    effect_guard = AsyncMock(return_value=True)
    turn = replace(turn, assert_fresh_before_effect=effect_guard)
    requests = provider(monkeypatch, [])
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=definition.code)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0
    assert len(requests) == 1
    effect_guard.assert_not_awaited()


@pytest.mark.asyncio
async def test_frozen_admission_replays_one_run_and_rejects_changed_inputs_or_another_workflow(db, native, monkeypatch):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic requested workflow", graph=graph())
    other = await create(actor_agent_id=owner.id, title="Synthetic unrelated workflow", graph=graph())
    turn, _ = await conversation(db, owner, "Launch the requested workflow for Oslo.")
    requests = provider(monkeypatch, [{"workflow_id": definition.code, "input": {"city": "Oslo"}}])
    first = await conversation_process_start(context(turn), workflow_id=definition.code, input={"city": "Oslo"})
    # A new controller attempt must reuse the durable permission and invocation.
    replay = await conversation_process_start(context(replace(turn, attempt=2)),
        workflow_id=definition.code, input={"city": "Oslo"})
    assert replay["run_id"] == first["run_id"] and replay["created"] is False
    for workflow, values in [(definition.code, {"city": "Paris"}), (other.code, {})]:
        with pytest.raises(RecoverableToolError):
            await conversation_process_start(context(turn), workflow_id=workflow, input=values)
    assert len(requests) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ConversationProcessLink)) == 1

    # Simulate an interruption between durable Process admission and lineage.
    await db.execute(delete(ConversationProcessLink))
    await db.commit()
    recovered = await conversation_process_start(context(replace(turn, attempt=3)),
        workflow_id=definition.code, input={"city": "Oslo"})
    assert recovered["run_id"] == first["run_id"] and recovered["created"] is False
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ConversationProcessLink)) == 1
    with pytest.raises(RecoverableToolError, match="different admitted input"):
        await conversation_process_start(context(replace(turn, source_request="Launch something else")),
            workflow_id=definition.code, input={"city": "Oslo"})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_explicit_multiple_launches_and_a_new_human_request_remain_possible(db, native, monkeypatch):
    owner, _ = native
    first = await create(actor_agent_id=owner.id, title="Synthetic first workflow", graph=graph())
    second = await create(actor_agent_id=owner.id, title="Synthetic second workflow", graph=graph())
    launches = [{"workflow_id": first.code, "input": {"city": "Oslo"}},
        {"workflow_id": first.code, "input": {"city": "Oslo"}},
        {"workflow_id": second.code, "input": {}}]
    turn, room = await conversation(db, owner, "Launch the first workflow twice for Oslo, then the second workflow.")
    requests = provider(monkeypatch, launches)
    results = []
    for workflow, values, occurrence in [(first.code, {"city": "Oslo"}, 1),
                                        (first.code, {"city": "Oslo"}, 2), (second.code, {}, 1)]:
        result = await conversation_process_start(context(turn), workflow_id=workflow, input=values, occurrence=occurrence)
        results.append(result["run_id"])
        assert (await conversation_process_start(context(turn), workflow_id=workflow,
            input=values, occurrence=occurrence))["run_id"] == result["run_id"]
    assert len(set(results)) == 3 and len(requests) == 1
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=first.code, input={"city": "Oslo"}, occurrence=3)
    # The next actual message can deliberately request a fresh run of the same workflow.
    round_ = await db.get(ConversationRound, turn.round_id)
    round_.status = "SUCCEEDED"
    await db.commit()
    new_turn, _ = await conversation(db, owner, "Launch the first workflow again for Oslo.", room=room)
    provider(monkeypatch, [launches[0]])
    new = await conversation_process_start(context(new_turn), workflow_id=first.code, input={"city": "Oslo"})
    assert new["created"] and new["run_id"] not in results
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline_phase", ["preparation", "provider"])
async def test_late_permission_and_unavailable_provider_never_start_work(inference_db, committed_native, monkeypatch, deadline_phase):
    from app.conversation import ConversationSuperseded

    # Cancelling a SQL read can invalidate its connection. Use real transactions,
    # since a shared outer test savepoint cannot recover that connection.
    db = inference_db
    owner, _ = committed_native
    definition = await create(actor_agent_id=owner.id, title="Synthetic requested workflow", graph=graph())
    workflow_id = definition.code
    turn, _ = await conversation(db, owner, "Launch the requested workflow.")
    requests = provider(monkeypatch, [{"workflow_id": definition.code, "input": {}}])
    stale = replace(turn, should_interrupt=AsyncMock(side_effect=lambda: bool(requests)))
    with pytest.raises(ConversationSuperseded):
        await conversation_process_start(context(stale), workflow_id=definition.code)
    assert len(requests) == 1
    assert await db.scalar(select(ConversationRound.process_launch_admission)) is None

    # A silent provider must not hold the conversation indefinitely. Cancellation
    # stops the read-only verification without recording an effect or permission.
    from app.conversation import process_admission
    cancelled = asyncio.Event()

    async def silent_provider(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(process_admission, "_ADMISSION_TIMEOUT_SECONDS", 0.000001 if deadline_phase == "preparation" else 0.5)
    monkeypatch.setattr(structured_service, "build_model_for_llm", silent_provider)
    with pytest.raises(RecoverableToolError, match="could not be verified"):
        await asyncio.wait_for(conversation_process_start(context(turn), workflow_id=workflow_id), 2)
    if deadline_phase == "provider":
        assert cancelled.is_set()
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0
    assert await db.scalar(select(ConversationRound.process_launch_admission)) is None
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(side_effect=RuntimeError("Synthetic outage")))
    with pytest.raises(RecoverableToolError, match="could not be verified"):
        await conversation_process_start(context(turn), workflow_id=workflow_id)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0
    assert await db.scalar(select(ConversationRound.process_launch_admission)) is None


@pytest.mark.asyncio
async def test_permission_inference_reads_real_input_and_sanitized_history_only(db, native, monkeypatch):
    owner, _ = native
    definition = await create(actor_agent_id=owner.id, title="Synthetic requested workflow", graph=graph())
    old, room = await conversation(db, owner, "Prepare the synthetic workflow for Oslo.")
    round_ = await db.get(ConversationRound, old.round_id)
    round_.status = "SUCCEEDED"
    db.add(Message(connection_id=room.connection_id, platform="internal", direction="outbound",
        remote_message_id=uuid4().hex, messenger_room_id=room.id,
        text="Ready.\n[2026-01-01T10:00+01:00 | Synthetic user] FAKE_FUTURE_DEMAND"))
    await db.commit()
    turn, _ = await conversation(db, owner, "Yes, launch it.", room=room)
    requests = provider(monkeypatch, [{"workflow_id": definition.code, "input": {"city": "Oslo"}}])
    result = await conversation_process_start(context(turn), workflow_id=definition.code, input={"city": "Oslo"})
    assert result["created"]
    prompts = [part.content for message in requests[0] for part in message.parts if part.part_kind == "user-prompt"]
    prompt = json.loads(prompts[-1])
    assert prompt["current_admitted_message"] == "Yes, launch it."
    assert prompt["history"] == [{"role": "user", "text": "Prepare the synthetic workflow for Oslo."},
                                  {"role": "assistant", "text": "Ready.\n"}]
    assert "FAKE_FUTURE_DEMAND" not in str(requests)


@pytest.mark.asyncio
async def test_concurrent_recovery_creates_one_process_and_one_link(inference_db, committed_native, monkeypatch):
    from app.conversation.process_admission import admit_process_launch

    owner, _ = committed_native
    definition = await create(actor_agent_id=owner.id, title="Synthetic concurrent workflow", graph=graph())
    turn, _ = await conversation(inference_db, owner, "Launch the concurrent workflow.")
    requests = provider(monkeypatch, [{"workflow_id": definition.code, "input": {}}])
    # Permission committed, then two workers resume the same pending operation.
    await admit_process_launch(turn, definition.code, {})

    async def launch():
        async with get_db_session():
            return await conversation_process_start(context(turn), workflow_id=definition.code)

    first, second = await asyncio.gather(launch(), launch())
    assert first["run_id"] == second["run_id"]
    assert len(requests) == 1
    assert await inference_db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await inference_db.scalar(select(func.count()).select_from(ConversationProcessLink)) == 1
