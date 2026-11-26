"""Run native Process admission through both embedded Chat loops and the provider journal."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.connection import Connection, connection_service
from app.conversation import ConversationRound, ConversationRoundAttempt
from app.conversation import controller as round_controller, scheduler as round_scheduler
from app.conversation.models import ConversationProcessLink
from app.conversation.service import claim_next_round
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.llm import LLMCallPurpose, LlmProfile
from app.llm.models import LLMCall
from app.process import registry as process_registry
from app.process.models import ProcessRun, ProcessStartJob
from app.process.native_definitions import create
from app.process.native_engine import NativeProcessEngine
from app.process.tests.test_native_bpmn import graph
from app.services import ServiceModel, sync_integrated_service_connections
from core.database import get_db_session
from core.params import runtime_settings
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime as runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize(("requested", "occurrences"), [
    pytest.param(0, [1], id="unrequested"),
    pytest.param(1, [1, 1], id="explicit-replay"),
    pytest.param(1, [1, 2], id="excess-occurrence"),
    pytest.param(2, [1, 2], id="two-explicit-occurrences"),
])
async def test_model_proposals_cannot_expand_the_human_process_request(
    attachment_context, runtime, monkeypatch, tmp_path, request, driver, requested, occurrences,
):
    db, model, requests, mode = runtime
    context = attachment_context
    if "galaris" not in process_registry.codes():
        process_registry.register(NativeProcessEngine())
        request.addfinalizer(lambda: process_registry.unregister("galaris"))
    agent = await db.get(Agent, context["agent_id"])
    assert agent is not None
    title = "Synthetic monthly inventory review"
    definition = await create(actor_agent_id=agent.id, title=title, graph=graph("Reconcile the synthetic inventory."))
    await sync_integrated_service_connections(agent.id)
    process_connection = await db.scalar(select(Connection).join(ServiceModel).where(
        Connection.agent_id == agent.id, ServiceModel.code == "process",
    ))
    assert process_connection is not None and process_connection.active
    tool = "process_start_conversation"
    await connection_service.set_connection_function_state(process_connection.id, tool, "enabled")
    profile = LlmProfile(label="Synthetic Process profile", text_low_llm_id=model.id, text_standard_llm_id=model.id)
    db.add(profile)
    await db.flush()
    agent.profile_id, agent.agent_driver = profile.id, driver
    await db.commit()
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 5)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(round_controller, "_controller", HarnessConversationController())

    text = {
        0: f"Explain what {title} does without starting it.",
        1: f"Start the {title} once.",
        2: f"Start the {title} twice, as two separate runs.",
    }[requested]
    arguments = {"workflow_id": definition.engine_process_id, "input": {}}
    decisions: list[dict[str, object]] = []
    replies: dict[str, str] = {}
    receipts: list[str] = []
    proposals = 0

    def choose_tools(body):
        nonlocal proposals
        functions = [entry["function"] for entry in body.get("tools", [])]
        admission = next((entry for entry in functions if "launches" in entry["parameters"].get("properties", {})), None)
        if admission is not None:
            prompt = next(message["content"] for message in body["messages"] if message["role"] == "user")
            decisions.append(json.loads(prompt))
            return [("synthetic-admission", admission["name"], {"launches": [arguments] * requested})]
        launch = next((entry["name"] for entry in functions if entry["name"] in {tool, f"mcp__galaris__{tool}"}), None)
        assert launch is not None, [entry["name"] for entry in functions]
        for message in body["messages"]:
            if message["role"] == "tool":
                replies[message["tool_call_id"]] = str(message["content"])
        if proposals < len(occurrences):
            occurrence = occurrences[proposals]
            proposals += 1
            return [(f"synthetic-launch-{proposals}", launch, {**arguments, "occurrence": occurrence})]
        return []

    mode.update(concurrent=True, tool_calls_for=choose_tools, chat_response_ids=receipts)
    async with _gateway(monkeypatch), asyncio.timeout(45):
        sent = await context["client"].post(f"/api/chat/rooms/{context['room_id']}/messages", headers=context["headers"],
            json={"text": text, "language": "en", "client_message_id": str(uuid4())})
        assert sent.status_code == 201, sent.text
        round_ = await claim_next_round("paired-chat-process")
        assert round_ is not None and round_.room_id == context["room_id"] and round_.lease_token is not None
        round_id, lease = round_.id, round_.lease_token
        await db.commit()
        await round_scheduler._execute_action(round_id, lease)

    [decision] = decisions
    assert str(decision["current_admitted_message"]).endswith(f"] {text}")
    assert decision["history"] == [] and decision["already_launched_in_this_round"] == []
    async with get_db_session() as reader:
        round_ = await reader.get(ConversationRound, round_id)
        assert round_ is not None and round_.status == "SUCCEEDED" and round_.driver_code == driver
        assert round_.process_launch_admission is not None
        assert round_.process_launch_admission["plan"]["launches"] == [{**arguments, "typed_values": False}] * requested
        [attempt] = await reader.scalars(select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id == round_id))
        links = (await reader.scalars(select(ConversationProcessLink).where(ConversationProcessLink.round_id == round_id))).all()
        runs = (await reader.scalars(select(ProcessRun).where(ProcessRun.process_id == definition.id))).all()
        calls = (await reader.scalars(select(LLMCall).where(LLMCall.conversation_round_id == round_id)
                                      .order_by(LLMCall.started_at))).all()
        assert len(runs) == len(links) == requested
        assert {link.process_run_id for link in links} == {run.id for run in runs}
        assert len(replies) == len(occurrences), replies
        for run in runs:
            assert run.launcher_agent_id == agent.id
            assert run.status == "queued" and run.task_id is None
            [job] = await reader.scalars(select(ProcessStartJob).where(ProcessStartJob.run_id == run.id))
            assert job.status == "pending"
            assert any(str(run.id) in reply for reply in replies.values()), replies

    if requested == 0:
        [refusal] = replies.values()
        assert "outside the current request's launch permission" in refusal.lower(), refusal
    elif requested == 1 and occurrences == [1, 1]:
        assert all(str(runs[0].id) in reply for reply in replies.values()), replies
        assert sum("already_linked" in reply for reply in replies.values()) == 1
    elif requested == 1:
        assert any("occurrence counts identical launches" in reply.lower() for reply in replies.values()), replies

    assert len(requests) == len(receipts) == len(calls) == len(occurrences) + 2
    assert [call.upstream_request_id for call in calls] == receipts
    assert all(call.agent_id == agent.id and call.agent_run_id == round_id and call.task_id is None
               and call.status == "completed" for call in calls)
    assert [call.purpose for call in calls].count(LLMCallPurpose.CONVERSATION_PROCESS_ADMISSION) == 1
    loop_calls = [call for call in calls if call.purpose == LLMCallPurpose.CONVERSATION_TEXT]
    assert len(loop_calls) == len(calls) - 1
    if driver == "claude_embedded":
        assert {call.correlation_ref for call in loop_calls} == {f"round:{round_id}:attempt:{attempt.id}"}
