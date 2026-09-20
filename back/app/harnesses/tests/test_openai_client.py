from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.agent import (
    AgentRunEnvelopeV1,
    AgentRunIdentityV1,
    AgentUsage,
    ResolvedExecutionTarget,
)
from app.harnesses.openai_client import OpenAIHarnessClient
from app.harnesses.openai_client import _messages


def _envelope() -> AgentRunEnvelopeV1:
    return AgentRunEnvelopeV1(
        identity=AgentRunIdentityV1(run_id=uuid4()),
        target=ResolvedExecutionTarget(
            provider_code="openai_messages",
            target_ref=f"harness:{uuid4()}",
            metadata={"model": "agent-model"},
        ),
        agent_id=1,
        agent_code="alice",
        effort="standard",
        objective="Do the work",
        model_id=2,
        model_code="fallback",
        model_name="fallback",
    )


def _passthrough_envelope() -> AgentRunEnvelopeV1:
    envelope = _envelope().model_copy(
        update={
            "reasoning_effort": "xhigh",
            "identity": AgentRunIdentityV1(
                task_id=uuid4(),
                run_id=uuid4(),
            ),
        }
    )
    return envelope.model_copy(
        update={
            "target": envelope.target.model_copy(
                update={
                    "metadata": {
                        "model": "agent-model",
                        "model_passthrough": True,
                        "galaris_extensions": True,
                    }
                }
            )
        }
    )


def test_network_harness_receives_server_owned_messaging_context() -> None:
    envelope = _envelope().model_copy(
        update={
            "messaging_context": {
                "platform": "internal",
                "room_id": "chat:direct:1:1",
                "user_id": "user:1",
                "user_name": "Nicolas",
            }
        }
    )

    final_user = _messages(envelope)[-1]["content"]

    assert final_user.endswith("Do the work")
    assert "<galaris_message_context>" in final_user
    assert '"room_id":"chat:direct:1:1"' in final_user
    assert '"user_name":"Nicolas"' in final_user


@pytest.mark.asyncio
async def test_client_discovers_models_and_never_follows_a_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"data": [{"id": "one"}, {"id": "two"}]})

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    assert await client.list_models() == ["one", "two"]


@pytest.mark.asyncio
async def test_client_reads_final_assistant_message_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode()
        assert '"model":"agent-model"' in payload
        assert "X-Galaris-Agent-Run-Id" not in request.headers
        return httpx.Response(
            200,
            json={
                "id": "completion-1",
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    result = await client.run(_envelope())

    assert result.result == "Done"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 2
    assert result.usage.token_quality == "exact"


@pytest.mark.asyncio
async def test_client_reads_optional_non_streamed_galaris_telemetry() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        assert _request.headers["X-Galaris-Reasoning-Effort"] == "xhigh"
        assert _request.headers["X-Galaris-Task-Id"]
        assert "X-Galaris-Conversation-Round-Id" not in _request.headers
        return httpx.Response(
            200,
            json={
                "id": "completion-2",
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "galaris": {
                    "success": True,
                    "execution_time": 1.25,
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 3,
                        "tool_calls": 1,
                        "cost": 0.02,
                        "token_quality": "partial",
                        "cost_quality": "estimated",
                    },
                    "messages": [
                        {
                            "type": "tool",
                            "content": "read",
                            "tool_name": "Read",
                            "success": True,
                        }
                    ],
                    "metadata": {"runtime_run_id": "session-2"},
                },
            },
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    result = await client.run(_passthrough_envelope())

    assert [message.type for message in result.messages] == ["tool", "text"]
    assert result.usage.tool_calls == 1
    assert result.cost == pytest.approx(0.02)
    assert result.execution_time == pytest.approx(1.25)
    assert result.metadata["runtime_run_id"] == "session-2"


@pytest.mark.asyncio
async def test_client_prefers_persisted_gateway_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _passthrough_envelope()
    envelope = envelope.model_copy(
        update={
            "target": envelope.target.model_copy(
                update={
                    "provider_code": "claude_agent",
                }
            )
        }
    )
    aggregate = AsyncMock(
        return_value=(
            AgentUsage(
                input_tokens=80,
                output_tokens=12,
                cache_read_tokens=20,
                reasoning_tokens=4,
                requests=3,
                tool_calls=2,
                cost=0.07,
                token_quality="exact",
                cost_quality="exact",
            ),
            0.09,
        )
    )
    monkeypatch.setattr("app.agent.aggregate_llm_run_usage", aggregate)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "completion-accounted",
                "choices": [{"message": {"role": "assistant", "content": "Done"}}],
                "galaris": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cost": 0.01,
                        "token_quality": "partial",
                        "cost_quality": "estimated",
                    }
                },
            },
        )

    result = await OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    ).run(envelope)

    aggregate.assert_awaited_once_with(
        envelope.identity.run_id,
        agent_id=envelope.agent_id,
    )
    assert result.usage.input_tokens == 80
    assert result.usage.requests == 3
    assert result.cost == pytest.approx(0.07)
    assert result.usage.cost_quality == "exact"
    assert result.metadata["usage_source"] == "galaris_llm_calls"
    assert result.metadata["inference_cost"] == pytest.approx(0.09)


@pytest.mark.asyncio
async def test_client_streams_deltas_then_exactly_one_terminal_result() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_envelope())]

    assert [event.kind for event in events] == ["message", "message", "result"]
    assert events[-1].result is not None
    assert events[-1].result.result == "Hello"


@pytest.mark.asyncio
async def test_client_refuses_unresolved_tool_calls() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "call-1"}],
                    }
                }]
            },
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="unresolved tool_calls"):
        await client.run(_envelope())


@pytest.mark.asyncio
async def test_client_propagates_a_streaming_harness_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                'data: {"error":"deepseek_harness_failed","detail":"runtime stopped"}\n\n'
                'data: [DONE]\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="runtime stopped"):
        _ = [event async for event in client.stream(_envelope())]


@pytest.mark.asyncio
async def test_client_passes_galaris_model_and_correlation_headers() -> None:
    envelope = _passthrough_envelope()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode()
        assert '"model":"fallback"' in payload
        assert request.headers["X-Galaris-Agent-Run-Id"] == str(
            envelope.identity.run_id
        )
        assert request.headers["X-Galaris-Model-Code"] == "fallback"
        assert request.headers["X-Galaris-Model-Name"] == "fallback"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Done"}}]
            },
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    assert (await client.run(envelope)).result == "Done"


@pytest.mark.asyncio
async def test_client_streams_optional_semantic_tool_events_and_terminal_usage() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'data: {"choices":[{"delta":{"content":"Done"}}]}\n\n'
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","content":"ok","tool_name":"Read",'
            '"tool_arguments":{"file_path":"README.md"},"tool_result":{"bytes":12},'
            '"execution_time":0.2,"success":true}\n\n'
            'event: galaris.agent-result/v1\n'
            'data: {"success":true,"execution_time":1.5,'
            '"usage":{"input_tokens":10,"output_tokens":2,"requests":2,'
            '"tool_calls":1,"cost":0.01,"token_quality":"partial",'
            '"cost_quality":"estimated"},'
            '"metadata":{"runtime_run_id":"session-1"}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_passthrough_envelope())]

    assert [event.kind for event in events] == ["message", "message", "result"]
    assert events[1].message is not None
    assert events[1].message.tool_name == "Read"
    assert events[-1].result is not None
    assert events[-1].result.usage.tool_calls == 1
    assert events[-1].result.cost == pytest.approx(0.01)
    assert events[-1].result.metadata["runtime_run_id"] == "session-1"


@pytest.mark.asyncio
async def test_client_preserves_semantic_thinking_before_the_final_text() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"thinking",'
            '"content":"Inspecting the contracts.","success":true}\n\n'
            'data: {"choices":[{"delta":{"content":"Done"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_passthrough_envelope())]

    assert [event.kind for event in events] == ["message", "message", "result"]
    result = events[-1].result
    assert result is not None
    assert [
        (message.type, message.tool_name, message.content)
        for message in result.messages
    ] == [
        ("tool", "thinking", "Inspecting the contracts."),
        ("text", None, "Done"),
    ]


@pytest.mark.asyncio
async def test_client_keeps_every_live_thinking_block_in_terminal_result() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"thinking",'
            '"content":"Première réflexion.","success":true}\n\n'
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"thinking",'
            '"content":"Deuxième réflexion.","success":true}\n\n'
            'event: galaris.agent-result/v1\n'
            'data: {"success":true,"result":"Réponse finale."}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_passthrough_envelope())]

    live = [event.message for event in events if event.message is not None]
    result = events[-1].result
    assert result is not None
    assert [message.content for message in live] == [
        "Première réflexion.",
        "Deuxième réflexion.",
    ]
    assert [message.content for message in result.messages] == [
        "Première réflexion.",
        "Deuxième réflexion.",
        "Réponse finale.",
    ]


@pytest.mark.asyncio
async def test_client_coalesces_live_fragments_in_the_terminal_trace() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"thinking",'
            '"stream_id":"codex:reasoning:r1:0","content":"Inspection ",'
            '"success":true}\n\n'
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"thinking",'
            '"stream_id":"codex:reasoning:r1:0","content":"des contrats.",'
            '"success":true}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_passthrough_envelope())]

    live = [event.message for event in events if event.message is not None]
    result = events[-1].result
    assert result is not None
    assert [message.content for message in live] == ["Inspection ", "des contrats."]
    assert [message.content for message in result.messages] == [
        "Inspection des contrats."
    ]


@pytest.mark.asyncio
async def test_client_uses_runtime_terminal_text_instead_of_streamed_progress() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        content = (
            'data: {"choices":[{"delta":{"content":"Inspecting."}}]}\n\n'
            'event: galaris.agent-message/v1\n'
            'data: {"type":"tool","tool_name":"Read",'
            '"content":"README loaded","success":true}\n\n'
            'data: {"choices":[{"delta":{"content":"Done."}}]}\n\n'
            'event: galaris.agent-result/v1\n'
            'data: {"success":true,"result":"Done."}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
        )

    client = OpenAIHarnessClient(
        base_url="https://harness.test/v1",
        token=None,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in client.stream(_passthrough_envelope())]

    assert [event.kind for event in events] == [
        "message",
        "message",
        "message",
        "result",
    ]
    result = events[-1].result
    assert result is not None
    assert result.result == "Done."
    assert [(message.type, message.content) for message in result.messages] == [
        ("tool", "README loaded"),
        ("text", "Done."),
    ]
