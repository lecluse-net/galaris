import base64
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import httpx
from fastapi.responses import StreamingResponse

from app.llm import proxy_service
from app.llm.provider_facade import ProviderConnection
from bridge.openai import codex_oauth
from bridge.openai.codex import CodexBridge
from bridge.openai.codex_oauth import codex_request_headers
from bridge.openai.codex_responses import (
    CodexSSEAdapter,
    chat_completions_to_responses,
    responses_to_chat_completion,
)


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "truncated", "refresh", "objective", "objective_empty_terminal", "text_empty_terminal"])
async def test_native_nonstream_responses_consumes_codex_sse(monkeypatch, outcome, responses_sse):
    import httpx
    from contextlib import asynccontextmanager

    terminal = {
        "id": "resp_objective", "object": "response", "status": "completed",
        "model": "gpt-6-astra", "created_at": 1234,
        "output": [{"type": "message", "id": "msg_objective", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text",
                    "text": '{"label":"Test","objective":"Vérifier le résultat"}', "annotations": []}]}],
        "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
    }
    requests = []
    async def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream") is not True:
            return httpx.Response(400, json={"detail": "Stream must be set to true"})
        for parameter in ("max_output_tokens", "temperature", "top_p"):
            if parameter in body:
                return httpx.Response(400, json={"detail": f"Unsupported parameter: {parameter}"})
        if outcome == "refresh" and len(requests) == 1:
            return httpx.Response(401, json={"error": "expired"})
        if outcome.startswith("objective"):
            terminal["output"] = [{"type": "function_call", "id": "fc_objective",
                "call_id": "call_objective", "name": body["tools"][0]["name"],
                "arguments": '{"label":"Test","objective":"Vérifier le résultat"}',
                "status": "completed"}]
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                content=responses_sse(terminal, empty_terminal=outcome.endswith("empty_terminal")))
        event = {"type": "response.completed", "response": terminal}
        if outcome == "failed":
            event = {"type": "response.failed", "response": {"status": "failed", "error": {"message": "provider failed"}}}
        if outcome == "truncated":
            event = {"type": "response.created", "response": {"id": "partial"}}
        events = [event]
        if outcome.endswith("empty_terminal"):
            events = [
                {"type": "response.output_item.done", "output_index": index, "item": item}
                for index, item in enumerate(terminal["output"])
            ] + [{"type": "response.completed", "response": {**terminal, "output": []}}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(f"data: {json.dumps(item)}\n\n" for item in events).encode())

    @asynccontextmanager
    async def session():
        yield None

    provider = SimpleNamespace(id=2, name="ChatGPT", is_active=True,
        catalog_code="openai-codex", provider_type="openai_codex", configuration={},
        base_url="https://chatgpt.com/backend-api/codex")
    llm = SimpleNamespace(id=1, code="codex", llm_name="gpt-6-astra", llm_provider_id=2,
        cost_per_input_token=None, cost_per_cached_input_token=None, cost_per_output_token=None)
    create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    finalize = AsyncMock()
    token = AsyncMock(return_value=_jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "test"}}))
    client_class = httpx.AsyncClient
    clients = []
    class Client(client_class):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(upstream), **kwargs)
            clients.append(self)
    monkeypatch.setattr(proxy_service, "get_db_session", session)
    monkeypatch.setattr(proxy_service, "enforce_subscription_access", AsyncMock(return_value=1))
    monkeypatch.setattr(proxy_service.llm_provider_service, "get_provider_with_decrypted_key", AsyncMock(return_value=(provider, None)))
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", finalize)
    monkeypatch.setattr(proxy_service.llm_call_service, "update_running_call", AsyncMock())
    monkeypatch.setattr(codex_oauth, "get_access_token", token)
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", Client)
    # This transport unit replaces persistence with synthetic identities.
    from app.llm import protocol_inference
    monkeypatch.setattr(protocol_inference, "proxy_responses", proxy_service.proxy_responses)
    if outcome.startswith("objective"):
        from app.agent import AgentRunContext
        from app.conversation import ConversationTurn, task_objective
        from app.llm.provider_models import LLM, LLMProvider

        llm = LLM(id=1, code="codex", label="Test", llm_name="gpt-6-astra", llm_provider_id=2)
        llm.provider = LLMProvider(id=2, name="ChatGPT", catalog_code="openai-codex",
            provider_type="openai_codex", base_url=provider.base_url)
        agent = SimpleNamespace(id=7, code="test", first_name="Test", last_name="Agent", agent_driver="internal")
        monkeypatch.setattr(task_objective, "get_agent_record", AsyncMock(return_value=agent))
        monkeypatch.setattr(task_objective.llm_service, "get_profile_llm", AsyncMock(return_value=llm))
        monkeypatch.setattr(task_objective, "task_objective_system_prompt", AsyncMock(return_value="Construct the task objective."))
        monkeypatch.setattr(task_objective, "build_agent_run_context", AsyncMock(return_value=AgentRunContext()))
        turn = ConversationTurn(room_id=uuid4(), round_id=uuid4(), agent_id=7,
            language="fr", objective="Vérifier le résultat", messages=(),
            messaging_context={}, reasoning_effort_override="low")
        # Actual objective generation, structured Pydantic output, SDK, proxy and bridge.
        label, objective, _cost = await task_objective.generate_task_fields(
            turn, label_hint="Test", objective_hint=turn.objective)
        assert (label, objective) == ("Test", "Vérifier le résultat")
        assert len(requests) == 1
        assert requests[0]["stream"] is True
        assert create.call_args.kwargs["stream"] is True
        assert create.call_args.kwargs["conversation_round_id"] == turn.round_id
        assert finalize.call_args.kwargs["status"] == "completed"
        assert all(value.is_closed for value in clients)
        return
    unsupported_settings = {"max_output_tokens": 512, "temperature": 0.0, "top_p": 0.9}
    body = {"model": "codex", "input": [], "stream": False, **unsupported_settings}
    response = await proxy_service.proxy_responses(body, task_id=None, llm_override=llm,
        route_executor_model=False, purpose="conversation.task_objective", conversation_round_id=uuid4())
    assert all(request["stream"] is True for request in requests)
    assert body["stream"] is False
    for parameter, value in unsupported_settings.items():
        assert body[parameter] == value
        assert all(parameter not in request for request in requests)
    assert create.call_args.kwargs["stream"] is False
    assert all(value.is_closed for value in clients)
    assert finalize.await_count == 1
    if outcome in {"completed", "refresh", "text_empty_terminal"}:
        assert response.status_code == 200
        assert json.loads(response.body) == terminal
        assert finalize.call_args.kwargs["status"] == "completed"
        assert json.loads(finalize.call_args.kwargs["raw_response"]) == terminal
    else:
        assert response.status_code == 502
        assert finalize.call_args.kwargs["status"] == "error"
        assert "error" in json.loads(response.body)
    if outcome == "refresh":
        assert token.call_args.kwargs["force_refresh"] is True
        assert len(requests) == 2


def test_codex_headers_include_chatgpt_account_id() -> None:
    token = _jwt({
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"},
    })

    headers = codex_request_headers(token)

    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["ChatGPT-Account-ID"] == "acct-123"
    assert headers["originator"] == "codex_cli_rs"


def test_native_terminal_reconstruction_preserves_completed_items_only():
    from app.llm.responses_trace import ResponsesStreamTrace

    trace = ResponsesStreamTrace()
    reasoning = {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "opaque"}
    tool = {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "final_result", "arguments": '{"label":"ok"}', "status": "completed"}
    for index, item in [(1, tool), (0, reasoning), (1, tool)]:
        trace.add_event({"type": "response.output_item.done", "output_index": index, "item": item})
    assert trace.terminal_response is None
    trace.add_event({"type": "response.output_item.added", "output_index": 2, "item": {"type": "function_call", "arguments": "partial"}})
    terminal = {"id": "resp_1", "status": "completed", "output": [], "usage": {"total_tokens": 7}}
    trace.add_event({"type": "response.completed", "response": terminal})
    assert trace.terminal_response == {**terminal, "output": [reasoning, tool]}
    assert terminal["output"] == []
    authoritative = {**terminal, "output": [tool]}
    trace.add_event({"type": "response.completed", "response": authoritative})
    assert trace.terminal_response == authoritative


@pytest.mark.asyncio
async def test_codex_native_responses_compaction_keeps_native_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_oauth,
        "get_access_token",
        AsyncMock(return_value="access-token"),
    )
    connection = ProviderConnection(
        id=4,
        name="OpenAI — ChatGPT",
        catalog_code="openai-codex",
        provider_type="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
    )

    prepared = await CodexBridge().prepare_responses_request(
        4,
        connection,
        {"model": "gpt-5.6-sol", "input": []},
        operation="compact",
    )

    assert prepared.endpoint.endswith("/responses/compact")
    assert prepared.body == {"model": "gpt-5.6-sol", "input": []}


def test_chat_request_is_converted_to_responses_input_and_tools() -> None:
    request = chat_completions_to_responses({
        "model": "gpt-codex",
        "messages": [
            {"role": "system", "content": "Follow the project conventions."},
            {"role": "user", "content": "Inspect the repository."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "contents"},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read one file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }],
        "stream": True,
        "reasoning_effort": "high",
    })

    assert request["instructions"] == "Follow the project conventions."
    assert request["input"] == [
        {"role": "user", "content": "Inspect the repository."},
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        },
        {"type": "function_call_output", "call_id": "call_123", "output": "contents"},
    ]
    assert request["tools"][0]["name"] == "read_file"
    assert request["reasoning"] == {"effort": "high", "summary": "auto"}
    assert request["stream"] is True
    assert request["store"] is False


def test_codex_request_normalizes_legacy_minimal_reasoning_to_low() -> None:
    request = chat_completions_to_responses({
        "model": "gpt-5.6-luna",
        "messages": [{"role": "user", "content": "Answer briefly."}],
        "reasoning_effort": "minimal",
    })

    assert request["reasoning"] == {"effort": "low", "summary": "auto"}


def test_codex_response_is_converted_to_chat_completion() -> None:
    response = responses_to_chat_completion({
        "id": "resp_123",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "I should inspect it."}],
            },
            {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "I am checking."}],
            },
            {
                "type": "function_call",
                "id": "fc_123",
                "call_id": "call_123",
                "name": "read_file",
                "arguments": '{"path":"README.md"}',
            },
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }, model="gpt-codex")

    choice = response["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    assert choice["message"]["reasoning_content"] == "I should inspect it.\n\nI am checking."
    assert choice["message"]["tool_calls"][0]["id"] == "call_123"
    assert response["usage"]["prompt_tokens_details"]["cached_tokens"] == 3
    assert response["usage"]["completion_tokens_details"]["reasoning_tokens"] == 2


def test_codex_sse_is_converted_to_chat_chunks() -> None:
    adapter = CodexSSEAdapter("gpt-codex")
    chunks = adapter.convert({
        "type": "response.created",
        "response": {"id": "resp_123", "model": "gpt-codex", "created_at": 1234},
    })
    chunks += adapter.convert({
        "type": "response.output_item.added",
        "output_index": 0,
        "item": {
            "id": "fc_123",
            "type": "function_call",
            "call_id": "call_123",
            "name": "read_file",
            "arguments": "",
        },
    })
    chunks += adapter.convert({
        "type": "response.function_call_arguments.delta",
        "output_index": 0,
        "item_id": "fc_123",
        "delta": '{"path":"README.md"}',
    })
    chunks += adapter.convert({
        "type": "response.completed",
        "response": {
            "id": "resp_123",
            "status": "completed",
            "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        },
    })

    tool_deltas = [
        tool
        for chunk in chunks
        for tool in chunk["choices"][0]["delta"].get("tool_calls", [])
    ]
    assert tool_deltas[0]["id"] == "call_123"
    assert tool_deltas[0]["function"]["name"] == "read_file"
    assert tool_deltas[1]["function"]["arguments"] == '{"path":"README.md"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"]["total_tokens"] == 7
    assert adapter.terminal is True


def test_codex_commentary_streams_as_reasoning() -> None:
    adapter = CodexSSEAdapter("gpt-codex")
    adapter.convert({
        "type": "response.output_item.added",
        "output_index": 2,
        "item": {"type": "message", "phase": "commentary"},
    })

    chunks = adapter.convert({
        "type": "response.output_text.delta",
        "output_index": 2,
        "delta": "Checking the repository…",
    })

    assert chunks[-1]["choices"][0]["delta"]["reasoning_content"] == "Checking the repository…"


def test_codex_stream_keeps_sequential_reasoning_summaries() -> None:
    adapter = CodexSSEAdapter("gpt-codex")

    first = adapter.convert({
        "type": "response.reasoning_summary_text.delta",
        "output_index": 0,
        "summary_index": 0,
        "delta": "Inspecting the repository.",
    })
    second = adapter.convert({
        "type": "response.reasoning_summary_text.done",
        "output_index": 0,
        "summary_index": 1,
        "text": "Planning the correction.",
    })

    assert first[-1]["choices"][0]["delta"]["reasoning_content"] == (
        "Inspecting the repository."
    )
    assert second[-1]["choices"][0]["delta"]["reasoning_content"] == (
        "\n\nPlanning the correction."
    )


def test_codex_stream_keeps_revised_cutoff_summary() -> None:
    adapter = CodexSSEAdapter("gpt-codex")
    adapter.convert({
        "type": "response.reasoning_summary_text.delta",
        "output_index": 0,
        "summary_index": 0,
        "delta": "Inspecting…",
    })

    chunks = adapter.convert({
        "type": "response.reasoning_summary_text.done",
        "output_index": 0,
        "summary_index": 0,
        "text": "Inspecting the complete repository.",
    })

    assert chunks[-1]["choices"][0]["delta"]["reasoning_content"] == (
        "\n\nInspecting the complete repository."
    )


@pytest.mark.asyncio
async def test_proxy_bridges_managed_runtime_nonstream_call_to_codex_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    task_id = uuid4()

    class FakeProvider:
        id = 2
        name = "ChatGPT"
        base_url = "https://chatgpt.com/backend-api/codex"
        is_active = True
        catalog_code = "openai-codex"
        provider_type = "openai_codex"
        configuration = {}

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"type":"response.created","response":{"id":"resp_bridge","model":"gpt-codex","created_at":1234}}'
            yield 'data: {"type":"response.output_item.added","output_index":0,"item":{"type":"message","phase":"final"}}'
            yield 'data: {"type":"response.output_text.delta","output_index":0,"delta":"{\\"decision\\":\\"allow\\"}"}'
            yield 'data: {"type":"response.completed","response":{"id":"resp_bridge","status":"completed","usage":{"input_tokens":8,"output_tokens":3,"total_tokens":11}}}'

        async def aread(self) -> bytes:
            raise AssertionError("the bridged Codex response must be consumed as SSE")

        async def aclose(self) -> None:
            captured["upstream_closed"] = True

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, method: str, url: str, **kwargs):
            captured["json"] = kwargs["json"]
            return object()

        async def send(self, request, stream: bool = False):
            captured["upstream_stream"] = stream
            return FakeUpstream()

        async def aclose(self) -> None:
            captured["client_closed"] = True

    class FakeDbSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    async def get_provider(provider_id: int):
        assert provider_id == 2
        return FakeProvider(), None

    async def get_token(provider_id: int, *, force_refresh: bool = False) -> str:
        assert provider_id == 2
        assert force_refresh is False
        return _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"}})

    async def create_call(**kwargs):
        captured["recorded_stream"] = kwargs["stream"]
        return SimpleNamespace(id=uuid4())

    async def finalize_call(*args, **kwargs) -> None:
        captured["final_status"] = kwargs["status"]
        captured["trace"] = kwargs["trace"]
        captured["raw_response"] = kwargs["raw_response"]

    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())
    monkeypatch.setattr(
        proxy_service,
        "resolve_task_reasoning_effort",
        AsyncMock(return_value=proxy_service.TaskReasoningPolicy(resolved=False)),
    )
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        get_provider,
    )
    monkeypatch.setattr(
        proxy_service,
        "enforce_subscription_access",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(codex_oauth, "get_access_token", get_token)
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create_call)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", finalize_call)
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeClient)

    response = await proxy_service.proxy_chat_completion(
        {
            "model": "codex-main",
            "messages": [{"role": "user", "content": "Review this command"}],
            "stream": False,
        },
        task_id=task_id,
        agent_id=7,
        managed_runtime_request=True,
        llm_override=SimpleNamespace(
            id=1,
            code="codex-main",
            llm_name="gpt-codex",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        ),
    )

    payload = json.loads(bytes(response.body))
    assert captured["recorded_stream"] is False
    assert captured["json"]["stream"] is True
    assert captured["upstream_stream"] is True
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == '{"decision":"allow"}'
    assert payload["usage"]["total_tokens"] == 11
    assert captured["final_status"] == "completed"
    assert captured["trace"]["response_text"] == '{"decision":"allow"}'
    assert json.loads(captured["raw_response"]) == payload
    assert captured["upstream_closed"] is True
    assert captured["client_closed"] is True

    streamed_response = await proxy_service.proxy_chat_completion(
        {
            "model": "codex-main",
            "messages": [{"role": "user", "content": "Review this command"}],
            "stream": True,
        },
        task_id=task_id,
        agent_id=7,
        managed_runtime_request=True,
        llm_override=SimpleNamespace(
            id=1,
            code="codex-main",
            llm_name="gpt-codex",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        ),
    )

    assert isinstance(streamed_response, StreamingResponse)
    streamed_chunks = [chunk async for chunk in streamed_response.body_iterator]
    assert captured["recorded_stream"] is True
    assert b'{\\"decision\\":\\"allow\\"}' in b"".join(streamed_chunks)
    assert streamed_chunks[-1] == b"data: [DONE]\n\n"
    assert json.loads(captured["raw_response"]) == payload


@pytest.mark.asyncio
async def test_proxy_bridges_regular_nonstream_codex_call_to_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeProvider:
        id = 2
        name = "ChatGPT"
        base_url = "https://chatgpt.com/backend-api/codex"
        is_active = True
        catalog_code = "openai-codex"
        provider_type = "openai_codex"
        configuration = {}

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"type":"response.created","response":{"id":"resp_proxy","model":"gpt-codex","created_at":1234}}'
            yield 'data: {"type":"response.output_item.added","output_index":0,"item":{"type":"message","phase":"final"}}'
            yield 'data: {"type":"response.output_text.delta","output_index":0,"delta":"Bonjour"}'
            yield 'data: {"type":"response.completed","response":{"id":"resp_proxy","status":"completed","usage":{"input_tokens":2,"output_tokens":1,"total_tokens":3}}}'

        async def aread(self) -> bytes:
            raise AssertionError("the bridged Codex response must be consumed as SSE")

        async def aclose(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, method: str, url: str, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            captured["json"] = kwargs["json"]
            return object()

        async def send(self, request, stream: bool = False):
            captured["stream"] = stream
            return FakeUpstream()

        async def aclose(self) -> None:
            return None

    class FakeDbSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    async def get_provider(provider_id: int):
        assert provider_id == 2
        return FakeProvider(), None

    async def get_token(provider_id: int, *, force_refresh: bool = False) -> str:
        assert provider_id == 2
        assert force_refresh is False
        return _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"}})

    async def create_call(**kwargs):
        return SimpleNamespace(id=uuid4())

    async def finalize_call(*args, **kwargs) -> None:
        captured["final_status"] = kwargs["status"]

    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())
    monkeypatch.setattr(
        proxy_service,
        "resolve_task_reasoning_effort",
        AsyncMock(return_value=proxy_service.TaskReasoningPolicy(resolved=False)),
    )
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        get_provider,
    )
    monkeypatch.setattr(
        proxy_service,
        "enforce_subscription_access",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(codex_oauth, "get_access_token", get_token)
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create_call)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", finalize_call)
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeClient)

    response = await proxy_service.proxy_chat_completion(
        {
            "model": "codex-main",
            "messages": [
                {"role": "system", "content": "Réponds en français."},
                {"role": "user", "content": "Bonjour"},
            ],
            "stream": False,
        },
        task_id=uuid4(),
        agent_id=7,
        llm_override=SimpleNamespace(
            id=1,
            code="codex-main",
            llm_name="gpt-codex",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        ),
    )

    payload = json.loads(bytes(response.body))
    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert captured["json"]["instructions"] == "Réponds en français."
    assert captured["json"]["input"] == [{"role": "user", "content": "Bonjour"}]
    assert captured["json"]["stream"] is True
    assert captured["stream"] is True
    assert captured["headers"]["ChatGPT-Account-ID"] == "acct-123"
    assert payload["choices"][0]["message"]["content"] == "Bonjour"
    assert captured["final_status"] == "completed"
