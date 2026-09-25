"""Tests for the Anthropic-compatible API (translation, SSE contract, routes)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import AsyncClient

from app.llm.anthropic_schemas import MessageRequest
from app.llm.anthropic_service import (
    AnthropicStreamTranslator,
    _parse_openai_sse_chunks,
    anthropic_input_tokens,
    estimate_openai_body_tokens,
    estimate_text_tokens,
    translate_completion,
    translate_to_openai,
)

import app.llm.anthropic_router as anthropic_router_module


# ───────────────────────── request translation ─────────────────────────


BASIC_REQUEST = {
    "model": "deepseek-flash",
    "max_tokens": 1024,
    "system": "Tu es un assistant concis.",
    "messages": [
        {"role": "user", "content": "Bonjour"},
    ],
}


def test_translate_request_carries_system_prompt_and_stream_flags() -> None:
    request = MessageRequest.model_validate({
        **BASIC_REQUEST,
        "stream": True,
        "temperature": 0.2,
        "top_p": 0.9,
        "stop_sequences": ["STOP"],
        "tools": [{
            "name": "recherche",
            "description": "Cherche une information",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }],
        "tool_choice": {"type": "tool", "name": "recherche"},
    })

    body = translate_to_openai(request)

    assert body["model"] == "deepseek-flash"
    assert body["stream"] is True
    # Ask the upstream for usage so the stream can bill without estimates.
    assert body["stream_options"] == {"include_usage": True}
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9
    assert body["stop"] == "STOP"
    (system, user) = body["messages"]
    assert system == {"role": "system", "content": "Tu es un assistant concis."}
    assert user == {"role": "user", "content": "Bonjour"}
    assert body["tools"] == [{
        "type": "function",
        "function": {
            "name": "recherche",
            "description": "Cherche une information",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }]
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "recherche"},
    }


def test_tool_use_ids_pass_through_verbatim() -> None:
    """The client echoes our toolu_ ids; the translation must not rewrite them,
    or upstream assistant/tool messages stop matching."""
    tool_id = "toolu_01abc"
    request = MessageRequest.model_validate({
        "model": "m",
        "max_tokens": 10,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Je vais chercher."},
                    {"type": "tool_use", "id": tool_id, "name": "recherche", "input": {"q": "x"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_id, "content": "42"},
                ],
            },
        ],
    })

    body = translate_to_openai(request)
    assistant, tool = body["messages"]

    assert assistant["tool_calls"][0]["id"] == tool_id
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"q":"x"}'
    assert tool == {"role": "tool", "tool_call_id": tool_id, "content": "42"}


def test_tool_error_is_marked_in_band_and_images_become_vision_payload() -> None:
    request = MessageRequest.model_validate({
        "model": "m",
        "max_tokens": 10,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Regarde :"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "échec", "is_error": True},
                ],
            },
        ],
    })

    body = translate_to_openai(request)
    user, tool = body["messages"]

    assert user["content"] == [
        {"type": "text", "text": "Regarde :"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    assert tool["content"] == "[tool_error] échec"


# ───────────────────────── token estimation ─────────────────────────


def test_token_estimation_is_cjk_aware() -> None:
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("hello") == 2  # ceil(5 * 0.25)
    assert estimate_text_tokens("中文测试") == 4  # 1 token per CJK char


def test_input_tokens_are_coherent_between_messages_and_count_tokens() -> None:
    request = MessageRequest.model_validate(BASIC_REQUEST)

    assert anthropic_input_tokens(request) == estimate_openai_body_tokens(
        translate_to_openai(request)
    )
    assert anthropic_input_tokens(request) > 0


# ───────────────────────── stream translation ─────────────────────────


def _event_names(sse: str) -> list[str]:
    return [
        line[len("event: "):]
        for line in sse.splitlines()
        if line.startswith("event: ")
    ]


def _event_data(sse: str) -> dict[str, list[dict[str, Any]]]:
    """Group SSE payloads by event name, in emission order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    name: str | None = None
    for line in sse.splitlines():
        if line.startswith("event: "):
            name = line[len("event: "):]
        elif line.startswith("data: ") and name is not None:
            grouped.setdefault(name, []).append(json.loads(line[len("data: "):]))
            name = None
    return grouped


def _feed(chunks: list[dict[str, Any]]) -> tuple[str, AnthropicStreamTranslator]:
    translator = AnthropicStreamTranslator(model="m", input_tokens=12)
    sse = translator.start()
    for chunk in chunks:
        for event in translator.feed(chunk):
            sse += event
    for event in translator.finish():
        sse += event
    return sse, translator


def test_stream_text_sequence_follows_anthropic_order() -> None:
    sse, _ = _feed([
        {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "Bon"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "jour"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 3}},
    ])

    assert _event_names(sse) == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    by_event = _event_data(sse)
    start = by_event["message_start"][0]
    assert start["message"]["usage"]["input_tokens"] == 12
    assert start["message"]["usage"]["cache_read_input_tokens"] == 0
    deltas = by_event["content_block_delta"]
    assert [d["delta"]["text"] for d in deltas] == ["Bon", "jour"]
    delta = by_event["message_delta"][0]
    assert delta["delta"]["stop_reason"] == "end_turn"
    assert delta["usage"]["output_tokens"] == 3


def test_stream_tool_use_keeps_stable_ids_and_partial_json_order() -> None:
    sse, translator = _feed([
        {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call-upstream",
                "function": {"name": "recherche", "arguments": ""},
            }]}, "finish_reason": None}],
        },
        {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": "{\"q\":\"x\""},
            }]}, "finish_reason": None}],
        },
        {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": "}"},
            }]}, "finish_reason": "tool_calls"}],
            "usage": {"completion_tokens": 7},
        },
    ])

    assert _event_names(sse) == [
        "message_start",
        "content_block_start",
        # The first (empty) fragment still ticks as a delta, then the payload.
        "content_block_delta",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    by_event = _event_data(sse)
    block = by_event["content_block_start"][0]["content_block"]
    assert block["type"] == "tool_use"
    assert block["name"] == "recherche"
    # The upstream id is hidden from the client; the presented id is ours and
    # stable (it is what the client will echo in tool_result).
    assert block["id"].startswith("toolu_")
    assert block["id"] == translator._tools[0]["id"]
    fragments = [d["delta"]["partial_json"] for d in by_event["content_block_delta"]]
    assert "".join(fragments) == '{"q":"x"}'
    assert by_event["message_delta"][0]["delta"]["stop_reason"] == "tool_use"
    assert by_event["message_delta"][0]["usage"]["output_tokens"] == 7


def test_stream_unnamed_lead_buffers_arguments_until_the_name_arrives() -> None:
    sse, _ = _feed([
        {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"name": "", "arguments": "{\"a\":1}"},
            }]}, "finish_reason": None}],
        },
        {
            "choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"name": "tardif", "arguments": ""},
            }]}, "finish_reason": "stop"}],
        },
    ])

    by_event = _event_data(sse)
    block = by_event["content_block_start"][0]["content_block"]
    assert block["name"] == "tardif"
    fragments = [d["delta"]["partial_json"] for d in by_event["content_block_delta"]]
    # The buffered fragment is flushed before the (empty) current one.
    assert fragments == ["{\"a\":1}", ""]


def test_stop_reason_mapping_handles_length_and_refusal() -> None:
    sse_length, _ = _feed([
        {"choices": [{"delta": {"content": "x"}, "finish_reason": "length"}]},
    ])
    sse_refusal, _ = _feed([
        {"choices": [{"delta": {}, "finish_reason": "content_filter"}]},
    ])

    assert _event_data(sse_length)["message_delta"][0]["delta"]["stop_reason"] == "max_tokens"
    assert _event_data(sse_refusal)["message_delta"][0]["delta"]["stop_reason"] == "refusal"


def test_output_tokens_fall_back_to_estimation_without_usage() -> None:
    sse, _ = _feed([
        {"choices": [{"delta": {"content": "aaaaaaaa"}, "finish_reason": "stop"}]},
    ])

    delta = _event_data(sse)["message_delta"][0]
    assert delta["usage"]["output_tokens"] == 2
    assert delta["delta"]["stop_reason"] == "end_turn"


def test_parse_openai_sse_chunks_skips_comments_and_done() -> None:
    text = (
        "event: comment\ndata: ignored\n\n"
        'data: {"choices": [{"delta": {"content": "a"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    assert _parse_openai_sse_chunks(text) == [
        {"choices": [{"delta": {"content": "a"}}]},
    ]


def test_translate_completion_maps_non_streamed_tool_use() -> None:
    payload = {
        "id": "chatcmpl-1",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Voici.",
                "tool_calls": [{
                    "id": "call-upstream",
                    "function": {"name": "météo", "arguments": '{"ville":"Paris"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"completion_tokens": 9},
    }

    translated = translate_completion(payload, model="m", input_tokens=20)

    assert translated["type"] == "message"
    assert translated["stop_reason"] == "tool_use"
    assert translated["content"][0] == {"type": "text", "text": "Voici."}
    tool_use = translated["content"][1]
    assert tool_use["type"] == "tool_use"
    assert tool_use["name"] == "météo"
    assert tool_use["id"].startswith("toolu_")
    assert tool_use["input"] == {"ville": "Paris"}
    assert translated["usage"]["input_tokens"] == 20
    assert translated["usage"]["output_tokens"] == 9


# ───────────────────────── routes ─────────────────────────


def _patch_auth(monkeypatch: pytest.MonkeyPatch, side_effect: Any = None) -> AsyncMock:
    auth = AsyncMock(return_value=None, side_effect=side_effect)
    monkeypatch.setattr(anthropic_router_module, "_anthropic_api_auth", auth)
    return auth


def _patch_proxy(monkeypatch: pytest.MonkeyPatch, result: Any) -> AsyncMock:
    proxy = AsyncMock(return_value=result)
    monkeypatch.setattr(anthropic_router_module, "call_proxy", proxy)
    return proxy


@pytest.mark.asyncio
async def test_messages_route_returns_anthropic_message(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)
    upstream = JSONResponse(
        content={
            "id": "chatcmpl-9",
            "choices": [{
                "message": {"role": "assistant", "content": "Bonjour"},
                "finish_reason": "stop",
            }],
            "usage": {"completion_tokens": 4},
        },
        headers={"X-Galaris-LLM-Call-Id": "call-123"},
    )
    _patch_proxy(monkeypatch, upstream)

    response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json=BASIC_REQUEST,
    )

    assert response.status_code == 200
    assert response.headers.get("X-Galaris-LLM-Call-Id") == "call-123"
    payload = response.json()
    assert payload["type"] == "message"
    assert payload["stop_reason"] == "end_turn"
    assert payload["content"] == [{"type": "text", "text": "Bonjour"}]
    parsed = MessageRequest.model_validate(BASIC_REQUEST)
    assert payload["usage"]["input_tokens"] == anthropic_input_tokens(parsed)
    assert payload["usage"]["output_tokens"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/llm/anthropic/v1/messages", "/api/profile/anthropic/v1/messages"])
async def test_managed_anthropic_runtime_uses_shared_task_correlation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    task_id = uuid4()
    auth = AsyncMock(return_value=42)
    correlate = AsyncMock(return_value=task_id)
    monkeypatch.setattr(anthropic_router_module, "_anthropic_api_auth", auth)
    monkeypatch.setattr(
        anthropic_router_module,
        "resolve_runtime_task_id",
        correlate,
    )
    upstream = JSONResponse(
        content={
            "choices": [{
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }],
        },
    )
    proxy = _patch_proxy(monkeypatch, upstream)

    response = await client.post(
        path,
        json=BASIC_REQUEST,
    )

    assert response.status_code == 200
    correlate.assert_awaited_once()
    assert correlate.await_args.kwargs["agent_id"] == 42
    assert correlate.await_args.kwargs["messages"] == translate_to_openai(
        MessageRequest.model_validate(BASIC_REQUEST)
    )["messages"]
    assert proxy.await_args.kwargs["task_id"] == task_id


@pytest.mark.asyncio
async def test_messages_and_count_tokens_share_the_same_input_number(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)
    upstream = JSONResponse(
        content={
            "choices": [{
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }],
        },
    )
    _patch_proxy(monkeypatch, upstream)
    messages_response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json=BASIC_REQUEST,
    )
    count_response = await client.post(
        "/api/llm/anthropic/v1/messages/count_tokens",
        json=BASIC_REQUEST,
    )

    assert count_response.status_code == 200
    assert count_response.json()["input_tokens"] == (
        messages_response.json()["usage"]["input_tokens"]
    )


@pytest.mark.asyncio
async def test_stream_route_emits_ordered_events(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)

    async def upstream_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices": [{"delta": {"role": "assistant", "content": "Salut"}}]}\n\n'
        yield (
            b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}],'
            b' "usage": {"completion_tokens": 2}}\n\n'
        )
        yield b"data: [DONE]\n\n"

    _patch_proxy(monkeypatch, StreamingResponse(
        upstream_stream(),
        media_type="text/event-stream",
        headers={"X-Galaris-LLM-Call-Id": "call-42"},
    ))

    response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json={**BASIC_REQUEST, "stream": True},
    )

    assert response.status_code == 200
    assert response.headers.get("X-Galaris-LLM-Call-Id") == "call-42"
    events = [
        line[len("event: "):]
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]
    assert events == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert '"stop_reason":"end_turn"' in response.text


@pytest.mark.asyncio
async def test_upstream_error_becomes_anthropic_envelope(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)
    _patch_proxy(monkeypatch, JSONResponse(
        content={"error": {"message": "provider exploded"}},
        status_code=502,
    ))

    response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json={**BASIC_REQUEST, "stream": True},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "api_error"
    assert payload["error"]["message"] == "provider exploded"


@pytest.mark.asyncio
async def test_auth_error_uses_the_anthropic_envelope(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch, side_effect=HTTPException(
        status_code=401,
        detail="jeton invalide",
        headers={"WWW-Authenticate": "Bearer"},
    ))

    response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json=BASIC_REQUEST,
    )

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    payload = response.json()
    assert payload["error"]["type"] == "authentication_error"
    assert payload["error"]["message"] == "jeton invalide"


@pytest.mark.asyncio
async def test_missing_messages_is_rejected_as_invalid_request(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)

    response = await client.post(
        "/api/llm/anthropic/v1/messages",
        json={"model": "m", "max_tokens": 10, "messages": []},
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_models_route_lists_chat_llms_with_anthropic_shape(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auth(monkeypatch)
    listed = [
        SimpleNamespace(
            code="deepseek-flash",
            label="DeepSeek Flash",
            provider=None,
            context_length=128_000,
        ),
        SimpleNamespace(code="autre", label=None, provider=None, context_length=None),
    ]
    monkeypatch.setattr(
        anthropic_router_module.llm_service,
        "list_llms",
        AsyncMock(return_value=listed),
    )

    response = await client.get("/api/llm/anthropic/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_more"] is False
    assert payload["first_id"] == "deepseek-flash"
    by_id = {model["id"]: model for model in payload["data"]}
    assert by_id["deepseek-flash"]["type"] == "model"
    assert by_id["deepseek-flash"]["display_name"] == "DeepSeek Flash"
    assert by_id["deepseek-flash"]["owned_by"] == "galaris"
    # A label-less LLM falls back to its code.
    assert by_id["autre"]["display_name"] == "autre"


@pytest.mark.asyncio
async def test_count_tokens_uses_the_count_request_shape(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count endpoint must stay usable without max_tokens/stream fields."""
    _patch_auth(monkeypatch)
    count_body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hello hello hello hello"}],
        "tools": [{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
    }

    response = await client.post(
        "/api/llm/anthropic/v1/messages/count_tokens",
        json=count_body,
    )

    assert response.status_code == 200
    assert response.json()["input_tokens"] == anthropic_input_tokens(
        MessageRequest.model_validate(count_body)
    )
    assert response.json()["input_tokens"] > 0
