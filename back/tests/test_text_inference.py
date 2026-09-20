"""Exercise the real SDK, gateway and PostgreSQL; replace only provider HTTP."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent import AIResult
from app.llm import LLM, LLMProvider, llm_call_service, proxy_service
from app.llm.contracts import TextInferenceRequest
from app.llm.facade import (
    read_inference_events,
    read_inference_result,
    run_text_inference,
)
from app.llm.models import LLMCallEvent


async def configure_provider(db, monkeypatch, responses_sse):
    connection = LLMProvider(
        name=f"pilot-{uuid4()}",
        base_url="https://provider.test/v1",
        provider_type="openai_compatible",
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    llm = LLM(
        llm_provider_id=connection.id,
        provider=connection,
        code=f"pilot-{uuid4()}",
        label="Text pilot",
        llm_name="opaque-deployment",
        cost_per_input_token=2,
        cost_per_output_token=4,
    )
    db.add(llm)
    await db.commit()
    requests = []
    response_mode = {"error": False, "outputs": None, "journal": True}

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            text = (
                response_mode["outputs"][len(requests) - 1]
                if response_mode["outputs"] is not None
                else "Bonjour !"
            )
            deltas = [
                {"role": "assistant", "reasoning_content": "Je réfléchis."},
                {"content": text[:3]},
                {"content": text[3:]},
            ]
            if response_mode.get("structured") and requests[-1].get("tools"):
                name = requests[-1]["tools"][0]["function"]["name"]
                deltas = [deltas[0],
                    {"tool_calls": [{"index": 0, "id": "output-call", "type": "function",
                                     "function": {"name": name, "arguments": ""}}]},
                    {"tool_calls": [{"index": 0, "function": {"arguments": text[:3]}}]},
                    {"tool_calls": [{"index": 0, "function": {"arguments": text[3:]}}]},
                ]
                if response_mode.get("split_tool_name"):
                    deltas[1]["tool_calls"][0]["function"]["name"] = name[:3]
                    deltas.insert(2, {"tool_calls": [{"index": 0, "function": {"name": name[3:]}}]})
            for delta in deltas:
                if response_mode.get("fragment_delay"):
                    await asyncio.sleep(0.11)
                chunk = {
                    "id": "chat-pilot",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "opaque-deployment",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                if "reasoning_content" in delta and response_mode.get("gate") is not None:
                    await response_mode["gate"].wait()
                if "tool_calls" in delta and response_mode.get("tool_gate") is not None:
                    await response_mode["tool_gate"].wait()
                fragment = delta.get("content")
                if "tool_calls" in delta:
                    fragment = delta["tool_calls"][0]["function"].get("arguments")
                if fragment == text[:3] and response_mode.get("partial_gate") is not None:
                    await response_mode["partial_gate"].wait()
                if response_mode["error"]:
                    raise httpx.ReadError("provider stream interrupted")
            yield b'data: {"id":"chat-pilot","object":"chat.completion.chunk","created":1,"model":"opaque-deployment","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}\n\n'
            yield b"data: [DONE]\n\n"

    async def respond(request):
        requests.append(json.loads(request.content))
        # Entry and its native input must be committed before the provider is contacted.
        query = select(func.count()).select_from(LLMCallEvent).where(LLMCallEvent.sequence == 0)
        if response_mode.get("concurrent"):
            from core.database import get_db_session

            async with get_db_session() as reader:
                assert await reader.scalar(query) >= len(requests)
        else:
            assert await db.scalar(query) == (len(requests) if response_mode["journal"] else 0)
        if request.url.path.endswith("/responses"):
            terminal = {
                "id": "resp-pilot",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4.1",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "reason-pilot",
                        "summary": [{"type": "summary_text", "text": "Je réfléchis."}],
                    },
                    {
                        "type": "message",
                        "id": "message-pilot",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "Bonjour !", "annotations": []}
                        ],
                    },
                ],
                "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            }
            if response_mode.get("structured"):
                text = response_mode["outputs"][len(requests) - 1]
                if requests[-1].get("tools"):
                    terminal["output"][1] = {
                        "type": "function_call", "id": "fc-output", "call_id": "output-call",
                        "name": requests[-1]["tools"][0]["name"],
                        "arguments": text, "status": "completed",
                    }
                else:
                    terminal["output"][1]["content"][0]["text"] = text
            return httpx.Response(
                200, content=responses_sse(terminal), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})

    original = httpx.AsyncClient

    class ProviderClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", ProviderClient)
    return llm, requests, response_mode


@pytest_asyncio.fixture
async def provider(db, monkeypatch, responses_sse):
    return await configure_provider(db, monkeypatch, responses_sse)


def request_for(llm):
    return TextInferenceRequest(
        llm_id=llm.id,
        prompt="Dis bonjour.",
        system_prompt="Réponds en français.",
        parameters={"temperature": 0.2, "max_tokens": 64},
        purpose="lab.mechanism_run",
        count_tokens_before_request=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("subscription", [False, True])
@pytest.mark.parametrize("sampling_supported", [False, True])
@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_text_stream_is_durable_and_readback_never_calls_provider(
    db, provider, subscription, sampling_supported, protocol
):
    llm, requests, _ = provider
    llm.is_subscription = subscription
    if sampling_supported:
        llm.llm_name = "gpt-4.1"  # Public SDK profile with sampling support.
    if protocol == "responses":
        llm.provider.base_url = "https://api.openai.com/v1"
    await db.commit()
    observed = []

    async def receive(event):
        persisted = await read_inference_events(event.call_id, after_sequence=event.sequence - 1)
        assert persisted[0] == event
        observed.append(event)

    request = request_for(llm).model_copy(update={"reasoning_effort": "low"})
    result = await run_text_inference(request, on_event=receive)
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    if sampling_supported:
        assert requests[0]["temperature"] == 0.2
    else:
        # The SDK's default opaque-model profile enables reasoning and drops sampling.
        assert "temperature" not in requests[0]
    saved_request = await db.scalar(select(LLMCallEvent).where(LLMCallEvent.sequence == 0))
    assert saved_request.payload["request"]["parameters"]["temperature"] == 0.2
    if protocol == "chat":
        assert requests[0].get("max_tokens", requests[0].get("max_completion_tokens")) == 64
        assert [m["content"] for m in requests[0]["messages"]] == [
            "Réponds en français.",
            "Dis bonjour.",
        ]
    else:
        assert requests[0]["max_output_tokens"] == 64
        assert "Réponds en français." in json.dumps(requests[0], ensure_ascii=False)
        assert "Dis bonjour." in json.dumps(requests[0], ensure_ascii=False)
    assert result.result == "Bonjour !"
    assert [m.content for m in result.messages] == ["Je réfléchis.", "Bonjour !"]
    assert len({m.stream_id for m in result.messages}) == 2
    call_id = UUID(result.metadata["llm_call_ids"][0])
    call = await llm_call_service.get_call(call_id)
    assert call.status == "completed"
    assert call.reasoning_effort == "low"
    assert result.cost == call.cost == (0 if subscription else pytest.approx(0.000036))
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 3
    assert result.usage.requests == 1
    assert [event.kind for event in observed].count("result") == 1
    assert observed[-1].kind == "result"
    terminal = await read_inference_result(call_id)
    assert terminal == observed[-1].result
    reconstructed = AIResult(prompt="")
    for event in await read_inference_events(call_id):
        if event.message is not None:
            reconstructed.add_message(event.message)
    assert [m.content for m in reconstructed.messages] == [m.content for m in terminal.messages]
    db.expire_all()  # Re-read uses storage, no model invocation.
    assert await read_inference_result(call_id) == terminal
    assert len(requests) == 1
    with pytest.raises(LookupError):
        await read_inference_events(call_id, agent_ids=[])


@pytest.mark.asyncio
async def test_journal_survives_caller_rollback_without_committing_its_changes(
    committed_database,
    monkeypatch,
    responses_sse,
):
    from core.database import get_db_session

    monkeypatch.setattr(llm_call_service, "AsyncSessionLocal", committed_database)
    async with get_db_session() as db:
        llm, requests, _ = await configure_provider(db, monkeypatch, responses_sse)
        llm_id, original_label = llm.id, llm.label
        llm.label = "Uncommitted caller change"
        await db.flush()

        result = await run_text_inference(request_for(llm))
        call_id = UUID(result.metadata["llm_call_ids"][0])
        await db.rollback()

        assert await db.scalar(select(LLM.label).where(LLM.id == llm_id)) == original_label
        terminal = await read_inference_result(call_id)
        assert terminal is not None and terminal.result == "Bonjour !"
        assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interrupted_inference_preserves_partial_and_original_failure(db, provider, cancel):
    llm, requests, mode = provider
    mode["error"] = not cancel
    observed = []

    async def receive(event):
        observed.append(event)
        if cancel and event.kind == "message":
            raise asyncio.CancelledError("caller stopped")

    with pytest.raises(asyncio.CancelledError if cancel else Exception):
        await run_text_inference(request_for(llm), on_event=receive)
    assert len(requests) == 1
    call_id = observed[0].call_id
    terminal = await read_inference_result(call_id)
    assert terminal is not None and terminal.success is False
    assert terminal.messages[0].content == "Je réfléchis."
    assert len([e for e in await read_inference_events(call_id) if e.kind == "result"]) == 1
    assert await read_inference_result(call_id) == terminal


@pytest.mark.asyncio
async def test_journal_follows_trace_retention_and_terminal_is_immutable(db, provider, monkeypatch):
    from app.llm.inference_journal import append_events
    from app.llm.retention import prune_traces
    from core.params import runtime_settings

    llm, requests, _ = provider
    result = await run_text_inference(request_for(llm))
    call_id = UUID(result.metadata["llm_call_ids"][0])
    with pytest.raises(ValueError, match="terminal"):
        await append_events(call_id, [{"kind": "message", "message": {}}])
    call = await llm_call_service.get_call(call_id)
    call.completed_at = call.updated_at = datetime.now(timezone.utc) - timedelta(days=40)
    await db.commit()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces() == 1
    await db.commit()
    assert await read_inference_events(call_id) == []
    assert await read_inference_result(call_id) is None
    assert call.cost == result.cost
    assert len(requests) == 1
