import asyncio
import json
from uuid import UUID
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from httpx import AsyncClient
from fastapi import FastAPI
import pytest
from pydantic_ai import Agent
from sqlalchemy import select

from app.llm import protocol_inference
from app.llm.facade import read_inference, stream_inference, control_inference, llm_call_accounting
from app.llm.models import LLMInference, LLMCall
from app.llm.pydantic_ai_utils import build_model_for_llm
from tests import test_inference_lifecycle as lifecycle

runtime = lifecycle.runtime
state = lifecycle.state


def provider_http(monkeypatch, handler):
    class ProviderClient(AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(protocol_inference.proxy_service.httpx, "AsyncClient", ProviderClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,parameter,retries", [
    (400, "custom_option", 1), (422, "temperature", 1),
    (400, "messages", 0), (400, "max_tokens", 0), (429, "temperature", 0),
])
async def test_optional_parameter_rejection_is_best_effort_without_losing_requirements(
    runtime, monkeypatch, status, parameter, retries,
):
    _, llm, _, _ = runtime
    llm.provider.catalog_code = "openrouter"
    await runtime[0].commit()
    sent = []
    def upstream(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            return httpx.Response(status, json={"error": {
                "code": "unsupported_parameter", "param": parameter, "message": "Unsupported option",
            }}, headers={"Retry-After": "12"})
        return httpx.Response(200, json={"id": "chat-test", "object": "chat.completion",
            "created": 1, "model": "opaque", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "Bonjour !"}, "finish_reason": "stop"}]})
    provider_http(monkeypatch, upstream)
    body = {"model": llm.code, "messages": [{"role": "user", "content": "Bonjour"}],
            "temperature": 0.4, "custom_option": True, "max_tokens": 50}
    response = await protocol_inference.proxy_chat_completion(body, task_id=None)
    assert response.status_code == (200 if retries else status)
    assert len(sent) == retries + 1
    assert sent[-1]["messages"] == body["messages"]
    assert sent[-1]["max_tokens"] == 50
    saved = await read_inference(UUID(response.headers["x-galaris-inference-id"]))
    assert saved.status == ("completed" if retries else "failed")
    if retries:
        assert parameter not in sent[-1]
        assert saved.attempts[-1].result.messages[-1].content == "Bonjour !"
    else:
        assert response.headers["retry-after"] == "12"


@pytest.mark.asyncio
@pytest.mark.parametrize("parameter,retry", [
    ("reasoning.effort", True), ("custom_options.level", True),
    ("reasoning.max_tokens", False), ("reasoning", False), ("text.format", False),
])
async def test_nested_optional_parameter_rejection_preserves_schema_and_reasoning_budget(
    runtime, monkeypatch, parameter, retry,
):
    _, llm, _, _ = runtime
    llm.provider.catalog_code = "openrouter"
    await runtime[0].commit()
    sent = []

    def upstream(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {
                "code": "unsupported_parameter", "param": parameter,
            }})
        return httpx.Response(200, json={"id": "response-nested", "object": "response",
            "created_at": 1, "model": "opaque", "status": "completed", "output": [{
                "id": "answer", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "{}", "annotations": []}],
            }]})

    provider_http(monkeypatch, upstream)
    output_format = {"type": "json_schema", "name": "Answer", "schema": {"type": "object"}}
    response = await protocol_inference.proxy_responses({
        "model": llm.code, "input": "Réponds.", "reasoning": {"effort": "high", "max_tokens": 100},
        "text": {"verbosity": "low", "format": output_format},
        "custom_options": {"level": "high"},
    }, task_id=None)
    assert response.status_code == (200 if retry else 400)
    assert len(sent) == (2 if retry else 1)
    assert sent[-1]["reasoning"]["max_tokens"] == 100
    assert sent[-1]["text"]["format"] == output_format
    if retry:
        root, leaf = parameter.split(".")
        assert leaf not in sent[-1][root]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", ["opaque-deployment", "arbitrary/opaque-deployment"])
@pytest.mark.parametrize("refusal", [None, 400, 404, 422, 401, 429])
async def test_perplexity_protocol_comes_from_provider_response_and_preserves_durable_calls(
    runtime, monkeypatch, responses_sse, model_name, refusal,
):
    from pydantic_ai.exceptions import ModelHTTPError

    db, llm, _, _ = runtime
    llm.provider.catalog_code = "perplexity"
    llm.llm_name = model_name
    await db.commit()
    sent = []

    def upstream(request):
        body = json.loads(request.content)
        sent.append((request.url.path, body))
        assert body["stream"] is True
        assert body["model"] == model_name
        if request.url.path.endswith("/responses"):
            if refusal is not None:
                return httpx.Response(refusal, json={"error": {
                    "message": "Endpoint refused this request", "code": "invalid_request",
                }})
            return httpx.Response(200, content=responses_sse({
                "id": "response-opaque", "object": "response", "created_at": 1,
                "model": model_name, "status": "completed", "output": [{
                    "type": "message", "id": "answer", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Bonjour !", "annotations": []}],
                }], "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            }), headers={"content-type": "text/event-stream"})
        chunk = {"id": "chat-opaque", "object": "chat.completion.chunk", "created": 1,
                 "model": model_name, "choices": [{"index": 0,
                 "delta": {"role": "assistant", "content": "Bonjour !"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}
        return httpx.Response(200, content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    provider_http(monkeypatch, upstream)
    model = await build_model_for_llm(llm, reasoning_effort="high", purpose="test.protocol")
    with llm_call_accounting() as accounting:
        if refusal in {401, 429}:
            with pytest.raises(ModelHTTPError) as error:
                await Agent(model).run("Dis bonjour.")
            assert error.value.status_code == refusal
        else:
            assert (await Agent(model).run("Dis bonjour.")).output == "Bonjour !"
    fallback = refusal in {400, 404, 422}
    assert len(sent) == (2 if fallback else 1)
    assert sent[0][0].endswith("/responses")
    if fallback:
        assert sent[1][0].endswith("/chat/completions")
        assert sent[1][1]["messages"][-1]["content"] == "Dis bonjour."
    keys = list(await db.scalars(select(LLMInference.id).order_by(LLMInference.created_at)))
    snapshots = [await read_inference(key) for key in keys]
    assert len(snapshots) == len(sent)
    assert [item.status for item in snapshots] == (
        ["failed", "completed"] if fallback else ["failed"] if refusal else ["completed"]
    )
    assert sum(item.cost for item in snapshots) == pytest.approx(accounting.cost)


@pytest.mark.asyncio
async def test_tool_loop_records_each_request_and_replay_never_executes_the_tool(runtime):
    db, llm, requests, mode = runtime
    mode.update(structured=True, outputs=['{}', 'Bonjour !', '{}'])
    executions = []
    model = await build_model_for_llm(llm, purpose="lab.mechanism_run")
    agent = Agent(model)

    @agent.tool_plain
    def inspect_workspace() -> str:
        executions.append(True)
        mode["structured"] = False
        return "Workspace ready"

    assert (await agent.run("Inspecte puis réponds.")).output == "Bonjour !"
    assert executions == [True]
    keys = list(await db.scalars(select(LLMInference.id).order_by(LLMInference.created_at)))
    assert len(keys) == 2
    first = await read_inference(keys[0])
    assert any(message.tool_name == "inspect_workspace" for message in first.attempts[-1].result.messages)
    mode["structured"] = True
    replay = await control_inference(keys[0], "replay")
    await state(replay.replay_id, "completed")
    assert executions == [True]
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_http_controls_enforce_scope_and_reconnect_to_durable_events(runtime, monkeypatch):
    from app.llm import call_router
    from app.llm import inference_execution as execution
    from app.llm import inference_store as store
    from tests.test_text_inference import request_for

    _, llm, requests, mode = runtime
    api = FastAPI()
    api.include_router(call_router.llm_api_router)
    key = await execution.transaction(lambda: store.create(request_for(llm)))
    base = f"/llm/openai/inferences/{key}"
    identity = SimpleNamespace(id=None, is_active=True)
    monkeypatch.setattr(call_router.user_service, "get_current_user", AsyncMock(return_value=identity))
    privilege = AsyncMock(return_value=False)
    monkeypatch.setattr(call_router, "check_privilege", privilege)
    scope = AsyncMock(return_value=SimpleNamespace(agent_ids=frozenset()))
    monkeypatch.setattr(call_router, "current_management_scope", scope)
    async with AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.get(base)).status_code == 403
        privilege.return_value = True
        assert (await client.get(base)).status_code == 404
        assert (await client.post(base + "/commands", json={"action": "replay"})).status_code == 404
        scope.return_value = SimpleNamespace(agent_ids=None)
        assert (await client.get(base)).json()["status"] == "queued"
        command = {"action": "pause", "command_id": str(uuid4())}
        receipt = await client.post(base + "/commands", json=command)
        assert receipt.status_code == 200
        assert (await client.post(base + "/commands", json=command)).json() == receipt.json()
        assert (await client.get(base)).json()["status"] == "paused"
        assert requests == []
        mode["outputs"] = ["Bonjour !"]
        assert (await client.post(base + "/commands", json={"action": "resume"})).status_code == 200
        await execution.start()
        saved = await state(key, "completed")
        events = await client.get(base + "/events")
        lines = [json.loads(line.removeprefix("data: ")) for line in events.text.splitlines() if line.startswith("data: ")]
        assert lines[-1]["result"]["messages"][-1]["content"] == "Bonjour !"
        assert sum(item["kind"] == "result" for item in lines) == 1
        last = lines[-1]["sequence"]
        assert (await client.get(base + f"/events?after_sequence={last}")).text == ""
        assert (await client.get(base + f"/events?attempt_id={uuid4()}")).status_code == 404
        assert len(saved.attempts) == 2
        assert (await client.post("/llm/openai/inferences", json={
            **request_for(llm).model_dump(mode="json"), "task_id": str(uuid4()),
        })).status_code == 403


@pytest.mark.asyncio
async def test_public_openai_api_returns_the_same_durable_inference(runtime, monkeypatch):
    from app.llm import call_router

    _, llm, _, _ = runtime
    api = FastAPI()
    api.include_router(call_router.llm_api_router)
    monkeypatch.setattr(call_router, "_llm_api_auth", AsyncMock(return_value=None))
    response_body = {"model": llm.code, "messages": [{"role": "user", "content": "Bonjour"}], "stream": True}
    async with AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post("/llm/openai/chat/completions", json=response_body)
    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    saved = await read_inference(UUID(response.headers["x-galaris-inference-id"]))
    assert saved.request.body == response_body
    assert saved.status == "completed"


@pytest.mark.asyncio
async def test_stream_keeps_two_thoughts_fifteen_tools_and_one_answer_as_eighteen_messages(
    runtime, monkeypatch, responses_sse,
):
    _, llm, _, _ = runtime
    output = [{"type": "reasoning", "id": "thinking-first",
               "summary": [{"type": "summary_text", "text": "Première réflexion."}]}]
    output.extend({"type": "function_call", "id": f"tool-{index}", "call_id": f"call-{index}",
                   "name": "lookup", "arguments": json.dumps({"index": index}), "status": "completed"}
                  for index in range(15))
    output.extend([
        {"type": "reasoning", "id": "thinking-second",
         "summary": [{"type": "summary_text", "text": "Deuxième réflexion."}]},
        {"type": "message", "id": "answer", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "text": "Réponse finale.", "annotations": []}]},
    ])
    terminal = {"id": "response-parts", "object": "response", "created_at": 1,
                "model": "opaque", "status": "completed", "output": output}
    provider_http(monkeypatch, lambda request: httpx.Response(
        200, content=responses_sse(terminal), headers={"content-type": "text/event-stream"},
    ))
    response = await protocol_inference.proxy_responses(
        {"model": llm.code, "stream": True, "input": "Recherche puis réponds."}, task_id=None,
    )
    async for _ in response.body_iterator:
        pass
    key = UUID(response.headers["x-galaris-inference-id"])
    events = [event async for event in stream_inference(key)]
    result = events[-1].result
    assert len(result.messages) == 18
    assert sum(message.tool_name == "lookup" for message in result.messages) == 15
    assert result.messages[0].content == "Première réflexion."
    assert result.messages[-2].content == "Deuxième réflexion."
    assert result.messages[-1].content == "Réponse finale."
    assert len({message.stream_id for message in result.messages}) == 18
    assert len([event for event in events if event.kind == "message"]) > 18
    assert sum(event.kind == "result" for event in events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["chat", "responses"])
@pytest.mark.parametrize("slow_terminal", [False, True])
async def test_sdk_models_use_durable_requests_without_changing_their_outputs(
    runtime, protocol, monkeypatch, slow_terminal,
):
    if slow_terminal:
        from app.llm import text_inference

        persist = text_inference.persist_events

        async def delayed_terminal(call_id, payloads):
            if any(payload["kind"] == "result" for payload in payloads):
                await asyncio.sleep(0.6)
            return await persist(call_id, payloads)

        monkeypatch.setattr(text_inference, "persist_events", delayed_terminal)
    db, llm, requests, _ = runtime
    if protocol == "responses":
        llm.provider.base_url = "https://api.openai.com/v1"
        await db.commit()
    model = await build_model_for_llm(llm, purpose="lab.mechanism_run")
    with llm_call_accounting() as accounting:
        result = await Agent(model, system_prompt="Réponds en français.").run("Dis bonjour.")
    assert result.output == "Bonjour !"
    assert len(requests) == 1
    key = await db.scalar(select(LLMInference.id))
    saved = await read_inference(key)
    assert saved.status == "completed"
    assert saved.request.protocol == protocol
    assert saved.request.sdk_request is True
    assert saved.cost == accounting.cost
    assert requests[0]["stream"] is True
    events = [event async for event in stream_inference(key)]
    assert sum(event.kind == "result" for event in events) == 1
    assert events[-1].result.messages[-1].content == "Bonjour !"


@pytest.mark.asyncio
async def test_raw_protocol_stream_keeps_parameters_and_replays_without_a_harness(runtime):
    db, llm, requests, mode = runtime
    mode.update(outputs=["Bonjour !", "Bonjour !"])
    body = {"model": llm.code, "stream": True,
            "messages": [{"role": "user", "content": "Dis bonjour."}],
            "custom_provider_option": {"value": 12}}
    response = await protocol_inference.proxy_chat_completion(body, task_id=None)
    data = b"".join([chunk async for chunk in response.body_iterator])
    assert b"data: [DONE]" in data
    assert requests[0]["custom_provider_option"] == {"value": 12}
    saved = await read_inference(UUID(response.headers["x-galaris-inference-id"]))
    assert saved.status == "completed"
    replay = await control_inference(saved.id, "replay")
    repeated = await state(replay.replay_id, "completed")
    assert repeated.request == saved.request
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_cancellation_before_headers_does_not_leave_a_running_call(runtime):
    db, llm, _, mode = runtime
    mode["gate"] = asyncio.Event()
    model = await build_model_for_llm(llm, purpose="lab.mechanism_run")
    consumer = asyncio.create_task(Agent(model).run("Dis bonjour."))
    async with asyncio.timeout(10):
        while not (key := await db.scalar(select(LLMInference.id))):
            await asyncio.sleep(0.02)
        stream = stream_inference(key)
        await anext(stream)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await stream.aclose()
    saved = await read_inference(key)
    assert saved.status == "stopped"
    assert saved.attempts[-1].result.messages
    assert (await db.scalar(select(LLMCall))).status != "running"
