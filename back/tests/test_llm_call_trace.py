import asyncio
import json

import anyio
import httpx
import pytest
from fastapi.responses import StreamingResponse
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.llm import call_router, llm_service, model_usages, proxy_service
from app.llm import llm_call_service
from app.llm.proxy_service import (
    parse_proxy_model,
    resolve_proxy_llm,
    resolve_task_executor_llm,
)
from app.llm.responses_trace import (
    ResponsesStreamTrace,
    request_messages as responses_request_messages,
    response_trace as responses_response_trace,
)
from app.llm.trace import (
    StreamTrace,
    agent_run_id_from_messages,
    extract_prompts,
    infer_call_type,
    infer_call_purpose,
    llm_id_from_messages,
    response_trace,
    task_id_from_messages,
    usage_counters,
)


def test_infer_call_type_identifies_internal_orchestration_and_vision() -> None:
    assert infer_call_type([], "You are the Planner. Build a plan.") == "planning"
    assert infer_call_type([], "You synthesize the overall result of a task.") == "synthesis"
    assert infer_call_type([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}},
            ],
        }
    ]) == "vision"


@pytest.mark.asyncio
async def test_stream_cleanup_survives_an_outer_anyio_cancellation() -> None:
    persisted = False

    async def persist() -> None:
        nonlocal persisted
        await anyio.sleep(0)
        persisted = True

    with anyio.CancelScope() as scope:
        scope.cancel()
        await proxy_service._run_stream_cleanup(  # pyright: ignore[reportPrivateUsage]
            persist,
            call_id=uuid4(),
            operation_name="trace finalization",
        )

    assert persisted is True


def test_agent_execution_trace_projects_the_durable_task_objective() -> None:
    objective = "Calculer 12 + 5 et communiquer le résultat à Nicolas."

    projected = llm_call_service._project_trace_prompt(  # pyright: ignore[reportPrivateUsage]
        purpose="agent.exec",
        request_prompt="<system-reminder>Skill catalogue reminder</system-reminder>",
        task_objective=objective,
    )

    assert projected == objective


def test_infer_call_purpose_recovers_legacy_dream_topic_calls() -> None:
    assert infer_call_purpose(
        [],
        "Return a bounded same_topic_probability for the durable subject.",
    ) == "dream.topic_continuity"
    assert infer_call_purpose(
        [{"role": "user", "content": "Reuse stage: choose one topic_id."}],
    ) == "dream.topic_reuse"
    assert infer_call_purpose(
        [{"role": "user", "content": "Creation stage: propose one topic."}],
    ) == "dream.topic_creation"


def test_extract_prompts_keeps_last_user_and_all_system_messages():
    prompt, system = extract_prompts([
        {"role": "system", "content": "Core instructions"},
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "system", "content": "Task context"},
        {"role": "user", "content": [{"type": "text", "text": "Final question"}]},
    ])

    assert prompt == "Final question"
    assert system == "Core instructions\n\nTask context"


def test_responses_trace_preserves_request_output_usage_and_tools() -> None:
    messages = responses_request_messages({
        "instructions": "Follow the repository rules.",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "Inspect it"}]},
            {"type": "function_call_output", "call_id": "call-1", "output": "contents"},
        ],
    })
    trace = responses_response_trace({
        "id": "resp-1",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "I should inspect it."}],
            },
            {
                "type": "function_call",
                "call_id": "call-2",
                "name": "read_file",
                "arguments": '{"path":"README.md"}',
            },
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 7,
            "total_tokens": 19,
            "cost": 0.031,
        },
    })

    assert messages[0] == {"role": "system", "content": "Follow the repository rules."}
    assert messages[-1]["role"] == "tool"
    assert trace["reasoning"] == "I should inspect it."
    assert trace["tool_calls"][0]["name"] == "read_file"
    assert trace["usage"]["cost"] == pytest.approx(0.031)


def test_responses_stream_trace_uses_terminal_response_as_authority() -> None:
    trace = ResponsesStreamTrace()
    trace.add_event({
        "type": "response.output_item.added",
        "output_index": 0,
        "item": {"type": "message", "phase": "final"},
    })
    assert trace.add_event({
        "type": "response.output_text.delta",
        "output_index": 0,
        "delta": "Draft",
    }) is True
    trace.add_event({
        "type": "response.completed",
        "response": {
            "id": "resp-2",
            "status": "completed",
            "output": [{
                "type": "message",
                "phase": "final",
                "content": [{"type": "output_text", "text": "Final"}],
            }],
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
        },
    })

    assert trace.terminal is True
    assert trace.result()["response_text"] == "Final"
    assert trace.result()["usage"]["total_tokens"] == 4


def test_streamed_responses_persist_only_the_terminal_result() -> None:
    trace = ResponsesStreamTrace()
    trace.add_event({
        "type": "response.output_text.delta",
        "output_index": 0,
        "delta": "partial",
    })

    assert proxy_service._serialized_final_responses_result(trace) == ""  # pyright: ignore[reportPrivateUsage]

    terminal = {
        "id": "resp-2",
        "status": "completed",
        "output": [{
            "type": "message",
            "phase": "final",
            "content": [{"type": "output_text", "text": "Final"}],
        }],
        "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    }
    trace.add_event({"type": "response.completed", "response": terminal})

    persisted = proxy_service._serialized_final_responses_result(trace)  # pyright: ignore[reportPrivateUsage]
    assert json.loads(persisted) == terminal
    assert "response.completed" not in persisted


def test_response_trace_collects_reasoning_tools_and_detailed_usage():
    trace = response_trace({
        "id": "req-1",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "I will check.",
                "reasoning_content": "The source must be checked.",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{\"query\":\"Galaris\"}"},
                }],
            },
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
            "prompt_tokens_details": {"cached_tokens": 40},
            "completion_tokens_details": {"reasoning_tokens": 10},
        },
    })

    assert trace["response_text"] == "I will check."
    assert trace["reasoning"] == "The source must be checked."
    assert trace["tool_calls"][0]["name"] == "search"
    assert trace["tool_calls"][0]["arguments"] == {"query": "Galaris"}
    assert usage_counters(trace["usage"]) == {
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
        "cache_read_tokens": 40,
        "cache_write_tokens": 0,
        "reasoning_tokens": 10,
    }


def test_streamed_chat_persists_only_a_complete_reconstructed_response() -> None:
    trace = StreamTrace()
    trace.add_payload({
        "id": "gen-1",
        "model": "deepseek/deepseek-v4-flash-0731",
        "provider": "Sail Research",
        "choices": [{"delta": {"content": "Bon"}, "finish_reason": None}],
    })

    assert proxy_service._serialized_final_chat_completion(  # pyright: ignore[reportPrivateUsage]
        trace,
        model="deepseek/deepseek-v4-flash-0731",
    ) == ""

    trace.add_payload({
        "id": "gen-1",
        "model": "deepseek/deepseek-v4-flash-0731",
        "choices": [{"delta": {"content": "jour"}, "finish_reason": "stop"}],
    })
    trace.add_payload({
        "id": "gen-1",
        "model": "deepseek/deepseek-v4-flash-0731",
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.000123},
    })

    persisted = proxy_service._serialized_final_chat_completion(  # pyright: ignore[reportPrivateUsage]
        trace,
        model="deepseek/deepseek-v4-flash-0731",
    )
    payload = json.loads(persisted)
    assert payload["choices"][0]["message"]["content"] == "Bonjour"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"]["cost"] == pytest.approx(0.000123)
    assert payload["provider"] == "Sail Research"
    assert not persisted.startswith("data:")


def test_response_trace_unwraps_deferred_hermes_tool_calls() -> None:
    trace = response_trace(
        {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "tool_call",
                            "arguments": (
                                '{"name":"mcp__galaris__messenger_room_send_message",'
                                '"arguments":{"room_id":"room-42","message":"Bonjour"}}'
                            ),
                        },
                    }],
                },
            }],
        },
        unwrap_deferred_tools=True,
    )

    assert trace["tool_calls"] == [{
        "id": "call-1",
        "type": "function",
        "name": "messenger_room_send_message",
        "arguments": {"room_id": "room-42", "message": "Bonjour"},
        "status": "requested",
    }]


def test_response_trace_keeps_richer_reasoning_details() -> None:
    trace = response_trace({
        "choices": [{
            "message": {
                "reasoning_content": "Short summary.",
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "First detailed step."},
                    {"type": "reasoning.text", "text": "Second detailed step."},
                ],
            },
        }],
    })

    assert trace["reasoning"] == "First detailed step.\nSecond detailed step."


def test_stream_trace_reassembles_fragmented_tool_call_and_reasoning():
    trace = StreamTrace()
    trace.add_payload({
        "id": "chatcmpl-1",
        "choices": [{"delta": {
            "reasoning_content": "Let us analyze ",
            "tool_calls": [{
                "index": 0,
                "id": "call-42",
                "type": "function",
                "function": {"name": "messenger_room_", "arguments": "{\"room"},
            }],
        }}],
    })
    trace.add_payload({
        "choices": [{
            "delta": {
                "reasoning_content": "the request.",
                "tool_calls": [{
                    "index": 0,
                    "function": {"name": "history", "arguments": "_id\":\"abc\"}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    })

    result = trace.result()
    assert result["reasoning"] == "Let us analyze the request."
    assert result["tool_calls"] == [{
        "id": "call-42",
        "type": "function",
        "name": "messenger_room_history",
        "arguments": {"room_id": "abc"},
        "status": "requested",
    }]
    assert result["finish_reason"] == "tool_calls"
    assert result["upstream_request_id"] == "chatcmpl-1"


def test_stream_trace_unwraps_deferred_hermes_tool_calls() -> None:
    trace = StreamTrace()
    trace.add_payload({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call-42",
                    "type": "function",
                    "function": {
                        "name": "tool_call",
                        "arguments": (
                            '{"name":"mcp__galaris__messenger_room_send_message",'
                            '"arguments":{"room_id":"room-42","message":"Bonjour"}}'
                        ),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
    })

    result = trace.result(unwrap_deferred_tools=True)

    assert result["tool_calls"] == [{
        "id": "call-42",
        "type": "function",
        "name": "messenger_room_send_message",
        "arguments": {"room_id": "room-42", "message": "Bonjour"},
        "status": "requested",
    }]


def test_llm_call_tool_merge_preserves_started_at_and_completed_result() -> None:
    merged = llm_call_service._merge_tool_results(  # pyright: ignore[reportPrivateUsage]
        previous=[{
            "id": "call-1",
            "name": "search",
            "arguments": {"q": "x"},
            "status": "completed",
            "result": "ok",
            "started_at": "2026-07-09T10:00:00+00:00",
            "completed_at": "2026-07-09T10:00:03+00:00",
        }],
        current=[{
            "id": "call-1",
            "name": "search",
            "arguments": {"q": "x"},
            "status": "requested",
        }],
    )

    assert merged == [{
        "id": "call-1",
        "name": "search",
        "arguments": {"q": "x"},
        "status": "completed",
        "started_at": "2026-07-09T10:00:00+00:00",
        "result": "ok",
        "completed_at": "2026-07-09T10:00:03+00:00",
    }]


def test_parse_proxy_model_uses_explicit_galaris_identifier():
    assert parse_proxy_model("llm-17") == 17
    assert parse_proxy_model(17) == 17


def test_upstream_error_payload_is_not_a_success_even_with_http_200() -> None:
    succeeded = proxy_service._upstream_response_succeeded(  # pyright: ignore[reportPrivateUsage]
        True,
        {"error": {"message": "Provider temporarily unavailable"}},
    )

    assert succeeded is False


@pytest.mark.asyncio
async def test_resolve_proxy_llm_prefers_stable_code(monkeypatch):
    by_code = object()
    by_id = object()

    async def get_llm_by_code(code: str):
        return by_code if code == "fast-model" else None

    async def get_llm(llm_id: int):
        return by_id if llm_id == 17 else None

    monkeypatch.setattr(proxy_service.llm_service, "get_llm_by_code", get_llm_by_code)
    monkeypatch.setattr(proxy_service.llm_service, "get_llm", get_llm)

    assert await resolve_proxy_llm("fast-model") is by_code
    assert await resolve_proxy_llm("llm-17") is by_id


@pytest.mark.asyncio
async def test_resolve_proxy_llm_maps_claude_and_codex_aliases_to_text_tiers(
    monkeypatch,
):
    resolved = object()
    seen: list[tuple[str, int | None]] = []

    async def get_llm_by_code(_code: str):
        return None

    async def get_profile_llm_for_agent_id(model_field: str, agent_id: int | None):
        seen.append((model_field, agent_id))
        return resolved

    monkeypatch.setattr(proxy_service.llm_service, "get_llm_by_code", get_llm_by_code)
    monkeypatch.setattr(
        proxy_service.llm_service,
        "get_profile_llm_for_agent_id",
        get_profile_llm_for_agent_id,
    )

    aliases = {
        "claude-haiku-5": model_usages.TEXT_ULTRA_LOW,
        "sonnet": model_usages.TEXT_LOW,
        "claude-opus-5": model_usages.TEXT_STANDARD,
        "fable": model_usages.TEXT_HIGH,
        "gpt-5.6-luna": model_usages.TEXT_LOW,
        "gpt-5.6-terra": model_usages.TEXT_STANDARD,
        "gpt-5.6-sol": model_usages.TEXT_HIGH,
    }
    for alias, expected_tier in aliases.items():
        assert await resolve_proxy_llm(alias, agent_id=7) is resolved
        assert seen[-1] == (expected_tier, 7)


@pytest.mark.asyncio
async def test_resolve_task_executor_llm_only_overrides_high_tasks(monkeypatch):
    task_id = uuid4()
    high_llm = object()

    async def get_by_id(raw_task_id):
        assert raw_task_id == task_id
        return SimpleNamespace(parent_id=None, effort="high", agent=None)

    async def get_executor_llm_for_task(task):
        assert task.effort == "high"
        return high_llm

    from app.task import task_service

    monkeypatch.setattr(task_service, "get_by_id", get_by_id)
    monkeypatch.setattr(
        proxy_service.llm_service,
        "get_executor_llm_for_task",
        get_executor_llm_for_task,
    )

    assert await resolve_task_executor_llm(task_id) is high_llm
    assert await resolve_task_executor_llm(None) is None


@pytest.mark.asyncio
async def test_resolve_task_executor_llm_ignores_standard_tasks(monkeypatch):
    task_id = uuid4()

    async def get_by_id(raw_task_id):
        assert raw_task_id == task_id
        return SimpleNamespace(parent_id=None, effort="standard", agent=None)

    async def fail_get_executor_llm_for_task(task):
        raise AssertionError("standard tasks must keep the requested model")

    from app.task import task_service

    monkeypatch.setattr(task_service, "get_by_id", get_by_id)
    monkeypatch.setattr(
        proxy_service.llm_service,
        "get_executor_llm_for_task",
        fail_get_executor_llm_for_task,
    )

    assert await resolve_task_executor_llm(task_id) is None


@pytest.mark.asyncio
async def test_resolve_task_executor_llm_ignores_standard_subtasks(monkeypatch):
    task_id = uuid4()

    async def get_by_id(raw_task_id):
        assert raw_task_id == task_id
        return SimpleNamespace(parent_id=uuid4(), effort="standard", agent=None)

    async def fail_get_executor_llm_for_task(task):
        raise AssertionError("standard subtasks must keep the requested model")

    from app.task import task_service

    monkeypatch.setattr(task_service, "get_by_id", get_by_id)
    monkeypatch.setattr(
        proxy_service.llm_service,
        "get_executor_llm_for_task",
        fail_get_executor_llm_for_task,
    )

    assert await resolve_task_executor_llm(task_id) is None


@pytest.mark.asyncio
async def test_resolve_task_executor_llm_overrides_high_subtasks(monkeypatch):
    task_id = uuid4()
    high_llm = object()

    async def get_by_id(raw_task_id):
        assert raw_task_id == task_id
        return SimpleNamespace(parent_id=uuid4(), effort="high", agent=None)

    async def get_executor_llm_for_task(task):
        assert task.effort == "high"
        return high_llm

    from app.task import task_service

    monkeypatch.setattr(task_service, "get_by_id", get_by_id)
    monkeypatch.setattr(
        proxy_service.llm_service,
        "get_executor_llm_for_task",
        get_executor_llm_for_task,
    )

    assert await resolve_task_executor_llm(task_id) is high_llm


@pytest.mark.asyncio
async def test_get_executor_llm_for_task_uses_subtask_effort(monkeypatch):
    captured: dict[str, object] = {}
    selected_llm = object()
    agent = object()

    async def get_executor_llm_for_effort(raw_agent, effort: str):
        captured["agent"] = raw_agent
        captured["effort"] = effort
        return selected_llm

    monkeypatch.setattr(
        llm_service,
        "get_executor_llm_for_effort",
        get_executor_llm_for_effort,
    )

    task = SimpleNamespace(parent_id=uuid4(), effort="standard", agent=agent)

    assert await llm_service.get_executor_llm_for_task(task) is selected_llm
    assert captured == {"agent": agent, "effort": "standard"}


@pytest.mark.asyncio
async def test_proxy_chat_completion_allows_taskless_internal_round_with_agent_id_and_override(
    monkeypatch,
):
    call_id = uuid4()
    conversation_round_id = uuid4()
    captured: dict[str, object] = {}

    class FakeProvider:
        id = 2
        name = "provider"
        catalog_code = None
        provider_type = "openai_compatible"
        base_url = "https://provider.test/v1"
        configuration: dict[str, object] = {}
        is_active = True

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aread(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        async def aclose(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, *args, **kwargs):
            return object()

        async def send(self, request, stream: bool = False):
            return FakeUpstream()

        async def aclose(self) -> None:
            return None

    async def fail_resolve_proxy_llm(model, *, agent_id=None):
        raise AssertionError("resolve_proxy_llm should not be called")

    async def fake_get_provider_with_decrypted_key(provider_id):
        return FakeProvider(), "secret"

    async def fake_create_running_call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=call_id)

    async def fake_finalize_call(*args, **kwargs):
        return None

    class FakeDbSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(proxy_service, "resolve_proxy_llm", fail_resolve_proxy_llm)
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        fake_get_provider_with_decrypted_key,
    )
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "create_running_call",
        fake_create_running_call,
    )
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "finalize_call",
        fake_finalize_call,
    )
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())

    response = await proxy_service.proxy_chat_completion(
        {"model": "demo", "messages": [], "stream": False},
        task_id=None,
        conversation_round_id=conversation_round_id,
        agent_id=42,
        llm_override=SimpleNamespace(
            id=1,
            code="demo",
            llm_name="provider-model",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        ),
    )

    assert response.status_code == 200
    assert captured["task_id"] is None
    assert captured["conversation_round_id"] == conversation_round_id
    assert captured["agent_id"] == 42


@pytest.mark.asyncio
async def test_proxy_chat_completion_uses_task_high_llm(monkeypatch):
    call_id = uuid4()
    task_id = uuid4()
    captured: dict[str, object] = {}

    class FakeProvider:
        id = 2
        name = "provider"
        catalog_code = None
        provider_type = "openai_compatible"
        base_url = "https://provider.test/v1"
        configuration: dict[str, object] = {}
        is_active = True

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aread(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        async def aclose(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, *args, **kwargs):
            captured["json"] = kwargs["json"]
            return object()

        async def send(self, request, stream: bool = False):
            return FakeUpstream()

        async def aclose(self) -> None:
            return None

    class FakeDbSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    high_llm = SimpleNamespace(
        id=10,
        code="high",
        llm_name="provider-high",
        llm_provider_id=2,
        cost_per_input_token=None,
        cost_per_cached_input_token=None,
        cost_per_output_token=None,
    )

    async def fake_resolve_task_executor_llm(raw_task_id):
        assert raw_task_id == task_id
        return high_llm

    async def fail_resolve_proxy_llm(model, *, agent_id=None):
        raise AssertionError("high task must not use the requested proxy model")

    async def fake_get_provider_with_decrypted_key(provider_id):
        return FakeProvider(), "secret"

    async def fake_create_running_call(**kwargs):
        captured["requested_model"] = kwargs["requested_model"]
        captured["effective_model"] = kwargs["effective_model"]
        captured["purpose"] = kwargs["purpose"]
        return SimpleNamespace(id=call_id)

    async def fake_finalize_call(*args, **kwargs):
        return None

    monkeypatch.setattr(proxy_service, "resolve_task_executor_llm", fake_resolve_task_executor_llm)
    monkeypatch.setattr(
        proxy_service,
        "resolve_task_reasoning_effort",
        AsyncMock(
            return_value=proxy_service.TaskReasoningPolicy(
                resolved=True,
                effort="xhigh",
            )
        ),
    )
    monkeypatch.setattr(proxy_service, "resolve_proxy_llm", fail_resolve_proxy_llm)
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        fake_get_provider_with_decrypted_key,
    )
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", fake_create_running_call)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", fake_finalize_call)
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())

    response = await proxy_service.proxy_chat_completion(
        {"model": "standard", "messages": [], "stream": False},
        task_id=task_id,
        agent_id=42,
        managed_runtime_request=True,
    )

    assert response.status_code == 200
    assert captured["requested_model"] == "standard"
    assert captured["effective_model"] == "provider-high"
    assert captured["purpose"] == "agent.exec"
    # An opaque deployment delegates support to its provider, preserving the Task effort.
    assert captured["json"]["reasoning_effort"] == "xhigh"
    assert captured["json"]["model"] == "provider-high"


def test_profile_reasoning_wins_unless_harness_explicitly_forces() -> None:
    assert proxy_service.effective_reasoning_effort(
        "low",
        configured="xhigh",
        force=False,
    ) == "xhigh"
    assert proxy_service.effective_reasoning_effort(
        "low",
        configured="xhigh",
        force=True,
    ) == "low"


@pytest.mark.asyncio
async def test_frozen_automatic_reasoning_does_not_fall_back_to_live_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import task_service

    task_id = uuid4()
    run_id = uuid4()
    task = SimpleNamespace(
        data={
            "_agent_run_identity": {
                "request_run_id": str(run_id),
                "reasoning_effort": None,
            }
        }
    )
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=task))

    policy = await proxy_service.resolve_task_reasoning_effort(task_id, run_id)

    assert policy == proxy_service.TaskReasoningPolicy(resolved=True, effort=None)
    assert proxy_service.effective_reasoning_effort(
        "low",
        configured=None,
        force=False,
    ) == "low"


@pytest.mark.asyncio
async def test_task_reasoning_override_wins_in_legacy_proxy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import task_service

    task_id = uuid4()
    task = SimpleNamespace(
        reasoning_effort_override="high",
        data={},
    )
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=task))

    policy = await proxy_service.resolve_task_reasoning_effort(task_id, None)

    assert policy == proxy_service.TaskReasoningPolicy(resolved=True, effort="high")


@pytest.mark.asyncio
async def test_proxy_chat_completion_rejects_taskless_managed_runtime() -> None:
    with pytest.raises(ValueError, match="must be attached to a Galaris Task"):
        await proxy_service.proxy_chat_completion(
            {"model": "standard", "messages": [], "stream": False},
            task_id=None,
            agent_id=42,
            managed_runtime_request=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", ["gpt-5.6-terra", "gpt-6-astra"])
async def test_proxy_responses_uses_frozen_model_code_and_native_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
) -> None:
    call_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    process_run_id = uuid4()
    captured: dict[str, object] = {}

    class FakeProvider:
        id = 2
        name = "OpenAI API"
        catalog_code = "openai-api"
        provider_type = "openai_compatible"
        base_url = "https://api.openai.test/v1"
        configuration: dict[str, object] = {}
        is_active = True

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aread(self) -> bytes:
            return (
                b'{"id":"resp-1","status":"completed","output":['
                b'{"type":"message","phase":"final","content":['
                b'{"type":"output_text","text":"ok"}]}],'
                b'"usage":{"input_tokens":10,"output_tokens":2,"total_tokens":12,"cost":0.04}}'
            )

        async def aclose(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, method: str, url: str, **kwargs):
            captured["method"] = method
            captured["url"] = url
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

    llm = SimpleNamespace(
        id=11,
        code="executor-terra",
        llm_name=model_name,
        llm_provider_id=2,
        cost_per_input_token=None,
        cost_per_cached_input_token=None,
        cost_per_output_token=None,
        is_subscription=False,
    )

    async def resolve(model: object, *, agent_id: int | None = None):
        assert agent_id == 7
        captured["resolved_model"] = model
        return llm

    async def provider(provider_id: int):
        assert provider_id == 2
        return FakeProvider(), "secret"

    async def create_call(**kwargs):
        captured["call"] = kwargs
        return SimpleNamespace(id=call_id)

    async def finalize_call(*args, **kwargs):
        captured["finalize"] = kwargs

    monkeypatch.setattr(proxy_service, "resolve_proxy_llm", resolve)
    monkeypatch.setattr(
        proxy_service,
        "resolve_task_reasoning_effort",
        AsyncMock(
            return_value=proxy_service.TaskReasoningPolicy(
                resolved=True,
                effort="medium",
            )
        ),
    )
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        provider,
    )
    monkeypatch.setattr(proxy_service.llm_call_service, "create_running_call", create_call)
    monkeypatch.setattr(proxy_service.llm_call_service, "finalize_call", finalize_call)
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())

    response = await proxy_service.proxy_responses(
        {
            "model": "gpt-5.6-terra",
            "instructions": "Work carefully.",
            "input": [{"role": "user", "content": "Do it"}],
            "stream": False,
            "temperature": 0.0,
            "top_p": 0.8,
        },
        task_id=task_id,
        agent_run_id=run_id,
        process_run_id=process_run_id,
        agent_id=7,
        model_code="executor-terra",
        managed_runtime_request=True,
    )

    assert response.status_code == 200
    assert captured["resolved_model"] == "executor-terra"
    assert captured["url"] == "https://api.openai.test/v1/responses"
    assert captured["json"]["model"] == model_name  # type: ignore[index]
    assert "temperature" not in captured["json"]
    assert "top_p" not in captured["json"]
    assert captured["json"]["reasoning"]["effort"] == "medium"  # type: ignore[index]
    assert captured["call"]["agent_run_id"] == run_id  # type: ignore[index]
    assert captured["call"]["process_run_id"] == process_run_id  # type: ignore[index]
    assert captured["call"]["reasoning_effort"] == "medium"  # type: ignore[index]
    assert captured["call"]["request_body"]["messages"][0]["role"] == "system"  # type: ignore[index]
    assert captured["finalize"]["trace"]["usage"]["cost"] == pytest.approx(0.04)  # type: ignore[index]
    assert str(captured["finalize"]["raw_response"]).startswith(
        '{"id":"resp-1","status":"completed"'
    )

    compact_response = await proxy_service.proxy_responses(
        {
            "model": "gpt-5.6-terra",
            "input": [{"role": "user", "content": "Long history"}],
            "reasoning": {"effort": "high"},
            "reasoning_effort": "low",
        },
        operation="compact",
        task_id=task_id,
        agent_run_id=run_id,
        agent_id=7,
        model_code="executor-terra",
    )

    assert compact_response.status_code == 200
    assert captured["url"] == "https://api.openai.test/v1/responses/compact"
    assert "reasoning" not in captured["json"]  # type: ignore[operator]
    assert "reasoning_effort" not in captured["json"]  # type: ignore[operator]
    assert captured["stream"] is False
    assert captured["call"]["reasoning_effort"] is None  # type: ignore[index]


@pytest.mark.asyncio
async def test_adapted_responses_stream_persists_reconstructed_final_result() -> None:
    class FakeUpstream:
        headers = httpx.Headers()
        async def aiter_lines(self):
            yield "event: response.created"
            yield 'data: {"type":"response.created"}'
            yield ""
            yield "event: response.completed"
            yield 'data: {"type":"response.completed"}'
            yield ""
            yield ': provider accounting follows'
            yield 'data: {"billing":{"cost":0.04}}'
            yield ""
            yield "data: [DONE]"

    class FakeAdapter:
        response_id = "resp-1"
        created = 1
        model = "provider-model"
        terminal = False

        def convert(self, event):
            if event["type"] == "response.created":
                return []
            assert event["type"] == "response.completed"
            self.terminal = True
            return [{
                "id": self.response_id,
                "model": self.model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": "done"},
                    "finish_reason": "stop",
                }],
            }]

    payload, raw_response = await proxy_service._consume_adapted_stream_as_completion(
        FakeUpstream(),  # type: ignore[arg-type]
        model="provider-model",
        adapter=FakeAdapter(),  # type: ignore[arg-type]
    )

    assert json.loads(raw_response) == payload
    assert payload["choices"][0]["message"]["content"] == "done"
    assert "response.completed" not in raw_response


@pytest.mark.asyncio
async def test_run_usage_aggregates_gateway_cost_with_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()

    async def authenticate(request: object) -> int:
        return 7

    async def list_calls(**kwargs):
        assert kwargs["agent_run_id"] == run_id
        return [
            SimpleNamespace(
                agent_id=7,
                status="completed",
                input_tokens=10,
                output_tokens=4,
                cache_read_tokens=3,
                cache_write_tokens=0,
                reasoning_tokens=2,
                tool_calls=[{"id": "call-1"}],
                cost=0.08,
                inference_cost=0.08,
                cost_estimated=False,
                is_subscription=False,
            ),
            SimpleNamespace(
                agent_id=7,
                status="completed",
                input_tokens=5,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
                reasoning_tokens=0,
                tool_calls=[],
                cost=0.02,
                inference_cost=0.02,
                cost_estimated=False,
                is_subscription=False,
            ),
        ]

    monkeypatch.setattr(call_router, "_llm_api_auth", authenticate)
    monkeypatch.setattr(call_router.llm_call_service, "list_calls", list_calls)

    usage = await call_router.llm_run_usage(run_id, SimpleNamespace())  # type: ignore[arg-type]

    assert usage["input_tokens"] == 15
    assert usage["requests"] == 2
    assert usage["cost"] == pytest.approx(0.10)
    assert usage["cost_quality"] == "exact"


def test_task_id_is_read_from_canonical_task_uri_with_legacy_fallback():
    # New prompts carry the canonical Task URI. The legacy task_id key remains readable so
    # historical traces can still be correlated.
    messages = [
        {
            "role": "user",
            "content": (
                "<galaris_message_context>\n"
                '{"task_id": "0f336215-a34a-4b37-9aa1-27421b5c9755", "datetime": "Friday"}\n'
                "</galaris_message_context>\nAncien tour"
            ),
        },
        {
            "role": "user",
            "content": (
                "<galaris_message_context>\n"
                '{"task_uri": "galaris://task/6b1d8c1e-0d0f-4c34-9a58-1c1caa6a6d42"}\n'
                "</galaris_message_context>\nCurrent turn"
            ),
        },
    ]

    assert str(task_id_from_messages(messages)) == "6b1d8c1e-0d0f-4c34-9a58-1c1caa6a6d42"


def test_resolved_llm_id_is_read_from_the_latest_message_context() -> None:
    messages = [
        {"role": "user", "content": '{"task_id": "0f336215-a34a-4b37-9aa1-27421b5c9755", "llm_id": "7"}'},
        {"role": "user", "content": '{"task_id": "6b1d8c1e-0d0f-4c34-9a58-1c1caa6a6d42", "llm_id": "12"}'},
    ]

    assert llm_id_from_messages(messages) == 12


def test_agent_run_id_is_read_without_a_task_id() -> None:
    messages = [
        {
            "role": "user",
            "content": '{"run_id": "a2ae2694-e3ab-42c6-a84d-b41912590ec5"}',
        }
    ]

    assert task_id_from_messages(messages) is None
    assert str(agent_run_id_from_messages(messages)) == (
        "a2ae2694-e3ab-42c6-a84d-b41912590ec5"
    )
@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["done", "finish_reason", "missing"])
async def test_stream_trace_finalization_error_does_not_abort_sse(monkeypatch, terminal):
    call_id = uuid4()

    class FakeProvider:
        id = 2
        name = "provider"
        catalog_code = None
        provider_type = "openai_compatible"
        base_url = "https://provider.test/v1"
        configuration: dict[str, object] = {}
        is_active = True

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            if terminal == "done":
                yield "data: [DONE]"
            elif terminal == "finish_reason":
                yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'

        async def aclose(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, *args, **kwargs):
            return object()

        async def send(self, request, stream: bool = False):
            return FakeUpstream()

        async def aclose(self) -> None:
            return None

    async def fake_create_running_call(**kwargs):
        return SimpleNamespace(id=call_id)

    async def fake_finalize_call(*args, **kwargs):
        assert kwargs["status"] == ("error" if terminal == "missing" else "completed")
        raise RuntimeError("This session is in 'prepared' state")

    async def fake_resolve_proxy_llm(model, *, agent_id=None):
        return SimpleNamespace(
            id=1,
            code="demo",
            llm_name="provider-model",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        )

    async def fake_get_provider_with_decrypted_key(provider_id):
        return FakeProvider(), "secret"

    monkeypatch.setattr(
        proxy_service,
        "resolve_proxy_llm",
        fake_resolve_proxy_llm,
    )
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        fake_get_provider_with_decrypted_key,
    )
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "create_running_call",
        fake_create_running_call,
    )
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "finalize_call",
        fake_finalize_call,
    )

    response = await proxy_service.proxy_chat_completion(
        {"model": "demo", "messages": [], "stream": True},
        task_id=None,
        agent_id=None,
    )

    assert isinstance(response, StreamingResponse)
    if terminal == "missing":
        with pytest.raises(RuntimeError, match="before its terminal response"):
            _ = [chunk async for chunk in response.body_iterator]
        return
    chunks = [chunk async for chunk in response.body_iterator]
    assert b"ok" in b"".join(chunks)
    if terminal == "done":
        assert chunks[-1] == b"data: [DONE]\n"


@pytest.mark.asyncio
async def test_cancelled_stream_finalizes_trace_before_transport_cleanup(monkeypatch):
    call_id = uuid4()
    stream_blocked = asyncio.Event()
    finalized = asyncio.Event()
    observed: dict[str, object] = {}

    class FakeProvider:
        id = 2
        name = "provider"
        catalog_code = None
        provider_type = "openai_compatible"
        base_url = "https://provider.test/v1"
        configuration: dict[str, object] = {}
        is_active = True

    class FakeUpstream:
        headers = httpx.Headers()
        is_success = True
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
            stream_blocked.set()
            await asyncio.Future()

        async def aclose(self) -> None:
            assert finalized.is_set()

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def build_request(self, *args, **kwargs):
            return object()

        async def send(self, request, stream: bool = False):
            return FakeUpstream()

        async def aclose(self) -> None:
            assert finalized.is_set()

    class FakeDbSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    async def fake_resolve_proxy_llm(model, *, agent_id=None):
        return SimpleNamespace(
            id=1,
            code="demo",
            llm_name="provider-model",
            llm_provider_id=2,
            cost_per_input_token=None,
            cost_per_cached_input_token=None,
            cost_per_output_token=None,
        )

    async def fake_get_provider_with_decrypted_key(provider_id):
        return FakeProvider(), "secret"

    async def fake_create_running_call(**kwargs):
        return SimpleNamespace(id=call_id)

    async def fake_finalize_call(*args, **kwargs):
        observed.update(kwargs)
        finalized.set()

    async def fake_update_running_call(*args, **kwargs):
        return None

    monkeypatch.setattr(proxy_service, "resolve_proxy_llm", fake_resolve_proxy_llm)
    monkeypatch.setattr(
        proxy_service.llm_provider_service,
        "get_provider_with_decrypted_key",
        fake_get_provider_with_decrypted_key,
    )
    monkeypatch.setattr(proxy_service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "create_running_call",
        fake_create_running_call,
    )
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "finalize_call",
        fake_finalize_call,
    )
    monkeypatch.setattr(
        proxy_service.llm_call_service,
        "update_running_call",
        fake_update_running_call,
    )
    monkeypatch.setattr(proxy_service, "get_db_session", lambda: FakeDbSession())

    response = await proxy_service.proxy_chat_completion(
        {"model": "demo", "messages": [], "stream": True},
        task_id=None,
        agent_id=None,
    )
    assert isinstance(response, StreamingResponse)

    async def consume() -> None:
        async for _chunk in response.body_iterator:
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(stream_blocked.wait(), timeout=1.0)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert observed["status"] == "cancelled"
    assert "disconnected" in str(observed["error"]).lower()
    assert observed["raw_response"] == ""
