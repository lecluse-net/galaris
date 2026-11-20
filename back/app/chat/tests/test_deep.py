"""Deep Chat admission and durable replay through the normal Chat endpoints."""

import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.agent import AgentEvent, AIMessage, ExecutionResult
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.conversation import deep
from app.conversation.models import ConversationRoundMessage, DeepSession
from app.messenger import create_internal_room
from app.llm import LLM, deep_inference_scope, llm_call_service
from app.task import Task
from core.database import get_db_session

pytestmark = pytest.mark.asyncio


async def send(context, room, text, request_id=None):
    response = await context["client"].post(
        f"/api/chat/rooms/{room}/messages", headers=context["headers"],
        json={"text": text, "client_message_id": str(request_id or uuid4()), "language": "en"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def room_info(context, room):
    response = await context["client"].get(f"/api/chat/rooms/{room}/deep", headers=context["headers"])
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("inline_command", [False, True], ids=["standalone", "prefixed"])
async def test_deep_toggle_bypasses_rounds_and_replays_from_event_cursor(attachment_context, monkeypatch, inline_command):
    context = attachment_context
    room = context["room_id"]

    async def synthetic_harness(**request):
        assert request["objective"] == "Build the sample"
        assert request["room_id"] == room
        yield AgentEvent.from_message(AIMessage(type="text", content="Synthetic "))
        yield AgentEvent.from_message(AIMessage(type="tool", content="Completed", tool_name="Fixture"))
        yield AgentEvent.from_message(AIMessage(type="text", content="answer."))
        yield AgentEvent.from_result(ExecutionResult(prompt=request["objective"], success=True, result="Synthetic answer."))

    monkeypatch.setattr(deep, "stream_deep_submission", synthetic_harness)
    if not inline_command:
        command_id = uuid4()
        await send(context, room, "@deep", command_id)
        await send(context, room, "@deep", command_id)
        assert (await room_info(context, room))["enabled"]

    first_input = "@Deep\nBuild the sample" if inline_command else "Build the sample"
    request_id = uuid4()
    message_id = await send(context, room, first_input, request_id)
    assert await send(context, room, first_input, request_id) == message_id
    activated = await room_info(context, room)
    assert activated["enabled"]
    [submission] = activated["submissions"]
    assert submission["state"] == "queued"
    assert submission["message_id"] == message_id
    assert not submission["has_activity"]
    async with get_db_session() as db:
        assert await db.scalar(select(func.count(ConversationRoundMessage.message_id))) == 0
        assert await db.scalar(select(func.count(Task.id)).where(Task.agent_id == context["agent_id"])) == 0

    claim = await deep._claim()
    assert str(claim[0]) == submission["id"]
    await deep._run(*claim)
    [finished] = (await room_info(context, room))["submissions"]
    assert finished["state"] == "completed"
    assert finished["response_message_id"]
    assert finished["has_activity"]

    response = await context["client"].get(
        f"/api/chat/rooms/{room}/deep/{submission['id']}/events", headers=context["headers"],
        params={"after": 1},
    )
    assert response.status_code == 200, response.text
    assert [(item["sequence"], item["kind"]) for item in response.json()] == [(2, "activity"), (3, "text")]

    if inline_command:
        second_id = await send(context, room, "@deep Continue the sample")
        continued = await room_info(context, room)
        assert continued["enabled"]
        _, second = continued["submissions"]
        assert second["message_id"] == second_id
        assert second["session_id"] == submission["session_id"]

    await send(context, room, "@deep")
    assert not (await room_info(context, room))["enabled"]
    await send(context, room, "Use the standard conversation and explain @deep")
    assert len((await room_info(context, room))["submissions"]) == (2 if inline_command else 1)
    async with get_db_session() as db:
        assert await db.scalar(select(func.count(ConversationRoundMessage.message_id))) == 1


async def test_five_conversations_claim_independent_sessions_and_deny_cross_room_replay(attachment_context):
    context = attachment_context
    rooms = [context["room_id"]]
    async with get_db_session() as db:
        for _ in range(4):
            room = await create_internal_room(actor_user_id=context["user_id"], agent_id=context["agent_id"])
            assert room
            rooms.append(room.id)

    for room in rooms:
        await send(context, room, "@deep")
        await send(context, room, "Synthetic independent work")
    await send(context, rooms[0], "Synthetic next input")
    claims = [await deep._claim() for _ in range(5)]
    assert {room for _, room in claims} == set(rooms)
    assert await deep._claim() is None
    async with get_db_session() as db:
        sessions = (await db.scalars(select(DeepSession).where(DeepSession.room_id.in_(rooms)))).all()
        assert len(sessions) == 5
        assert {row.agent_id for row in sessions} == {context["agent_id"]}

    wrong_room = next(room for room in rooms if room != claims[0][1])
    response = await context["client"].get(
        f"/api/chat/rooms/{wrong_room}/deep/{claims[0][0]}/events", headers=context["headers"],
    )
    assert response.status_code == 404


@pytest.mark.parametrize(("origin", "code", "status"), [
    ("exception", "http", 422), ("result", "quota", None),
    ("historic", "skills_task_required", None), ("unrecorded", "unrecorded", None),
])
async def test_deep_projects_safe_failure_details(attachment_context, monkeypatch, origin, code, status):
    from app.agent.contracts import HarnessFailure
    from app.incident import service as incidents
    from core import failure_journal

    context = attachment_context
    room = context["room_id"]
    private_detail = "synthetic-private-exception-text"

    async def rejected_harness(**_request):
        if origin == "exception":
            request = httpx.Request("POST", f"https://harness.test/{private_detail}")
            response = httpx.Response(422, request=request)
            response.raise_for_status()
        yield AgentEvent.from_result(ExecutionResult(prompt="Sample", success=False, result=private_detail,
            failure=HarnessFailure(code="quota", message=private_detail)))

    await send(context, room, "@deep Synthetic request")
    submission_id, _ = await deep._claim()
    if origin in {"historic", "unrecorded"}:
        await deep._persist(submission_id, room, [], state="failed")
        if origin == "historic":
            monkeypatch.setattr(failure_journal, "_read_run_failures", incidents.read_taskless_run_failures)
            async with get_db_session() as db:
                await incidents.record_failure(db, failure_journal.FailureEvent(
                    idempotency_key=f"agent-run:{submission_id}:terminal", kind="llm", phase="agent_run",
                    run_uuid=submission_id, agent_id=context["agent_id"], error_type="HarnessConflictError",
                    error_message=f"HarnessConflictError: Skill synchronization requires an admitted Task. {private_detail}",
                ))
    else:
        monkeypatch.setattr(deep, "stream_deep_submission", rejected_harness)
        await deep._run(submission_id, room)

    [failed] = (await room_info(context, room))["submissions"]
    assert failed["state"] == "failed" and failed["response_message_id"] is None
    assert not failed["has_activity"]
    assert failed["failure"] == {"code": code, "http_status": status}
    endpoint = f"/api/chat/rooms/{room}/deep/{submission_id}/events"
    replay = await context["client"].get(endpoint, headers=context["headers"])
    assert replay.status_code == 200
    assert replay.json() == ([{"sequence": 1, "kind": "failure", "payload": failed["failure"]}]
                             if origin in {"exception", "result"} else [])
    history = await context["client"].get(f"/api/chat/rooms/{room}/messages", headers=context["headers"])
    assert history.status_code == 200 and private_detail not in history.text


async def test_managed_deep_stream_survives_skill_projection_and_resumes(attachment_context, monkeypatch):
    from app.agent import get_agent_record
    from app.harnesses.driver import OpenAIMessagesDriver
    from app.harnesses.models import AgentHarness
    from app.harnesses.openai_client import OpenAIHarnessClient
    from app.harnesses.registry import get_provider
    from app.mcp import mcp_token_service
    from app.services import authorization

    context = attachment_context
    agent_id = context["agent_id"]
    room = context["room_id"]
    async with get_db_session() as db:
        agent = await get_agent_record(agent_id)
        agent.agent_driver = "openai_messages"
        agent.personality = "<p>Synthetic personality</p>"
        agent.job_description = "<p>Synthetic role</p>"
        db.add(AgentHarness(agent_id=agent_id, provider_code="deepseek_harness", lifecycle_status="ready",
            runtime_model="synthetic-model", provider_metadata={"galaris_extensions": True, "skill_revision": "stale"}))
        await mcp_token_service.ensure_system_token(agent_id)

    operations = []
    native_ref = str(uuid4())

    async def project(_agent, action):
        operations.append(action)
        return "synchronized"

    async def harness(request):
        if request.method == "GET":
            assert request.url.path.endswith("/galaris/capabilities")
            return httpx.Response(200, json={"authorization_protocol": "galaris.runtime-authorization/v1",
                "resumable_runs": True, "deep_sessions": True})
        assert request.url.path.endswith("/chat/completions")
        assert "X-Galaris-Deep-Control" in request.headers and "X-Galaris-Deep-Context" in request.headers
        assert "X-Galaris-Task-Id" not in request.headers
        expected_text = "Continue the sample" if request.headers.get("X-Galaris-Deep-Native-Session") else "Start the sample"
        assert json.loads(request.content)["messages"] == [
            {"role": "system", "content": "<p>Synthetic personality</p>\n\n<p>Synthetic role</p>"},
            {"role": "user", "content": expected_text},
        ]
        session_id = UUID(request.headers["X-Galaris-Deep-Session"])
        async with get_db_session():
            assert await deep.authorize_deep_runtime(session_id, agent_id) == context["user_id"]
        operations.append(request.headers.get("X-Galaris-Deep-Native-Session"))
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=(
            f'event: galaris.deep-session/v1\ndata: {json.dumps({"session": native_ref})}\n\n'
            'data: {"choices":[{"delta":{"content":"Synthetic response"}}]}\n\n'
            'data: [DONE]\n\n'))

    async def client(_driver, _request):
        return OpenAIHarnessClient(base_url="http://harness.test/v1", token="synthetic", transport=httpx.MockTransport(harness))

    monkeypatch.setattr(get_provider("deepseek_harness"), "run_action", project)
    monkeypatch.setattr(OpenAIMessagesDriver, "_client", client)
    monkeypatch.setitem(authorization._context_guards, "deep", deep._authorization_scope)

    await send(context, room, "@deep Start the sample")
    [queued] = (await room_info(context, room))["submissions"]
    async with get_db_session() as db:
        session = await db.get(DeepSession, UUID(queued["session_id"]))
        session.target = {**session.target, "metadata": {**session.target["metadata"], "skill_revision": "stale"}}
    await deep._run(*(await deep._claim()))
    [first] = (await room_info(context, room))["submissions"]
    assert first["state"] == "completed" and first["response_message_id"]
    timeline = await context["client"].get(f"/api/chat/rooms/{room}/messages", headers=context["headers"])
    assert timeline.status_code == 200
    reply = next(message for message in timeline.json()["items"] if message["id"] == first["response_message_id"])
    assert reply["deep_submission_id"] == first["id"]
    events = await context["client"].get(f"/api/chat/rooms/{room}/deep/{first['id']}/events", headers=context["headers"])
    assert events.status_code == 200
    assert [(event["kind"], event["payload"]) for event in events.json()] == [("text", {"content": "Synthetic response"})]

    await send(context, room, "Continue the sample")
    await deep._run(*(await deep._claim()))
    _, second = (await room_info(context, room))["submissions"]
    assert second["state"] == "completed" and second["session_id"] == first["session_id"]
    assert operations == ["refresh", None, native_ref]


async def test_deep_call_filters_exact_origin_without_round_or_task(attachment_context):
    context = attachment_context
    room = context["room_id"]
    await send(context, room, "@deep")
    await send(context, room, "Synthetic inference")
    [submission] = (await room_info(context, room))["submissions"]
    session_id = UUID(submission["session_id"])

    async with get_db_session() as db:
        llm_id = await db.scalar(select(LLM.id).limit(1))
        assert llm_id is not None
        with deep_inference_scope(session_id):
            call = await llm_call_service.create_running_call(
                purpose=None, task_id=None, agent_run_id=None, agent_id=context["agent_id"], llm_id=llm_id,
                provider_name="Synthetic", provider_code="synthetic", requested_model="sample",
                effective_model="sample", stream=True, request_body={},
            )
        assert call.deep_session_id == session_id
        assert call.task_id is None and call.conversation_round_id is None
        [projected] = await llm_call_service.serialize_calls(await llm_call_service.list_calls(deep_room_id=room))
        assert projected.deep_room_id == room
        assert await llm_call_service.list_calls(deep_room_id=uuid4()) == []


async def test_gateway_validates_deep_scope_and_ignores_other_lineage(attachment_context, monkeypatch):
    from fastapi.responses import JSONResponse
    from app.llm import call_router
    from app.llm.correlation import current_deep_session
    from core.util import get_encryption_service

    context = attachment_context
    room = context["room_id"]
    await send(context, room, "@deep")
    await send(context, room, "Synthetic scope")
    [submission] = (await room_info(context, room))["submissions"]
    session_id = UUID(submission["session_id"])
    credential = get_encryption_service().encrypt(f"galaris:deep:v1:{session_id}")

    async def runtime_agent(request):
        return int(request.headers["X-Synthetic-Agent"])

    async def observed(_body, **options):
        assert current_deep_session() == session_id
        assert options["task_id"] is None
        assert "conversation_round_id" not in options
        return JSONResponse({"status": "observed"})

    monkeypatch.setattr(call_router, "_llm_api_auth", runtime_agent)
    monkeypatch.setattr(call_router, "proxy_responses", observed)
    endpoint = "/api/llm/openai/responses"
    headers = {"X-Synthetic-Agent": str(context["agent_id"]), "X-Galaris-Deep-Context": credential}
    response = await context["client"].post(endpoint, headers=headers, json={"galaris_task_id": str(uuid4())})
    assert response.status_code == 200
    assert current_deep_session() is None
    response = await context["client"].post(endpoint, headers={**headers, "X-Synthetic-Agent": "999999"}, json={})
    assert response.status_code == 403
    response = await context["client"].post(endpoint, headers={**headers, "X-Galaris-Deep-Context": "tampered"}, json={})
    assert response.status_code == 403
