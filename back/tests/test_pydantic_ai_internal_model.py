from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.profiles.openai import OpenAIModelProfile

from app.llm import pydantic_ai_utils
from app.llm.provider_catalog import get_provider_profile
from app.llm.provider_models import LLM, LLMProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(("mime", "wire_type", "audio_format"), [
    ("image/png", "image_url", None),
    ("application/pdf", "file", None),
    ("audio/wav", "input_audio", "wav"),
    ("audio/ogg", "input_audio", "ogg"),
    ("video/mp4", "video_url", None),
])
async def test_multimodal_model_reaches_proxy_with_native_parts(monkeypatch, mime, wire_type, audio_format):
    import base64

    requests = []
    async def proxy(body, **kwargs):
        requests.append(body)
        async def chunks():
            yield 'data: {"id":"native-test","object":"chat.completion.chunk","created":1,"model":"native-model","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            yield "data: [DONE]\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(pydantic_ai_utils, "proxy_chat_completion", proxy)
    llm = LLM(id=1, code="native-test", llm_name="synthetic/native-model", input_image=True,
              input_audio=True, input_video=True, input_file=True,
              provider=LLMProvider(catalog_code="openrouter", provider_type="openai_compatible",
                                   base_url="https://openrouter.ai/api/v1"))
    model = await pydantic_ai_utils.build_model_for_llm(llm, enable_native_media=True)
    result = await model.request([ModelRequest(parts=[UserPromptPart(content=[
        "Inspect this media", BinaryContent(data=b"synthetic-media", media_type=mime),
    ])])], None, ModelRequestParameters())
    assert result.parts[0].content == "ok"
    parts = requests[0]["messages"][0]["content"]
    assert [part["type"] for part in parts] == ["text", wire_type]
    encoded = base64.b64encode(b"synthetic-media").decode()
    if audio_format:
        assert parts[1]["input_audio"] == {"data": encoded, "format": audio_format}
    else:
        assert encoded in json.dumps(parts[1])


def test_native_media_preflight_does_not_count_base64_as_prose():
    def usage(size):
        return pydantic_ai_utils._estimate_request_usage(
            [ModelRequest(parts=[UserPromptPart(content=[
                "Inspect", BinaryContent(data=b"x" * size, media_type="audio/wav"),
            ])])], None, ModelRequestParameters(),
        ).input_tokens
    assert 4096 < usage(1) < 10_000
    assert usage(1_000_000) == usage(1)


@pytest.fixture(autouse=True)
def mocked_gateway_boundary(monkeypatch):
    # These are SDK serialization units with synthetic LLM identities. Durable
    # admission and provider HTTP are exercised together in test_protocol_inference.
    from app.llm import protocol_inference

    async def chat(body, **options):
        return await pydantic_ai_utils.proxy_chat_completion(body, **options)

    async def responses(body, **options):
        return await pydantic_ai_utils.proxy_responses(body, **options)

    monkeypatch.setattr(protocol_inference, "proxy_chat_completion", chat)
    monkeypatch.setattr(protocol_inference, "proxy_responses", responses)


@pytest.mark.asyncio
async def test_chat_sdk_applies_profile_before_internal_transport(monkeypatch) -> None:
    """A SDK profile change must take effect without copying its request builder."""
    requests = []

    async def proxy(body, **kwargs):
        requests.append(body)

        async def chunks():
            yield 'data: {"id":"chat_test","object":"chat.completion.chunk","created":1,"model":"opaque-deployment","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(pydantic_ai_utils, "proxy_chat_completion", proxy)
    model = pydantic_ai_utils.InternalLLMChatModel(
        LLM(id=1, llm_provider_id=1, code="stable", llm_name="opaque-deployment", label="Opaque"),
    )
    # Deliberately opaque name: the profile, not Galaris model-name matching, owns this.
    model.profile.update(OpenAIModelProfile(
        openai_supports_reasoning=True,
        openai_reasoning_enabled_by_default=True,
        openai_chat_supports_max_completion_tokens=True,
    ))
    with pytest.warns(UserWarning, match="Sampling parameters"):
        result = await model.request([], {"temperature": 0.2, "max_tokens": 123}, ModelRequestParameters())
    assert result.parts[0].content == "ok"
    assert "temperature" not in requests[0]
    assert requests[0]["max_completion_tokens"] == 123


@pytest.mark.asyncio
async def test_internal_model_routes_pydantic_ai_requests_through_llm_call_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_proxy_chat_completion(
        body: dict[str, Any],
        *,
        purpose: str | None = None,
        task_id: Any,
        agent_run_id: Any = None,
        conversation_round_id: Any = None,
        agent_id: int | None = None,
        llm_override: LLM | None = None,
        route_executor_model: bool = True,
        reasoning_effort: str | None = None,
        sdk_request: bool = False,
        request_timeout: dict[str, float | None] | None = None,
    ) -> StreamingResponse:
        captured["body"] = body
        captured["task_id"] = task_id
        captured["agent_run_id"] = agent_run_id
        captured["conversation_round_id"] = conversation_round_id
        captured["agent_id"] = agent_id
        captured["llm_override"] = llm_override
        captured["purpose"] = purpose
        captured["route_executor_model"] = route_executor_model
        captured["reasoning_effort"] = reasoning_effort
        captured["sdk_request"] = sdk_request

        async def chunks() -> AsyncIterator[str]:
            yield (
                'data: {"id":"chatcmpl-test","object":"chat.completion.chunk",'
                '"created":1,"model":"provider-model","choices":[{"index":0,'
                '"delta":{"role":"assistant","content":"ok"},'
                '"finish_reason":null}]}\n\n'
            )
            yield (
                'data: {"id":"chatcmpl-test","object":"chat.completion.chunk",'
                '"created":1,"model":"provider-model","choices":[{"index":0,'
                '"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,'
                '"completion_tokens":1,"total_tokens":2}}\n\n'
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(
        pydantic_ai_utils,
        "proxy_chat_completion",
        fake_proxy_chat_completion,
    )
    task_id = uuid4()
    agent_run_id = uuid4()
    conversation_round_id = uuid4()
    llm = LLM(
        id=12,
        llm_provider_id=3,
        code="stable-code",
        llm_name="provider-model",
        label="Provider model",
    )
    model = await pydantic_ai_utils.build_model_for_llm(
        llm,
        task_id=task_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        agent_id=7,
    )

    response = await model.request(
        [],
        {"temperature": 0.2, "max_tokens": 256},
        ModelRequestParameters(),
    )

    assert captured["body"]["model"] == "stable-code"
    assert captured["body"]["stream"] is True
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["max_tokens"] == 256
    assert captured["task_id"] == task_id
    assert captured["agent_run_id"] == agent_run_id
    assert captured["conversation_round_id"] == conversation_round_id
    assert captured["agent_id"] == 7
    assert captured["llm_override"] is llm
    assert captured["purpose"] is None
    assert captured["route_executor_model"] is False
    assert captured["reasoning_effort"] is None
    assert captured["sdk_request"] is True
    assert response.model_name == "provider-model"
    assert response.state == "complete"
    assert len(response.parts) == 1
    assert isinstance(response.parts[0], TextPart)
    assert response.parts[0].content == "ok"
    assert response.usage.input_tokens == 1
    assert response.usage.output_tokens == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429, 503])
async def test_internal_model_preserves_http_error_and_retry_guidance(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    attempts = 0
    async def fake_proxy_chat_completion(
        body: dict[str, Any],
        **kwargs: Any,
    ) -> JSONResponse:
        nonlocal attempts
        attempts += 1
        return JSONResponse(
            {"error": {"message": "Provider temporarily unavailable"}},
            status_code=status, headers={"Retry-After": "17", "X-Request-Id": "provider-request"},
        )

    monkeypatch.setattr(
        pydantic_ai_utils,
        "proxy_chat_completion",
        fake_proxy_chat_completion,
    )
    model = await pydantic_ai_utils.build_model_for_llm(
        LLM(
            id=12,
            llm_provider_id=3,
            code="stable-code",
            llm_name="provider-model",
            label="Provider model",
        )
    )

    with pytest.raises(ModelHTTPError, match="Provider temporarily unavailable") as caught:
        await model.request([], {}, ModelRequestParameters())
    assert caught.value.status_code == status
    assert caught.value.retry_after == 17
    assert caught.value.headers["x-request-id"] == "provider-request"
    assert attempts == 1


def _responses_llm() -> LLM:
    provider = LLMProvider(
        id=3,
        name="OpenAI — ChatGPT",
        catalog_code="openai-codex",
        provider_type="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
    )
    llm = LLM(
        id=12,
        llm_provider_id=3,
        code="stable-sol",
        llm_name="gpt-5.6-sol",
        label="GPT-5.6 Sol",
    )
    llm.provider = provider
    return llm


def _catalog_llm(catalog_code: str, model_name: str) -> LLM:
    profile = get_provider_profile(catalog_code)
    assert profile is not None
    provider = LLMProvider(
        id=3,
        name=profile.display_name,
        catalog_code=profile.code,
        provider_type=profile.provider_type,
        base_url=profile.base_url,
    )
    llm = LLM(
        id=12,
        llm_provider_id=3,
        code=f"test-{catalog_code}",
        llm_name=model_name,
        label=model_name,
    )
    llm.provider = provider
    return llm


@pytest.mark.asyncio
async def test_codex_endpoint_constraints_apply_in_sdk_even_for_opaque_model(monkeypatch, responses_sse) -> None:
    captured = []

    async def proxy(body, **kwargs):
        captured.append(body)
        # This is the SDK boundary, before any compatibility filtering or OAuth bridge.
        assert body["stream"] is True
        assert body["store"] is False
        assert not {"temperature", "top_p", "max_output_tokens"} & body.keys()

        async def chunks():
            terminal = {"id": "resp_opaque", "object": "response", "created_at": 1,
                "status": "completed", "model": "opaque-deployment", "output": [{"id": "msg_opaque",
                "type": "message", "role": "assistant", "status": "completed", "content": [
                    {"type": "output_text", "text": "done", "annotations": []}]}]}
            yield responses_sse(terminal)

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(pydantic_ai_utils, "proxy_responses", proxy)
    model = await pydantic_ai_utils.build_model_for_llm(_catalog_llm("openai-codex", "opaque-deployment"))
    response = await model.request([ModelRequest(parts=[UserPromptPart(content="Work")])],
        {"temperature": 0.2, "top_p": 0.9, "max_tokens": 123, "openai_store": True}, ModelRequestParameters())
    assert response.parts[0].content == "done"
    assert len(captured) == 1


@pytest.mark.parametrize(
    ("catalog_code", "model_name", "expected"),
    [
        ("deepseek", "deepseek-v4-pro", True),
        ("deepseek", "opaque-deployment", True),
        ("openrouter", "openai/gpt-5.6-sol", True),
        ("fireworks", "accounts/fireworks/models/deepseek-v4", True),
        ("groq", "qwen/qwen3.6-27b", True),
        ("huggingface", "openai/gpt-oss-120b:groq", True),
        ("nvidia", "meta/llama-3.1-8b-instruct", True),
        ("perplexity", "openai/gpt-5.6-sol", True),
        ("perplexity", "sonar", True),
        ("xai", "grok-4.6", True),
        ("together", "openai/gpt-oss-120b", False),
    ],
)
def test_native_responses_support_is_declared_by_provider(
    catalog_code: str,
    model_name: str,
    expected: bool,
) -> None:
    assert (
        pydantic_ai_utils.llm_supports_native_responses(
            _catalog_llm(catalog_code, model_name)
        )
        is expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("catalog_code", "model_name"),
    [
        ("openrouter", "openai/gpt-5.6-sol"),
        ("fireworks", "accounts/fireworks/models/deepseek-v4"),
        ("huggingface", "openai/gpt-oss-120b:groq"),
        ("nvidia", "meta/llama-3.1-8b-instruct"),
        ("perplexity", "openai/gpt-5.6-sol"),
    ],
)
async def test_supported_gateway_models_build_native_responses_adapters(
    catalog_code: str,
    model_name: str,
) -> None:
    model = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm(catalog_code, model_name)
    )

    if catalog_code == "perplexity":
        from pydantic_ai.models.fallback import FallbackModel

        assert isinstance(model, FallbackModel)
        assert isinstance(model.models[0], pydantic_ai_utils.InternalLLMResponsesModel)
        assert isinstance(model.models[1], pydantic_ai_utils.InternalLLMChatModel)
    else:
        assert isinstance(model, pydantic_ai_utils.InternalLLMResponsesModel)


@pytest.mark.asyncio
async def test_native_responses_uses_provider_specific_model_profiles() -> None:
    deepseek = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm("deepseek", "deepseek-v4-pro")
    )
    assert isinstance(deepseek, pydantic_ai_utils.InternalLLMResponsesModel)
    assert (
        deepseek.profile["openai_responses_supports_interleaved_function_calls"]
        is False
    )
    assert deepseek.responses_policy.store is None
    assert deepseek.responses_policy.supports_compaction is False

    xai = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm("xai", "grok-4.6")
    )
    assert isinstance(xai, pydantic_ai_utils.InternalLLMResponsesModel)
    assert xai.profile["openai_supports_encrypted_reasoning_content"] is True
    assert xai.responses_policy.store is False
    assert xai.responses_policy.supports_compaction is True

    groq = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm("groq", "qwen/qwen3.6-27b")
    )
    assert isinstance(groq, pydantic_ai_utils.InternalLLMResponsesModel)
    assert groq.profile["supports_thinking"] is True
    assert groq.responses_policy.store is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning_effort", [None, "high", "none"])
@pytest.mark.parametrize(
    ("catalog_code", "model_name"),
    [
        ("openrouter", "deepseek/deepseek-v4-flash-0731"),
        ("deepseek", "deepseek-v4-pro"),
        ("openrouter", "openai/gpt-5.6-sol"),
    ],
)
async def test_task_objective_output_respects_provider_tool_forcing_and_validation(
    monkeypatch, catalog_code, model_name, reasoning_effort, responses_sse,
) -> None:
    from app.conversation.task_objective import _GeneratedTaskFields
    from app.llm import run_structured
    from app.llm.provider_facade import adapt_request_parameters, request_parameter_policy_for
    from app.llm.resource_discovery import provider_connection

    llm = _catalog_llm(catalog_code, model_name)
    policy = request_parameter_policy_for(provider_connection(llm.provider, None), model_name)
    requests = []
    round_id = uuid4()
    objective = "<p>Créer une image de la finale France 98 et la livrer.</p>"

    async def proxy(body, **kwargs):
        # Keep the actual compatibility gate: only the external response is replaced.
        wire = adapt_request_parameters(body, policy, "responses")
        requests.append(wire)
        assert kwargs["conversation_round_id"] == round_id
        tool = next(tool for tool in wire["tools"] if tool["type"] == "function")
        terminal = {
            "id": f"resp-{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": model_name,
            "output": [{
                "id": f"fc-{len(requests)}", "type": "function_call",
                "call_id": f"call-{len(requests)}", "name": tool["name"],
                "arguments": json.dumps({
                    "label": "Finale France 98",
                    "objective": "" if len(requests) == 1 else objective,
                }), "status": "completed",
            }],
        }
        async def chunks():
            yield responses_sse(terminal)
        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(pydantic_ai_utils, "proxy_responses", proxy)
    result = await run_structured(
        llm=llm, output_type=_GeneratedTaskFields,
        prompt="Créer une image de la finale France 98.",
        system_prompt="Return the Task label and HTML objective.",
        task_id=None, agent_id=None, conversation_round_id=round_id,
        temperature=0.0, request_limit=2, output_retries=1,
        reasoning_effort_override=reasoning_effort,
    )

    assert result.output.objective == objective
    assert result.output.label == "Finale France 98"
    assert len(requests) == 2  # Invalid output still requires a corrected model response.
    expected_choice = (
        "auto" if catalog_code == "deepseek" and reasoning_effort != "none" else "required"
    )
    assert all(request["tool_choice"] == expected_choice for request in requests)
    if reasoning_effort is not None:
        assert all(request["reasoning"]["effort"] == reasoning_effort for request in requests)


@pytest.mark.asyncio
async def test_native_xai_preserves_supported_temperature_with_reasoning(monkeypatch, responses_sse) -> None:
    captured = []

    async def proxy(body, **kwargs):
        captured.append(body)
        terminal = {"id": "resp_xai", "object": "response", "created_at": 1,
            "status": "completed", "model": "grok-4.6", "output": [{"id": "msg_xai",
            "type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": "done", "annotations": []}]}]}
        async def chunks():
            yield responses_sse(terminal)
        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr(pydantic_ai_utils, "proxy_responses", proxy)
    model = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm("xai", "grok-4.6"), reasoning_effort="high",
    )
    await model.request([ModelRequest(parts=[UserPromptPart(content="Work")])],
        {"temperature": 0.2}, ModelRequestParameters())
    assert captured[0]["temperature"] == 0.2
    assert captured[0]["reasoning"]["effort"] == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_code,empty_terminal", [
    ("openai-api", False), ("openai-codex", False), ("openai-codex", True),
])
async def test_native_responses_applies_policy_and_replays_reasoning_identity(
    monkeypatch: pytest.MonkeyPatch,
    catalog_code: str,
    empty_terminal: bool,
    responses_sse,
) -> None:
    captured: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def fake_proxy_responses(
        body: dict[str, Any],
        **kwargs: Any,
    ) -> JSONResponse | StreamingResponse:
        captured.append((body, kwargs))

        def reply(terminal: dict[str, Any]) -> JSONResponse | StreamingResponse:
            if not body.get("stream"):
                return JSONResponse(terminal)

            async def chunks() -> AsyncIterator[str]:
                yield responses_sse(terminal, empty_terminal=empty_terminal)

            return StreamingResponse(chunks(), media_type="text/event-stream")

        if len(captured) == 1:
            return reply(
                {
                    "id": "resp-1",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "id": "rs-1",
                            "type": "reasoning",
                            "summary": [
                                {
                                    "type": "summary_text",
                                    "text": "Need the authoritative lookup.",
                                }
                            ],
                            "encrypted_content": "opaque-reasoning",
                        },
                        {
                            "id": "fc-1",
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "lookup",
                            "arguments": "{\"query\":\"answer\"}",
                            "status": "completed",
                        },
                    ],
                    "parallel_tool_calls": True,
                    "reasoning": {"effort": "high", "summary": "auto"},
                    "store": False,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 4,
                        "total_tokens": 14,
                    },
                }
            )
        return reply(
            {
                "id": "resp-2",
                "object": "response",
                "created_at": 2,
                "status": "completed",
                "model": "gpt-5.6-sol",
                "output": [
                    {
                        "id": "msg-2",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "The answer is 42.",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "reasoning": {"effort": "high", "summary": "auto"},
                "store": False,
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "total_tokens": 25,
                },
            }
        )

    monkeypatch.setattr(pydantic_ai_utils, "proxy_responses", fake_proxy_responses)
    model = await pydantic_ai_utils.build_model_for_llm(
        _catalog_llm(catalog_code, "gpt-5.6-sol"),
        task_id=uuid4(),
        agent_run_id=uuid4(),
        agent_id=7,
        reasoning_effort="high",
    )
    assert isinstance(model, pydantic_ai_utils.InternalLLMResponsesModel)
    settings: dict[str, Any] = {"temperature": 0.0}
    request = ModelRequest(parts=[UserPromptPart(content="Find the answer")])
    first_response = await model.request(
        [request],
        settings,
        ModelRequestParameters(),
    )
    assert isinstance(first_response.parts[0], ThinkingPart)
    assert first_response.parts[0].signature == "opaque-reasoning"
    assert isinstance(first_response.parts[1], ToolCallPart)
    assert first_response.parts[1].tool_call_id == "call-1"
    assert first_response.usage.input_tokens == 10
    assert first_response.usage.output_tokens == 4
    first_body, _first_kwargs = captured[0]
    assert first_body["store"] is False
    assert first_body["reasoning"] == {
        "effort": "high",
        "context": "all_turns",
        "summary": "auto",
    }
    assert "reasoning.encrypted_content" in first_body["include"]

    tool_return = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="lookup",
                tool_call_id="call-1",
                content={"answer": 42},
            )
        ]
    )
    final_response = await model.request(
        [request, first_response, tool_return],
        settings,
        ModelRequestParameters(),
    )

    assert isinstance(final_response.parts[0], TextPart)
    assert final_response.parts[0].content == "The answer is 42."
    assert final_response.usage.input_tokens == 20
    assert final_response.usage.output_tokens == 5
    second_body, second_kwargs = captured[1]
    assert second_body["store"] is False
    assert second_body["reasoning"] == {
        "effort": "high",
        "context": "all_turns",
        "summary": "auto",
    }
    reasoning = next(
        item for item in second_body["input"] if item.get("type") == "reasoning"
    )
    assert reasoning["id"] == "rs-1"
    assert reasoning["encrypted_content"] == "opaque-reasoning"
    function_call = next(
        item for item in second_body["input"] if item.get("type") == "function_call"
    )
    assert function_call["id"] == "fc-1"
    assert function_call["call_id"] == "call-1"
    function_output = next(
        item
        for item in second_body["input"]
        if item.get("type") == "function_call_output"
    )
    assert function_output["call_id"] == "call-1"
    assert second_kwargs["operation"] == "create"
    assert second_kwargs["model_code"] == f"test-{catalog_code}"
    assert second_kwargs["route_executor_model"] is False


@pytest.mark.asyncio
async def test_native_responses_compaction_uses_compact_proxy_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_proxy_responses(
        body: dict[str, Any],
        **kwargs: Any,
    ) -> JSONResponse:
        captured["body"] = body
        captured["kwargs"] = kwargs
        return JSONResponse(
            {
                "id": "cmp-response-1",
                "object": "response.compaction",
                "created_at": 1,
                "output": [
                    {
                        "id": "cmp-1",
                        "type": "compaction",
                        "encrypted_content": "opaque-compaction",
                    }
                ],
                "usage": {
                    "input_tokens": 30,
                    "output_tokens": 8,
                    "total_tokens": 38,
                },
            }
        )

    monkeypatch.setattr(pydantic_ai_utils, "proxy_responses", fake_proxy_responses)
    model = pydantic_ai_utils.InternalLLMResponsesModel(_responses_llm())
    request = ModelRequest(parts=[UserPromptPart(content="Long history")])
    compacted = await model.compact_messages(
        ModelRequestContext(
            model=model,
            messages=[request],
            model_settings={"openai_store": False},
            model_request_parameters=ModelRequestParameters(),
        ),
        instructions="Keep goals and completed effects.",
    )

    assert captured["kwargs"]["operation"] == "compact"
    assert captured["body"]["instructions"] == "Keep goals and completed effects."
    assert "reasoning" not in captured["body"]
    assert compacted.provider_details == {"compaction": True}
    assert compacted.parts[0].provider_details is not None
    assert (
        compacted.parts[0].provider_details["encrypted_content"]
        == "opaque-compaction"
    )
    assert (
        compacted.parts[0].provider_details[
            "pydantic_ai_standing_prompt_planted"
        ]
        is True
    )
