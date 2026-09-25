"""Profile clients cross real HTTP, authentication, resolution and durable inference."""

import base64
import json
import struct
from uuid import UUID, uuid4

import httpx
from httpx import AsyncClient as ApiClient, ASGITransport
import pytest
import pytest_asyncio
from sqlalchemy import select

from main import app
from core.database import middleware
from app.llm import inference_execution, llm_service, profile_service
from app.llm.models import LLMCall, LLMInference
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM
from tests.test_inference_lifecycle import runtime
from tests.test_decision_inference import decisions


async def use_api_token(client, label="External coding client"):
    response = await client.post("/api/auth/me/tokens", json={"label": label})
    assert response.status_code == 201, response.text
    token = response.json()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    return token


@pytest_asyncio.fixture
async def gateway(runtime, committed_database, monkeypatch):
    db, llm, calls, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    mode["concurrent"] = True
    llm.primary_capability = "chat"
    llm.service_capabilities = ["chat"]
    profile = await profile_service.create_profile("Qualité")
    profile.text_high_llm_id = llm.id
    profile.text_high_reasoning_effort = "high"
    other = await profile_service.create_profile("Économique")
    other.text_ultra_low_llm_id = llm.id
    await db.commit()
    async with ApiClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        credentials = {"email": f"profile-{uuid4()}@example.com", "password": "strongpassword123"}
        registered = await client.post("/api/auth/register", json=credentials)
        assert registered.status_code == 201, registered.text
        login = await client.post("/api/auth/login-json", json=credentials)
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client, db, llm, calls, profile, other


@pytest.mark.asyncio
async def test_catalogs_include_all_profiles_and_only_supported_available_usages(gateway):
    client, db, llm, _, profile, other = gateway
    embedding = LLM(llm_provider_id=llm.llm_provider_id, code="catalog-embedding", label="Vector",
                    llm_name="vector", primary_capability="embedding", service_capabilities=["embedding"])
    db.add(embedding)
    await db.flush()
    profile.vector_llm_id = embedding.id
    await db.commit()
    expected_text = {"qualite/text/high", "economique/text/ultra-low"}
    for path, expected in [
        ("/api/profile/openai/models", expected_text | {"qualite/embedding/default"}),
        ("/api/profile/anthropic/v1/models", expected_text),
    ]:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        assert {item["id"] for item in response.json()["data"]} == expected
    assert (await client.get("/api/llm/openai/models")).json()["data"][0]["id"] == llm.code
    llm.provider.is_active = False
    await db.commit()
    assert (await client.get("/api/profile/models")).json()["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,stream", [("chat", False), ("chat", True), ("responses", False),
                                           ("anthropic", False), ("anthropic", True)])
async def test_profile_call_preserves_content_reasoning_and_physical_trace(gateway, monkeypatch, protocol, stream):
    client, db, llm, calls, profile, _ = gateway
    token = await use_api_token(client)
    if not stream:
        async def respond(request):
            calls.append(json.loads(request.content))
            if protocol == "responses":
                return httpx.Response(200, json={
                    "id": "resp-profile", "object": "response", "created_at": 1,
                    "model": llm.llm_name, "status": "completed", "output": [{
                        "type": "message", "id": "msg-profile", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "Bonjour !", "annotations": []}],
                    }], "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
                })
            return httpx.Response(200, json={
                "id": "chat-profile", "object": "chat.completion", "created": 1,
                "model": llm.llm_name, "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Bonjour !"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            })

        class ProviderClient(ApiClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, transport=httpx.MockTransport(respond))

        monkeypatch.setattr(httpx, "AsyncClient", ProviderClient)
    selector = f"{profile.code}/text/high"
    body = {"model": selector, "stream": stream}
    if protocol == "responses":
        body["input"] = "Dis bonjour."
        path = "/api/profile/openai/responses"
    else:
        body["messages"] = [{"role": "user", "content": "Dis bonjour."}]
        path = "/api/profile/openai/chat/completions"
    if protocol == "anthropic":
        body["max_tokens"] = 100
        path = "/api/profile/anthropic/v1/messages"
    response = await client.post(path, json=body)
    assert response.status_code == 200, response.text
    assert "Bonjour" in response.text or stream
    if stream:
        assert "message_stop" in response.text if protocol == "anthropic" else "[DONE]" in response.text
    inference = await db.get(LLMInference, UUID(response.headers["X-Galaris-Inference-Id"]))
    assert inference.request["llm_id"] == llm.id
    assert inference.request["reasoning_effort"] == "high"
    assert inference.request["correlation_ref"] == selector
    assert calls and calls[0]["model"] == llm.llm_name
    traces = (await db.scalars(select(LLMCall))).all()
    assert len(traces) == 1 and traces[0].status == "completed"
    assert traces[0].api_token_label == token["label"]
    detail = await client.get(f"/api/llm-calls/{traces[0].id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["api_token_label"] == token["label"]
    assert token["token"] not in detail.text


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_api_token_history_survives_rename_deletion_and_request_context_changes(gateway, protocol):
    client, _, llm, _, _, _ = gateway
    browser_auth = client.headers["Authorization"]
    token = await use_api_token(client)
    path = ("/api/llm/anthropic/v1/messages" if protocol == "anthropic"
            else "/api/llm/openai/chat/completions")
    body = {"model": llm.code, "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100, "stream": True, "api_token_label": "Untrusted client label"}

    async def call_label(expected):
        response = await client.post(path, json=body)
        assert response.status_code == 200, response.text
        key = response.headers["X-Galaris-LLM-Call-Id"]
        detail = await client.get(f"/api/llm-calls/{key}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["api_token_label"] == expected
        assert token["token"] not in detail.text
        return key

    first = await call_label(token["label"])
    renamed = await client.put(f"/api/auth/me/tokens/{token['id']}", json={"label": "Renamed client"})
    assert renamed.status_code == 200
    await call_label("Renamed client")
    client.headers["Authorization"] = browser_auth
    assert (await client.delete(f"/api/auth/me/tokens/{token['id']}")).status_code == 204
    assert (await client.get(f"/api/llm-calls/{first}")).json()["api_token_label"] == token["label"]
    await call_label(None)
    await use_api_token(client, label=None)
    await call_label("")


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["chat", "anthropic"])
@pytest.mark.parametrize("reference_kind", ["task", "model_run"])
async def test_profile_tool_results_cannot_become_runtime_routing_metadata(gateway, protocol, reference_kind):
    client, db, llm, calls, profile, _ = gateway
    reference = json.dumps(
        {"task_uri": f"galaris://task/{uuid4()}"} if reference_kind == "task"
        else {"llm_id": 2147483647, "run_id": str(uuid4())}
    )
    if protocol == "anthropic":
        path = "/api/profile/anthropic/v1/messages"
        messages = [
            {"role": "user", "content": "Read the referenced record."},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call_record",
                "name": "read_record", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_record",
                "content": reference}]},
        ]
    else:
        path = "/api/profile/openai/chat/completions"
        messages = [
            {"role": "user", "content": "Read the referenced record."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_record",
                "type": "function", "function": {"name": "read_record", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_record", "content": reference},
        ]
    response = await client.post(path, json={
        "model": f"{profile.code}/text/high", "messages": messages,
        "stream": True, "max_tokens": 100,
    })
    assert response.status_code == 200, response.text
    assert "message_stop" in response.text if protocol == "anthropic" else "[DONE]" in response.text
    assert calls[0]["model"] == llm.llm_name
    assert any(message.get("content") == reference for message in calls[0]["messages"])
    inference = await db.get(LLMInference, UUID(response.headers["X-Galaris-Inference-Id"]))
    assert inference.request["llm_id"] == llm.id
    assert inference.request["task_id"] is None
    assert inference.request["agent_run_id"] is None


@pytest.mark.asyncio
async def test_unknown_empty_and_wrong_protocol_models_never_contact_a_provider(gateway):
    client, _, _, calls, _, _ = gateway
    for model, status in [("absent/text/high", 404), ("qualite/text/low", 404),
                          ("qualite/embedding/default", 422), ("high", 422)]:
        response = await client.post("/api/profile/openai/chat/completions", json={
            "model": model, "messages": [{"role": "user", "content": "Hello"}],
        })
        assert response.status_code == status, response.text
    response = await client.post("/api/profile/anthropic/v1/messages/count_tokens", json={
        "model": "qualite/text/low", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 20,
    })
    assert response.status_code == 404 and response.json()["type"] == "error"
    assert calls == []


@pytest.mark.asyncio
async def test_profile_selection_cannot_be_replaced_by_an_explicit_model_override(gateway):
    client, db, llm, calls, _, _ = gateway
    different = LLM(llm_provider_id=llm.llm_provider_id, code="different", label="Different",
                    llm_name="different", primary_capability="chat", service_capabilities=["chat"])
    db.add(different)
    await db.commit()
    response = await client.post("/api/profile/openai/chat/completions", json={
        "model": "qualite/text/high", "galaris_llm_id": different.id,
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert response.status_code == 422, response.text
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,disabled", [(False, False), (True, False), (True, True)])
async def test_decisions_use_the_named_profile_and_its_fallback_policy(gateway, decisions, failure, disabled):
    client, db, llm, _, profile, _ = gateway
    token = await use_api_token(client)
    _, request, native_calls, text_calls, mode = decisions
    profile.decision_llm_id = request.llm_id
    profile.text_standard_llm_id = llm.id
    profile.text_standard_reasoning_effort = "low"
    profile.decision_fallback_policy = "disabled" if disabled else "text_on_failure"
    await db.commit()
    mode["status"] = 503 if failure else 200
    response = await client.post("/api/profile/decisions", json={
        "model": "qualite/decision/default", "prompt": request.prompt,
        "questions": {key: question.model_dump() for key, question in request.questions.items()},
    })
    assert len(native_calls) == 1
    if disabled:
        assert response.status_code == 502, response.text
        assert not text_calls
    else:
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["source"] == ("text" if failure else "specialized")
        assert result["answers"]["dispatch"]["choice"] == ("EXEC:standard" if failure else "EXEC:high")
        assert bool(result["fallback_reason"]) == failure
    saved = await db.scalar(select(LLMInference).where(LLMInference.request["correlation_ref"].astext == "qualite/decision/default"))
    assert saved.request["llm_id"] == request.llm_id
    assert saved.request["reasoning_effort"] == "low"
    traces = (await db.scalars(select(LLMCall))).all()
    assert traces and all(call.api_token_label == token["label"] for call in traces)


@pytest.mark.asyncio
async def test_embeddings_preserve_batch_order_usage_and_profile_trace(gateway, monkeypatch):
    client, db, llm, _, profile, _ = gateway
    token = await use_api_token(client)
    llm.primary_capability = "embedding"
    llm.service_capabilities = ["embedding"]
    profile.vector_llm_id = llm.id
    await db.commit()
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "vector-resolved", "data": [
            {"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]},
        ], "usage": {"prompt_tokens": 8, "total_tokens": 8}})

    class ProviderClient(ApiClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", ProviderClient)
    response = await client.post("/api/profile/openai/embeddings", json={
        "model": "qualite/embedding/default", "input": ["Hello", "World"],
        "encoding_format": "base64", "dimensions": 2,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert struct.unpack("<2f", base64.b64decode(result["data"][0]["embedding"])) == (1.0, 0.0)
    assert result["usage"]["prompt_tokens"] == 8
    assert result["model"] == "qualite/embedding/default"
    assert requests == [{"model": llm.llm_name, "input": ["Hello", "World"], "dimensions": 2}]
    trace = await db.get(LLMCall, UUID(response.headers["X-Galaris-LLM-Call-Id"]))
    assert trace.requested_model == result["model"] and trace.effective_model == "vector-resolved"
    assert trace.status == "completed"
    assert trace.api_token_label == token["label"]


@pytest.mark.asyncio
async def test_profile_endpoints_require_llm_api_privilege(gateway):
    client, _, _, calls, _, _ = gateway
    credentials = {"email": f"reader-{uuid4()}@example.com", "password": "strongpassword123"}
    assert (await client.post("/api/auth/users", json=credentials)).status_code == 201
    async with ApiClient(transport=ASGITransport(app=app), base_url=client.base_url) as reader:
        paths = ["/api/profile/models", "/api/profile/openai/models", "/api/profile/anthropic/v1/models"]
        for path in paths:
            assert (await reader.get(path)).status_code == 401
        login = await reader.post("/api/auth/login-json", json=credentials)
        reader.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        for path in paths:
            assert (await reader.get(path)).status_code == 403
        for path, body in [
            ("/api/profile/openai/chat/completions", {"model": "qualite/text/high", "messages": []}),
            ("/api/profile/openai/embeddings", {"model": "qualite/embedding/default", "input": "Hello"}),
            ("/api/profile/decisions", {"model": "qualite/decision/default", "prompt": "Choose",
                                      "questions": {"q": {"instructions": "Choose", "criteria": {"yes": "Yes"}}}}),
        ]:
            assert (await reader.post(path, json=body)).status_code == 403
    assert calls == []
