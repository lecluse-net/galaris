"""Qualify the bundled Claude SDK through Chat's Deep submission lifecycle."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.agent import Agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.chat.tests.test_deep import room_info, send
from app.connection import Connection
from app.connection.models import ConnectionFunctionState
from app.conversation import DeepSession, deep
from app.conversation.models import DeepSubmission
from app.document.data.models import Dataset
from app.harness import claude_driver
from app.harness.claude_session import ClaudeSession
from app.llm import llm_call_service
from app.llm.facade import EmbeddedDeepInference
from app.llm.models import LLMCall, LLMInference, LLMInferenceAttempt
from app.llm.profile_models import LlmProfile
from app.messenger import create_internal_room
from app.services import ServiceModel
from app.services.authorization_models import ActionAuthorization
from app.services.facade import answer_action, wake_authorization_context
from core.database import get_db_session
from core.params import runtime_settings
from core.util import get_encryption_service
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [
    "approved", "denied", "cancelled", "denied-budget-exhausted", "denied-legacy", "approved-tool-budget",
])
async def test_claude_deep_parks_and_resumes_only_the_approved_submission(attachment_context, runtime, monkeypatch, tmp_path, decision):
    db, model, requests, mode = runtime
    context = attachment_context
    actor = context["user_id"]
    room = context["room_id"]
    agent = await db.get(Agent, context["agent_id"])
    workspace = tmp_path / "claude"
    workspace.mkdir()
    exhausted = decision == "denied-budget-exhausted"
    legacy = decision == "denied-legacy"
    tool_budget = decision == "approved-tool-budget"
    approved = decision in {"approved", "approved-tool-budget"}
    initial_limit = 4 if tool_budget else 1 if exhausted else 3
    current_limit = 6 if tool_budget else 4 if legacy else 2
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", initial_limit)
    if tool_budget:
        monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 1)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    mode["concurrent"] = True
    profile = LlmProfile(label="Synthetic Deep approval profile", text_standard_llm_id=model.id)
    db.add(profile)
    await db.flush()
    agent.agent_driver = "claude_embedded"
    agent.profile_id = profile.id
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    connection = await db.scalar(select(Connection).where(Connection.service_id == service.id, Connection.agent_id == agent.id))
    if connection is None:
        connection = Connection(service_id=service.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
    db.add_all([
        ConnectionFunctionState(connection_id=connection.id, function_name="file_create", state="ask", enabled=False),
        ConnectionFunctionState(connection_id=connection.id, function_name="file_schemes", state="enabled", enabled=True),
    ])
    await db.commit()

    first_text = "Synthetic Deep approval for a dataset"
    next_text = "Synthetic Deep submission queued behind the approval"
    title = f"Synthetic Deep dataset {uuid4().hex}"
    arguments = {"path": "data://", "name": title, "content": json.dumps({"record": "fictional"})}
    followup_requested = False

    def choose_tools(body):
        nonlocal followup_requested
        data = json.dumps(body["messages"])
        if (tool_budget and not followup_requested and first_text in data and next_text not in data
                and "Galaris has resolved the earlier tool authorization" in data):
            followup_requested = True
            return [("synthetic-deep-after-approval", "mcp__galaris__file_schemes", {})]
        if first_text in data and next_text not in data and not any(item["role"] == "tool" for item in body["messages"]):
            return [("synthetic-deep-mutation", "mcp__galaris__file_create", arguments)]
        return []

    mode["tool_calls_for"] = choose_tools
    datasets = select(Dataset).where(Dataset.title == title)
    await send(context, room, f"@deep {first_text}")
    await send(context, room, f"@deep {next_text}")
    first, successor = (await room_info(context, room))["submissions"]
    submission_id, session_id = UUID(first["id"]), UUID(first["session_id"])
    authorization_context = f"deep:{session_id}:submission:{submission_id}"

    async with _gateway(monkeypatch), AsyncClient() as gateway, asyncio.timeout(45):
        try:
            await deep.start_deep()
            while True:
                row = await db.get(DeepSubmission, submission_id, populate_existing=True)
                if row.state == "waiting_approval":
                    break
                assert row.state in {"queued", "running"}, await room_info(context, room)
                await asyncio.sleep(0.025)
            previous = UUID(row.inference_admission["claim"])
            stored = row.encrypted_checkpoint
            assert stored and title not in stored and row.lease_token is None
            public_first, public_next = (await room_info(context, room))["submissions"]
            assert public_first["response_message_id"] is None
            assert public_next["state"] == "queued" and not public_next["approvals"]
            [approval_id] = public_first["approvals"]
            approval_id = UUID(approval_id)
            approval = await db.get(ActionAuthorization, approval_id)
            assert approval.status == "pending" and approval.context_key == authorization_context
            assert not list(await db.scalars(datasets))
            assert not await wake_authorization_context(agent.id, authorization_context)
            assert await deep._claim() is None
            await deep.stop_deep()
            parked_calls = len(requests)
            assert parked_calls == (1 if exhausted else 2)
            if legacy:
                row.inference_admission = {key: value for key, value in row.inference_admission.items() if key != "request_limit"}
                await db.commit()
            monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", current_limit)
            if tool_budget:
                monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 4)

            if decision == "cancelled":
                stopped = await context["client"].post(f"/api/chat/rooms/{room}/deep/{submission_id}/stop", headers=context["headers"])
                assert stopped.status_code == 204
                async with get_db_session():
                    assert not await answer_action(approval_id, user_id=actor, approved=True)
            else:
                assert await answer_action(approval_id, user_id=actor, approved=approved)
                assert await wake_authorization_context(agent.id, authorization_context)
                assert await wake_authorization_context(agent.id, authorization_context)

            await deep.start_deep()
            while True:
                public_first, public_next = (await room_info(context, room))["submissions"]
                assert public_next["state"] != "failed" and (exhausted or public_first["state"] != "failed"), (public_first, public_next)
                if public_next["state"] == "completed":
                    break
                await asyncio.sleep(0.025)
            expected_state = "failed" if exhausted else "cancelled" if decision == "cancelled" else "completed"
            assert public_first["state"] == expected_state
            assert not public_first["approvals"] and not public_next["approvals"]
            assert public_next["response_message_id"]
            assert bool(public_first["response_message_id"]) == (expected_state == "completed")
            if exhausted:
                assert public_first["failure"]["code"] == "quota"
            await db.refresh(approval)
            assert approval.status == ("completed" if approved else "invalidated" if decision == "cancelled" else "denied")
            assert len(list(await db.scalars(datasets))) == int(approved)
            settled = await db.get(DeepSubmission, submission_id, populate_existing=True)
            assert (UUID(settled.inference_admission["claim"]) != previous) == (decision != "cancelled")
            assert settled.inference_admission["request_limit"] == (current_limit if legacy else initial_limit)
            next_row = await db.get(DeepSubmission, UUID(successor["id"]), populate_existing=True)
            assert next_row.inference_admission["request_limit"] == current_limit
            origin = EmbeddedDeepInference(session_id=session_id, run_id=submission_id, attempt_id=previous,
                agent_id=agent.id, model_id=model.id, model_code=model.code,
                request_limit=settled.inference_admission["request_limit"])
            stale = await gateway.post(f"{claude_driver.CLAUDE_GATEWAY}/v1/messages", headers={"x-api-key": origin.credential()},
                json={"model": model.code, "max_tokens": 16, "messages": [{"role": "user", "content": "Stale claim"}]})
            assert stale.status_code == 403
            calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id).order_by(LLMCall.started_at)))
            journal = dict((await db.execute(
                select(LLMCall.id, LLMInference.request)
                .join(LLMInferenceAttempt, LLMInferenceAttempt.id == LLMCall.inference_attempt_id)
                .join(LLMInference, LLMInference.id == LLMInferenceAttempt.inference_id)
                .where(LLMCall.agent_id == agent.id)
            )).tuples().all())
            assert set(journal) == {call.id for call in calls}
            resumed = [call for call in calls if "Galaris has resolved the earlier tool authorization" in json.dumps(call.request_messages)
                       and call.deep_submission_id == submission_id]
            resumed_calls = int(expected_state == "completed") + int(tool_budget)
            assert len(resumed) == resumed_calls
            submission_calls = [call for call in calls if call.deep_submission_id == submission_id]
            assert len(submission_calls) == parked_calls + resumed_calls
            assert [journal[call.id]["embedded_origin"]["attempt_id"] for call in submission_calls] == (
                [str(previous)] * parked_calls + [settled.inference_admission["claim"]] * resumed_calls
            )
            successor_calls = [call for call in calls if call.deep_submission_id == next_row.id]
            assert successor_calls
            assert {journal[call.id]["embedded_origin"]["attempt_id"] for call in successor_calls} == {
                next_row.inference_admission["claim"],
            }
            if tool_budget:
                assert "tool call limit" in json.dumps(resumed[-1].request_messages)
                assert settled.inference_admission["tool_call_limit"] == settled.inference_admission["tool_calls_used"] == 1
                assert next_row.inference_admission["tool_call_limit"] == 4
            assert all(call.deep_session_id == session_id and call.agent_run_id == call.deep_submission_id for call in calls)
            assert list(workspace.iterdir()) == []
        finally:
            await deep.stop_deep()


@pytest.mark.asyncio
async def test_embedded_claude_deep_continues_history_and_fences_each_submission(attachment_context, runtime, monkeypatch, tmp_path):
    db, model, requests, mode = runtime
    context = attachment_context
    agent = await db.get(Agent, context["agent_id"])
    assert agent is not None
    workspace = tmp_path / "claude"
    workspace.mkdir()
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    mode["concurrent"] = True
    mode["gate"] = asyncio.Event()
    model.provider.max_concurrent_calls = 4
    profile = LlmProfile(label="Synthetic Deep profile", text_standard_llm_id=model.id)
    db.add(profile)
    await db.flush()
    agent.agent_driver = "claude_embedded"
    agent.profile_id = profile.id
    files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    assert files is not None
    existing = await db.scalar(select(Connection.id).where(Connection.agent_id == agent.id, Connection.service_id == files.id))
    if existing is None:
        db.add(Connection(service_id=files.id, agent_id=agent.id, active=True))
    await db.commit()
    first_room = context["room_id"]
    other_room = (await create_internal_room(actor_user_id=context["user_id"], agent_id=agent.id)).id
    await db.commit()

    first_text = "Synthetic Deep first instruction"
    next_text = "Synthetic Deep follow-up in the same session"
    other_text = "Synthetic Deep work from a different room"

    def choose_tools(body):
        last_user = max(index for index, item in enumerate(body["messages"]) if item["role"] == "user")
        if any(item["role"] == "tool" for item in body["messages"][last_user + 1:]):
            return []
        return [("synthetic-deep-read", "mcp__galaris__file_schemes", {})]

    mode["tool_calls_for"] = choose_tools
    for room, text in ((first_room, first_text), (first_room, next_text), (other_room, other_text)):
        await send(context, room, f"@deep {text}")
    # Fetch exact submission IDs from Chat, where events are also replayed.
    first, next_ = (await room_info(context, first_room))["submissions"]
    [other] = (await room_info(context, other_room))["submissions"]
    assert first["session_id"] == next_["session_id"] != other["session_id"]

    async def admitted(value):
        item = await db.get(DeepSubmission, UUID(value["id"]), populate_existing=True)
        assert item is not None and item.state == "running" and item.inference_admission is not None
        return EmbeddedDeepInference(
            session_id=item.session_id, run_id=item.id, attempt_id=UUID(item.inference_admission["claim"]),
            agent_id=agent.id, model_id=model.id, model_code=model.code,
            request_limit=item.inference_admission["request_limit"],
        )

    async with _gateway(monkeypatch), AsyncClient() as gateway, asyncio.timeout(55):
        try:
            await deep.start_deep()
            while len(requests) < 2:
                await asyncio.sleep(0.015)
            assert len(requests) == 2
            origin, other_origin = await admitted(first), await admitted(other)
            url = f"{claude_driver.CLAUDE_GATEWAY}/v1/messages"
            body = {"model": model.code, "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Unauthenticated data must never reach the model"}]}
            for forged in (
                origin.model_copy(update={"run_id": UUID(next_["id"])}),
                origin.model_copy(update={"session_id": other_origin.session_id}),
                origin.model_copy(update={"attempt_id": other_origin.attempt_id}),
                origin.model_copy(update={"model_id": model.id + 1}),
                origin.model_copy(update={"request_limit": origin.request_limit + 1}),
                origin.model_copy(update={"agent_id": context["other_agent_id"]}),
            ):
                denied = await gateway.post(url, json=body, headers={"x-api-key": forged.credential()})
                assert denied.status_code == 403
            conflicting = await gateway.post(url, json=body, headers={
                "x-api-key": origin.credential(), "X-Galaris-Deep-Context": str(other_origin.session_id),
            })
            assert conflicting.status_code == 403
            assert len(requests) == 2
            mode["gate"].set()

            while True:
                room_a, room_b = await room_info(context, first_room), await room_info(context, other_room)
                finished = [*room_a["submissions"], *room_b["submissions"]]
                assert not any(item["state"] == "failed" for item in finished), finished
                if all(item["state"] == "completed" for item in finished):
                    break
                await asyncio.sleep(0.025)
            stale = await gateway.post(url, json=body, headers={"x-api-key": origin.credential()})
            assert stale.status_code == 403

            calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id)))
            assert len(calls) == len(requests) == 6
            session = await db.get(DeepSession, origin.session_id, populate_existing=True)
            assert session is not None and session.native_history is not None
            assert first_text not in session.native_history and next_text not in session.native_history
            tape = ClaudeSession.from_deep_history(get_encryption_service().decrypt(session.native_history), session.id)
            assert first_text in tape.transcript and next_text in tape.transcript
            with pytest.raises(ValueError, match="does not belong"):
                ClaudeSession.from_deep_history(tape.deep_history(session.id), other_origin.session_id)
            for item, text in zip((first, next_, other), (first_text, next_text, other_text), strict=True):
                identifier, session_id = UUID(item["id"]), UUID(item["session_id"])
                subset = [call for call in calls if call.deep_submission_id == identifier]
                assert len(subset) == 2
                for call in subset:
                    assert call.deep_session_id == session_id and call.agent_run_id == identifier
                    assert call.correlation_ref == f"deep:{session_id}:submission:{identifier}"
                    assert call.requester_user_id == context["user_id"] and call.purpose == "conversation.deep"
                    assert call.task_id is None and call.task_attempt_id is None and call.conversation_round_id is None
                    wire = json.dumps(call.request_messages)
                    assert text in wire
                    assert (other_text in wire) is (text == other_text)
                    assert (next_text in wire) is (text == next_text)
                    assert (first_text in wire) is (text != other_text)
            projected = await llm_call_service.serialize_calls(await llm_call_service.list_calls(deep_room_id=first_room))
            assert {str(row.deep_submission_id) for row in projected} == {first["id"], next_["id"]}
            assert all(row.deep_room_id == first_room for row in projected)
            assert all(item["response_message_id"] for item in finished)
            assert list(workspace.iterdir()) == []

            interrupted_text = "Synthetic Deep turn interrupted while the provider is active"
            mode["gate"] = asyncio.Event()
            await send(context, first_room, interrupted_text)
            interrupted = (await room_info(context, first_room))["submissions"][-1]
            interrupt_id = UUID(interrupted["id"])
            while len(requests) < 7:
                await asyncio.sleep(0.015)
            interrupt_origin = await admitted(interrupted)
            stopped = await context["client"].post(
                f"/api/chat/rooms/{first_room}/deep/{interrupt_id}/stop", headers=context["headers"],
            )
            assert stopped.status_code == 204
            rejected = await gateway.post(url, json=body, headers={"x-api-key": interrupt_origin.credential()})
            assert rejected.status_code == 403
            while True:
                interrupted = (await room_info(context, first_room))["submissions"][-1]
                if interrupted["state"] == "interrupted":
                    break
                assert interrupted["state"] == "running", interrupted
                await asyncio.sleep(0.025)
            assert not interrupted["response_message_id"]
            interrupt_call = await db.scalar(select(LLMCall).where(LLMCall.deep_submission_id == interrupt_id))
            assert interrupt_call is not None and interrupt_call.agent_run_id == interrupt_id
            assert interrupt_call.deep_session_id == session.id and interrupted_text in json.dumps(interrupt_call.request_messages)
            assert len(requests) == 7
            await db.refresh(session)
            assert ClaudeSession.from_deep_history(
                get_encryption_service().decrypt(session.native_history), session.id,
            ) == tape
            assert list(workspace.iterdir()) == []
        finally:
            mode["gate"].set()
            await deep.stop_deep()
