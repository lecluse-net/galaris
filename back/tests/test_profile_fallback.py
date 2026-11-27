"""Synthetic provider outages through the real SDK, journal, and tool loop."""

import asyncio
import json
from collections.abc import Mapping
from contextlib import aclosing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.agent.schemas import AgentUpdate
from app.agent import agent_service
from app.agent.facade import build_run_request, stream as stream_agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.connection import Connection
from app.connection.models import ConnectionFunctionState
from app.conversation import controller as round_controller, scheduler as round_scheduler
from app.conversation.models import ConversationRoundAttempt
from app.conversation.service import claim_next_round
from app.document.data.models import Dataset
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.llm import LLM, LLMProvider, LlmProfile, llm_call_service, proxy_service
from app.llm.models import LLMCall, LLMInference
from app.llm.pydantic_ai_utils import build_model_for_llm
from app.llm import inference_execution
from app.llm.contracts import TextInferenceRequest
from app.llm.facade import run_text_inference, prepare_inference, control_inference, stream_inference, read_inference_result
from app.llm import llm_service, model_usages, profile_service
from app.llm.profile_fallback import ProfileFallbackRoute, provider_failure_allows_fallback
from app.llm.facade import read_inference
from app.services import ServiceModel
from app.task import Task, TaskStatus
from app.task.models import TaskAttempt
from pydantic_ai.exceptions import ModelHTTPError
from core.database import get_db_session, middleware
from core.params import runtime_settings
from core.user import UserModel
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime as runtime


@pytest_asyncio.fixture
async def failover(committed_database, monkeypatch):
    monkeypatch.setattr(llm_call_service, "AsyncSessionLocal", committed_database)
    async with get_db_session() as db:
        user = UserModel(email=f"fallback-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
        title = Title(label="Synthetic fallback", gender="F")
        db.add_all([user, title])
        providers = [LLMProvider(name=f"fallback-{uuid4().hex}", base_url=f"https://{name}.test/v1",
                                provider_type="openai_compatible", is_active=True) for name in ("primary", "secondary")]
        db.add_all(providers)
        await db.flush()
        models = [LLM(llm_provider_id=p.id, provider=p, code=f"fallback-{uuid4().hex}",
                      llm_name=name, label=name) for p, name in zip(providers, ("primary", "secondary"))]
        db.add_all(models)
        await db.flush()
        profiles = [LlmProfile(code=f"fallback-{uuid4().hex}", label=name,
                               text_low_llm_id=m.id, text_standard_llm_id=m.id)
                    for m, name in zip(models, ("primary", "secondary"))]
        db.add_all(profiles)
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"fallback-{uuid4().hex}",
                      first_name="Synthetic", last_name="", profile_id=profiles[0].id,
                      fallback_profile_id=profiles[1].id)
        db.add(agent)
        await db.commit()
        try:
            yield db, agent, models, profiles
        finally:
            await inference_execution.stop()


def sse(delta, finish=None):
    return ('data: ' + json.dumps({"id": "synthetic", "object": "chat.completion.chunk", "created": 1,
            "model": "synthetic", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + '\n\n').encode()


@pytest.mark.asyncio
@pytest.mark.parametrize(("driver", "status"), [
    pytest.param("internal", 429, id="pydantic-eligible"),
    pytest.param("internal", 422, id="pydantic-ineligible"),
    pytest.param("claude_embedded", 429, id="claude-eligible"),
    pytest.param("claude_embedded", 422, id="claude-ineligible"),
    pytest.param("claude_embedded", "empty", id="claude-reasoning-only"),
])
async def test_chat_preserves_call_origin_when_a_profile_can_fail_over(
    attachment_context, runtime, monkeypatch, tmp_path, driver, status,
):
    db, primary, requests, mode = runtime
    context = attachment_context
    agent = await db.get(Agent, context["agent_id"])
    assert agent is not None
    secondary = LLM(llm_provider_id=primary.llm_provider_id, code=f"fallback-{uuid4().hex}",
                    llm_name="synthetic-secondary", label="Synthetic secondary",
                    cost_per_input_token=2, cost_per_output_token=5)
    db.add(secondary)
    await db.flush()
    profiles = [
        LlmProfile(label=f"Synthetic {model.llm_name}", text_low_llm_id=model.id, text_standard_llm_id=model.id)
        for model in (primary, secondary)
    ]
    db.add_all(profiles)
    await db.flush()
    agent.agent_driver = driver
    agent.profile_id = profiles[0].id
    agent.fallback_profile_id = profiles[1].id
    await db.commit()
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 2)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(round_controller, "_controller", HarnessConversationController())
    provider_receipts = []
    mode.update(concurrent=True, chat_response_ids=provider_receipts)
    rejection = (status, {"message": f"Synthetic rejection {status}"})
    if status == "empty":
        mode.update(outputs=["", "Bonjour !"], chat_json="Bonjour !")
    elif status == 429:
        mode["first_error"] = rejection
    else:
        # An invalid request continues to fail even if the SDK tries another transport.
        mode["error_for"] = lambda body: rejection if body["model"] == primary.llm_name else None

    async with _gateway(monkeypatch):
        submitted = await context["client"].post(f"/api/chat/rooms/{context['room_id']}/messages",
            headers=context["headers"], json={"client_message_id": str(uuid4()), "language": "en",
                                              "text": "Give a short greeting in French."})
        assert submitted.status_code == 201, submitted.text
        round_ = await claim_next_round("paired-profile-test")
        assert round_ is not None and round_.lease_token is not None and round_.driver_code == driver
        assert round_.room_id == context["room_id"]
        round_.response_only = True
        round_id, lease = round_.id, round_.lease_token
        await db.commit()
        await round_scheduler._execute_action(round_id, lease)

    detail = await context["client"].get(f"/api/conversations/rounds/{round_id}", headers=context["headers"])
    assert detail.status_code == 200, detail.text
    record = detail.json()
    calls = list(await db.scalars(select(LLMCall).where(
        LLMCall.conversation_round_id == round_id, LLMCall.purpose == "conversation.text",
    ).order_by(LLMCall.started_at)))
    assert 1 <= len(requests) <= 2
    can_fail_over = status in {429, "empty"}
    expected_models = [primary, secondary] if can_fail_over else [primary] * len(requests)
    assert [request["model"] for request in requests] == [model.llm_name for model in expected_models]
    assert [call.llm_id for call in calls] == [model.id for model in expected_models]
    assert all(call.agent_id == agent.id and call.agent_run_id == round_id and call.task_id is None for call in calls)
    attempt = await db.scalar(select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id == round_id))
    assert attempt is not None
    if driver == "claude_embedded":
        assert {call.correlation_ref for call in calls} == {f"round:{round_id}:attempt:{attempt.id}"}
    assert calls[0].status == "error"
    if can_fail_over:
        assert record["status"] == "SUCCEEDED" and record["response_text"] == "Bonjour !"
        assert record["execution_result"]["metadata"]["driver_code"] == driver
        if status == "empty":
            assert calls[0].finish_reason == "stop" and calls[0].reasoning and not calls[0].response_text
            assert [call.upstream_request_id for call in calls] == provider_receipts
            assert calls[1].fallback_reason and "without an answer" in calls[1].fallback_reason
        receipt = provider_receipts[-1]
        fallback = calls[1]
        assert fallback.status == "completed" and fallback.upstream_request_id == receipt
        assert fallback.fallback_from_llm_id == primary.id and fallback.fallback_profile_id == profiles[1].id
        assert fallback.cost > 0 and record["execution_result"]["cost"] == pytest.approx(sum(call.cost for call in calls))
    else:
        assert record["status"] == "FROZEN" and attempt.status == "ERROR" and not record["response_text"]
        assert not provider_receipts
        assert all(call.status == "error" and call.fallback_from_llm_id is None for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize(("effort", "dedicated_high", "cut_after_tool"), [
    pytest.param("standard", True, None, id="standard"),
    pytest.param("high", True, None, id="high-shared-primary"),
    pytest.param("high", False, None, id="high-without-primary-tier"),
    pytest.param("standard", True, "text", id="cut-after-tool-text"),
    pytest.param("standard", True, "tool_calls", id="cut-after-tool-proposal"),
])
async def test_task_keeps_the_secondary_after_failover_and_one_native_tool_effect(
    runtime, committed_database, monkeypatch, tmp_path, driver, effort, dedicated_high, cut_after_tool,
):
    db, primary, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 4)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    standard_secondary, high_secondary = [
        LLM(llm_provider_id=primary.llm_provider_id, code=f"fallback-{uuid4().hex}",
            llm_name=f"task-secondary-{tier}", label=f"Synthetic task secondary {tier}",
            cost_per_input_token=2, cost_per_output_token=5)
        for tier in ("standard", "high")
    ]
    secondary = high_secondary if effort == "high" and dedicated_high else standard_secondary
    user = UserModel(email=f"task-fallback-{uuid4().hex}@example.test", hashed_password="unused")
    db.add_all([standard_secondary, high_secondary, user])
    await db.flush()
    profiles = [
        LlmProfile(label="Synthetic primary", text_standard_llm_id=primary.id,
                   text_high_llm_id=primary.id if dedicated_high else None),
        LlmProfile(label="Synthetic secondary", text_standard_llm_id=standard_secondary.id,
                   text_high_llm_id=high_secondary.id),
    ]
    db.add_all(profiles)
    await db.flush()
    agent = Agent(user_id=user.id, title_id=await db.scalar(select(Title.id).limit(1)),
                  code=f"task-fallback-{uuid4().hex}", first_name="Synthetic", last_name="Fallback",
                  agent_driver=driver, profile_id=profiles[0].id, fallback_profile_id=profiles[1].id)
    db.add(agent)
    await db.flush()
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    assert service is not None
    connection = Connection(agent_id=agent.id, service_id=service.id, active=True)
    db.add(connection)
    await db.flush()
    db.add(ConnectionFunctionState(connection_id=connection.id, function_name="file_create", state="enabled", enabled=True))
    await db.refresh(agent, attribute_names=["title"])

    async def admit(label, objective):
        lease = uuid4()
        task = Task(label=label, objective=objective, agent=agent, requester_user_id=user.id,
                    status=TaskStatus.EXEC, effort=effort, lease_token=lease, lease_owner="task-fallback-test",
                    attempt_count=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", worker_id="task-fallback-test",
                              lease_token=lease)
        db.add(attempt)
        await db.commit()
        admitted = await build_run_request(task)
        assert admitted.model.id == primary.id and admitted.attempt_id == attempt.id
        assert admitted.model.requested_effort == effort
        assert admitted.model.fallback_used == (effort == "high" and not dedicated_high)
        await db.commit()
        return task, admitted

    task, admitted = await admit("Synthetic fallback with a durable effect", "Create the synthetic inventory once and confirm.")

    title = "Synthetic inventory via fallback"
    abandoned_title = "Synthetic inventory from an abandoned proposal"
    tool_name = "file_create" if driver == "internal" else "mcp__galaris__file_create"
    receipt_id = "synthetic-fallback-file"
    provider_receipts = []

    tool_request = 1 if cut_after_tool else 2

    def choose_tools(_body: Mapping[str, object]):
        if cut_after_tool == "tool_calls" and len(requests) == 2:
            return [("abandoned-file", tool_name, {"path": "data://", "name": abandoned_title, "content": '{}'})]
        if len(requests) != tool_request:
            return []
        return [(receipt_id, tool_name, {"path": "data://", "name": title, "content": '{"stock":42}'})]

    mode.update(concurrent=True, tool_calls_for=choose_tools, chat_response_ids=provider_receipts)
    if cut_after_tool:
        mode.update(outputs=["unused", "Abandoned draft", "Bonjour !", "Bonjour !"], chat_json="Bonjour !",
                    error_after_partial=lambda body, delta: body["model"] == primary.llm_name
                    and ("content" if cut_after_tool == "text" else "tool_calls") in delta
                    and any(message["role"] == "tool" for message in body["messages"]))
    else:
        mode["first_error"] = (429, {"message": "Synthetic primary saturation"})
    async with _gateway(monkeypatch), asyncio.timeout(30), aclosing(stream_agent(admitted)) as events:
        [result] = [event.result async for event in events if event.result is not None]

    docs = (await db.scalars(select(Dataset).where(Dataset.owner_agent_id == agent.id, Dataset.title == title))).all()
    assert len(docs) == 1 and json.loads(docs[0].content) == {"stock": 42}
    assert await db.scalar(select(Dataset.id).where(Dataset.owner_agent_id == agent.id,
                                                    Dataset.title == abandoned_title)) is None
    assert result.success and result.result == "Bonjour !", ([request["model"] for request in requests], result.failure)
    continuation = requests[-1]["messages"]
    [proposed] = [tool for message in continuation for tool in message.get("tool_calls", [])]
    [receipt] = [message for message in continuation if message.get("role") == "tool"]
    assert receipt["tool_call_id"] == proposed["id"]
    assert f"data://{docs[0].id}" in json.dumps(receipt["content"])
    assert "Aba" not in json.dumps(continuation) and abandoned_title not in json.dumps(continuation)
    calls = (await db.scalars(select(LLMCall).where(LLMCall.task_id == task.id).order_by(LLMCall.started_at))).all()
    assert [call.status for call in calls] == (["completed", "error", "completed"] if cut_after_tool
                                               else ["error", "completed", "completed"])
    assert [(call.task_attempt_id, call.agent_run_id, call.requester_user_id) for call in calls] == [
        (admitted.attempt_id, admitted.run_id, user.id),
    ] * 3
    physical_responses = calls if cut_after_tool else calls[1:]
    assert [call.upstream_request_id for call in physical_responses] == provider_receipts
    models = (primary, primary, secondary) if cut_after_tool else (primary, secondary, secondary)
    assert [request["model"] for request in requests] == [model.llm_name for model in models]
    assert [call.llm_id for call in calls] == [model.id for model in models]
    assert all(call.fallback_from_llm_id == primary.id and call.fallback_profile_id == profiles[1].id
               for call in calls if call.llm_id == secondary.id)
    assert result.cost > 0 and result.cost == pytest.approx(sum(call.cost for call in calls))

    next_task, next_run = await admit("Synthetic independent task", "Say hello without using any tools.")
    assert next_run.run_id != admitted.run_id
    async with _gateway(monkeypatch), asyncio.timeout(30), aclosing(stream_agent(next_run)) as events:
        [result] = [event.result async for event in events if event.result is not None]
    assert result.success and result.result == "Bonjour !"
    [call] = (await db.scalars(select(LLMCall).where(LLMCall.task_id == next_task.id))).all()
    assert len(requests) == 4 and requests[-1]["model"] == primary.llm_name
    assert call.llm_id == primary.id and call.fallback_from_llm_id is None
    assert call.upstream_request_id == provider_receipts[-1]
    assert (call.agent_run_id, call.task_attempt_id) == (next_run.run_id, next_run.attempt_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["inference", "durable", "sdk", "gateway", "no_fallback", "inactive_fallback"])
async def test_automatic_mail_routes_around_chatgpt_before_transport(failover, monkeypatch, entrypoint):
    from unittest.mock import AsyncMock

    from app.connection import Connection
    from app.llm.facade import proxy_chat_completion
    from app.llm.subscription_policy import MailSubscriptionAccessError
    from app.messenger import Message
    from app.task import Task
    from app.task.activity_snapshot import activity_snapshots
    from app.task.models import TaskAttempt, TaskStatus
    from bridge.openai import codex_oauth
    from tests.protocol_tools import protocol_tool

    db, agent, models, _profiles = failover
    primary = models[0].provider
    primary.catalog_code = "openai-codex"
    primary.user_id = agent.user_id
    primary.subscription_acknowledged = True
    models[0].is_subscription = True
    if entrypoint == "no_fallback":
        agent.fallback_profile_id = None
    elif entrypoint == "inactive_fallback":
        models[1].provider.is_active = False
    service = await protocol_tool(db, "mail")
    connection = Connection(agent_id=agent.id, service_id=service.id, active=True)
    db.add(connection)
    await db.flush()
    message = Message(connection_id=connection.id, service_id=service.id, platform="mail",
                      remote_message_id="1:2", direction="inbound", status="admitted",
                      requester_user_id=agent.user_id, text="Synthetic incoming mail")
    db.add(message)
    await db.flush()
    parent = Task(agent_id=agent.id, label="Synthetic inbox", messenger_message_id=message.id)
    db.add(parent)
    await db.flush()
    lease_token = uuid4()
    task = Task(agent_id=agent.id, label="Synthetic child", parent_id=parent.id, lease_token=lease_token,
                requester_user_id=agent.user_id)
    db.add(task)
    await db.flush()
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH", worker_id="test", lease_token=lease_token))
    if entrypoint == "durable":
        parent.soft_delete()
        message.soft_delete()
    await db.commit()

    access_token = AsyncMock(side_effect=AssertionError("Mail must not request a ChatGPT token"))
    monkeypatch.setattr(codex_oauth, "get_access_token", access_token)
    upstream = []

    async def handler(request):
        upstream.append(request.url.host)
        return httpx.Response(200, content=sse({"content": "Processed"}) + sse({}, "stop") + b'data: [DONE]\n\n',
                              headers={"content-type": "text/event-stream"})

    class ProviderClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    blocked_fallback = entrypoint in {"no_fallback", "inactive_fallback"}
    if blocked_fallback:
        with pytest.raises(MailSubscriptionAccessError, match="fallback profile") as blocked:
            await proxy_chat_completion({"messages": []}, llm_override=models[0], task_id=task.id, agent_id=agent.id)
        with pytest.raises(MailSubscriptionAccessError, match="fallback profile"):
            await build_model_for_llm(models[0], task_id=task.id, agent_id=agent.id)
        task.status = TaskStatus.ERROR
        task.last_error = f"{type(blocked.value).__name__}: {blocked.value}"
        await db.commit()
        assert (await activity_snapshots([task]))[0].mail_subscription_routing == "blocked"
        assert upstream == []
    elif entrypoint in {"inference", "durable"}:
        request = TextInferenceRequest(
            llm_id=models[0].id, task_id=task.id, agent_id=agent.id, prompt="Synthetic request",
            purpose="agent.dispatch", model_field=model_usages.DISPATCHER,
        )
        if entrypoint == "durable":
            assert (await inference_execution.run_text(request)).output == "Processed"
        else:
            assert (await run_text_inference(request)).result == "Processed"
    elif entrypoint == "sdk":
        model = await build_model_for_llm(models[0], task_id=task.id, agent_id=agent.id,
                                          purpose="agent.exec", model_field=model_usages.EXECUTOR)
        assert (await PydanticAgent(model).run("Synthetic request")).output == "Processed"
    else:
        response = await proxy_chat_completion(
            {"messages": [{"role": "user", "content": "Synthetic request"}], "stream": True},
            llm_override=models[0], task_id=task.id, agent_id=agent.id, purpose="agent.exec",
        )
        assert b"Processed" in b"".join([chunk async for chunk in response.body_iterator])
    if not blocked_fallback:
        assert upstream == ["secondary.test"]
        assert (await activity_snapshots([task]))[0].mail_subscription_routing == "fallback"
    access_token.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["inference", "sdk", "gateway", "ineligible_secondary"])
async def test_default_fallback_routes_around_subscription_refusal(failover, monkeypatch, entrypoint):
    from unittest.mock import AsyncMock

    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.llm import subscription_policy
    from app.llm.facade import proxy_chat_completion
    from app.messenger import Room
    from app.services import ServiceModel
    from bridge.openai import codex_oauth

    db, agent, models, profiles = failover
    primary = models[0].provider
    primary.catalog_code = subscription_policy.CHATGPT_CATALOG_CODE
    primary.user_id = agent.user_id
    primary.subscription_acknowledged = True
    models[0].is_subscription = True
    models[1].is_subscription = entrypoint == "ineligible_secondary"
    agent.fallback_profile_id = None
    requester = UserModel(email=f"requester-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    service = ServiceModel(
        code="synthetic-fallback-chat", label="Synthetic fallback chat", description="", connection_schema={},
    )
    db.add_all([requester, service])
    await db.flush()
    connection = Connection(agent_id=agent.id, service_id=service.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(connection_id=connection.id, external_id="test-chat", label="Synthetic chat", kind="direct",
                conversation_type="text")
    db.add(room)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, requester_user_id=requester.id)
    db.add(round_)
    assert await profile_service.set_default_fallback_profile(profiles[1].id)

    monkeypatch.setattr(subscription_policy, "_chatgpt_acknowledged", True)
    access_token = AsyncMock(side_effect=AssertionError("The requester cannot use the subscription"))
    monkeypatch.setattr(codex_oauth, "get_access_token", access_token)
    upstream = []

    async def handler(request):
        upstream.append(request.url.host)
        return httpx.Response(200, content=sse({"content": "Recovered"}) + sse({}, "stop") + b"data: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    class ProviderClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    if entrypoint in {"inference", "ineligible_secondary"}:
        request = TextInferenceRequest(
            llm_id=models[0].id, agent_id=agent.id, prompt="Synthetic request",
            conversation_round_id=round_.id, purpose="conversation.text", model_field=model_usages.CONVERSATION,
        )
        if entrypoint == "ineligible_secondary":
            with pytest.raises(subscription_policy.SubscriptionAccessError):
                await run_text_inference(request)
        else:
            assert (await run_text_inference(request)).result == "Recovered"
    elif entrypoint == "sdk":
        model = await build_model_for_llm(
            models[0], agent_id=agent.id, conversation_round_id=round_.id, purpose="conversation.text",
        )
        assert (await PydanticAgent(model).run("Synthetic request")).output == "Recovered"
    else:
        response = await proxy_chat_completion(
            {"messages": [{"role": "user", "content": "Synthetic request"}], "stream": True},
            llm_override=models[0], agent_id=agent.id, task_id=None,
            conversation_round_id=round_.id, purpose="conversation.text",
        )
        assert b"Recovered" in b"".join([chunk async for chunk in response.body_iterator])
    assert upstream == ([] if entrypoint == "ineligible_secondary" else ["secondary.test"])
    access_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_fallback_is_inherited_and_explicit_agent_profile_takes_precedence(failover):
    db, agent, models, profiles = failover
    primary, shared = profiles
    forced = await profile_service.create_profile("Explicit fallback")
    await profile_service.use_profile(primary.id)
    agent.fallback_profile_id = forced.id
    inherited = Agent(
        user_id=agent.user_id, title_id=agent.title_id, code=f"fallback-{uuid4().hex}",
        first_name="Synthetic inherited", last_name="",
    )
    db.add(inherited)
    await db.commit()
    assert await profile_service.set_default_fallback_profile(shared.id)

    async def resolve(agent_id: int, *, model_id: int = models[0].id) -> tuple[int, object, str | None] | None:
        return await llm_service.get_agent_fallback_model(
            agent_id, model_id, model_field=model_usages.EXECUTOR, purpose="agent.exec",
        )

    assert await resolve(inherited.id) == (shared.id, models[1], None)
    assert await resolve(agent.id) is None
    await profile_service.update_profile(forced.id, values={model_usages.EXECUTOR: str(models[1].id)})
    assert await resolve(agent.id) == (forced.id, models[1], None)
    assert await resolve(inherited.id, model_id=models[1].id) is None
    assert await profile_service.set_default_fallback_profile(primary.id)
    assert await resolve(inherited.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http503", "overload", "partial", "partial_tool", "disconnect"])
@pytest.mark.parametrize("secondary_native", [False, True])
async def test_provider_failover_keeps_tool_receipt_and_only_successful_response_in_history(
    failover, monkeypatch, failure, secondary_native, responses_sse,
):
    db, agent, models, profiles = failover
    if secondary_native:
        models[1].provider.catalog_code = "openai"
        await db.commit()
    requests = []
    effects = []

    class Stream(httpx.AsyncByteStream):
        def __init__(self, provider, after_tool):
            self.provider, self.after_tool = provider, after_tool

        async def __aiter__(self):
            if not self.after_tool:
                yield sse({"tool_calls": [{"index": 0, "id": "synthetic-effect", "type": "function",
                           "function": {"name": "record_effect", "arguments": '{}'}}]})
                yield sse({}, "tool_calls")
            elif self.provider == "primary":
                if failure == "partial":
                    yield sse({"content": "Abandoned partial answer"})
                if failure == "partial_tool":
                    yield sse({"tool_calls": [{"index": 0, "id": "abandoned-effect", "type": "function",
                               "function": {"name": "record_effect", "arguments": '{}'}}]})
                if failure == "disconnect":
                    raise httpx.ReadError("synthetic connection reset")
                yield b'data: {"error":{"message":"Our servers are currently overloaded. Please try again later.","type":"overloaded_error"}}\n\n'
            else:
                yield sse({"content": "Secondary result"})
                yield sse({}, "stop")
            yield b'data: [DONE]\n\n'

    async def handler(request):
        body = json.loads(request.content)
        provider = request.url.host.split('.')[0]
        after_tool = (any(m.get("role") == "tool" for m in body["messages"])
                      if "messages" in body else
                      any(m.get("type") == "function_call_output" for m in body["input"]))
        requests.append((provider, after_tool))
        if provider == "primary" and after_tool and failure == "http503":
            return httpx.Response(503, json={"error": {"message": "synthetic unavailable"}})
        if request.url.path.endswith("/responses"):
            terminal = {"id": "resp-synthetic", "object": "response", "created_at": 1,
                        "model": "secondary", "status": "completed", "output": [{
                            "id": "msg-synthetic", "type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "Secondary result", "annotations": []}],
                        }]}
            return httpx.Response(200, content=responses_sse(terminal), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, stream=Stream(provider, after_tool), headers={"content-type": "text/event-stream"})

    original = httpx.AsyncClient
    class ProviderClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)

    model = await build_model_for_llm(models[0], agent_id=agent.id, purpose="agent.exec")
    sdk = PydanticAgent(model)
    @sdk.tool_plain
    async def record_effect() -> str:
        effects.append("done")
        return "Receipt: done"

    async with sdk.run_stream_events("Execute once, then report the receipt") as stream:
        async for _ in stream:
            pass
    # The same model keeps the secondary for subsequent requests in this run.
    result = await sdk.run("Report the receipt", message_history=stream.result.all_messages())
    assert result.output == "Secondary result"
    assert effects == ["done"]
    assert requests == [("primary", False), ("primary", True), ("secondary", True), ("secondary", True)]
    assert "Abandoned partial answer" not in str(result.all_messages())
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id).order_by(LLMCall.created_at)))
    assert [c.status for c in calls] == ["completed", "error", "completed", "completed"]
    assert all(c.fallback_profile_id == profiles[1].id for c in calls)
    assert calls[2].fallback_from_llm_id == models[0].id and calls[2].fallback_reason
    inferences = list(await db.scalars(select(LLMInference)))
    assert any(i.request.get("profile_fallback", {}).get("from_llm_id") == models[0].id for i in inferences)


@pytest.mark.asyncio
async def test_agent_secondary_profile_is_saved_cleared_and_validated(failover):
    db, agent, _, profiles = failover
    updated = await agent_service.update(agent.id, AgentUpdate(fallback_profile_id=None))
    assert updated.fallback_profile_id is None
    updated = await agent_service.update(agent.id, AgentUpdate(fallback_profile_id=profiles[1].id))
    assert updated.fallback_profile.label == "secondary"
    with pytest.raises(ValueError):
        await agent_service.update(agent.id, AgentUpdate(fallback_profile_id=-1))
    await db.rollback()


@pytest.mark.parametrize("error,allowed", [
    (ModelHTTPError(503, "synthetic", {}), True),
    (ModelHTTPError(401, "synthetic", {}), True),
    (ModelHTTPError(400, "synthetic", {}), False),
    (PermissionError("local authorization denied"), False),
    (RuntimeError("Inference physical call budget exhausted."), False),
])
def test_provider_failover_does_not_bypass_local_guards(error, allowed):
    assert provider_failure_allows_fallback(error) is allowed


@pytest.mark.asyncio
async def test_inference_admission_owns_secondary_selection(failover):
    db, agent, models, profiles = failover
    agent.fallback_profile_id = None
    await db.commit()
    request = TextInferenceRequest(
        llm_id=models[0].id, agent_id=agent.id, prompt="Synthetic request", purpose="synthetic.text",
        profile_fallback=ProfileFallbackRoute(profile_id=profiles[1].id, from_llm_id=models[0].id),
        profile_fallback_llm_id=models[1].id, profile_fallback_resolved=True,
    )
    key = await prepare_inference(request)
    stored = (await read_inference(key)).request
    assert stored.profile_fallback is None
    assert stored.profile_fallback_llm_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("secondary_fails", [False, True])
@pytest.mark.parametrize("prepared", [False, True])
async def test_text_inference_records_both_calls_and_does_not_loop(failover, monkeypatch, secondary_fails, prepared):
    db, agent, models, profiles = failover
    requests = []
    async def handler(request):
        provider = request.url.host.split('.')[0]
        requests.append(provider)
        if provider == "primary" or secondary_fails:
            return httpx.Response(503, json={"error": {"message": "synthetic outage"}})
        return httpx.Response(200, content=sse({"content": "Recovered"}) + sse({}, "stop") + b'data: [DONE]\n\n',
                              headers={"content-type": "text/event-stream"})
    original = httpx.AsyncClient
    class ProviderClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    request = TextInferenceRequest(llm_id=models[0].id, agent_id=agent.id, prompt="Recover once",
                                   purpose="synthetic.text", model_field=model_usages.CONVERSATION)
    if prepared:
        agent.fallback_profile_id = None
        assert await profile_service.set_default_fallback_profile(profiles[1].id)
        key = await prepare_inference(request)
        assert await profile_service.set_default_fallback_profile(None)
        profiles[1].text_low_llm_id = None
        await db.commit()
        await control_inference(key, "start", command_id=uuid4())
        async for event in stream_inference(key):
            if event.result is not None:
                result = event.result
        assert result.success is not secondary_fails
        if not secondary_fails:
            assert result.result == "Recovered"
    elif secondary_fails:
        with pytest.raises(ModelHTTPError, match="503"):
            await run_text_inference(request)
    else:
        result = await run_text_inference(request)
        assert result.result == "Recovered"
    assert requests == ["primary", "secondary"]
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id).order_by(LLMCall.created_at)))
    assert [c.llm_id for c in calls] == [m.id for m in models]
    assert calls[0].status == "error"
    assert calls[1].status == ("error" if secondary_fails else "completed")
    assert (await read_inference_result(calls[0].id)).success is False
    assert (await read_inference_result(calls[1].id)).success is not secondary_fails


@pytest.mark.asyncio
async def test_internal_harness_reports_paid_secondary_cost_after_subscription_failure(failover, monkeypatch):
    from app.agent.contracts import AgentRunRequest, AgentSnapshot, ResolvedModel
    from app.harness.executor import run

    db, agent, models, _ = failover
    models[0].is_subscription = True
    models[1].cost_per_input_token = 2
    models[1].cost_per_output_token = 4
    await db.commit()
    requests = []
    async def handler(request):
        provider = request.url.host.split('.')[0]
        requests.append(provider)
        if provider == "primary":
            return httpx.Response(503, json={"error": {"message": "synthetic outage"}})
        final = {"id": "synthetic", "object": "chat.completion.chunk", "created": 1, "model": "secondary",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}
        return httpx.Response(200, content=sse({"content": "Recovered"}) + ('data: ' + json.dumps(final) + '\n\n').encode()
                              + b'data: [DONE]\n\n', headers={"content-type": "text/event-stream"})
    original = httpx.AsyncClient
    class ProviderClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    request = AgentRunRequest(
        run_id=uuid4(), task_id=None, driver_code="internal", effort="standard", objective="Recover once",
        agent=AgentSnapshot(id=agent.id, code=agent.code, first_name=agent.first_name, last_name="", driver_code="internal"),
        model=ResolvedModel(id=models[0].id, code=models[0].code, model_name=models[0].llm_name,
                            label="Synthetic", requested_effort="standard"),
    )
    result = await run(request)
    assert result.success and result.metadata["profile_fallback_used"] is True, result.metadata
    assert requests == ["primary", "secondary"]
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_run_id == request.run_id)))
    assert result.cost > 0
    assert result.cost == pytest.approx(sum(c.cost for c in calls))
    assert result.usage.requests == 2
