"""Synthetic provider outages through the real SDK, journal, and tool loop."""

import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.agent.schemas import AgentUpdate
from app.agent import agent_service
from app.llm import LLM, LLMProvider, LlmProfile, llm_call_service, proxy_service
from app.llm.models import LLMCall, LLMInference
from app.llm.pydantic_ai_utils import build_model_for_llm
from app.llm import inference_execution
from app.llm.contracts import TextInferenceRequest
from app.llm.facade import run_text_inference, prepare_inference, control_inference, stream_inference, read_inference_result
from app.llm import model_usages
from app.llm.profile_fallback import ProfileFallbackRoute, provider_failure_allows_fallback
from app.llm.facade import read_inference
from pydantic_ai.exceptions import ModelHTTPError
from core.database import get_db_session
from core.user import UserModel


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
        key = await prepare_inference(request)
        agent.fallback_profile_id = None
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
    assert result.success and result.metadata["profile_fallback_used"] is True
    assert requests == ["primary", "secondary"]
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_run_id == request.run_id)))
    assert result.cost > 0
    assert result.cost == pytest.approx(sum(c.cost for c in calls))
    assert result.usage.requests == 2
