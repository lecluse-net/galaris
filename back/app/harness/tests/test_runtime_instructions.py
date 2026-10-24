from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from app.harness import runtime
from app.harness.runtime import Agent
from app.llm import LLM
from app.task import TaskMessage
from app.task import TaskMessageAttachment
from tests.conftest import responses_sse  # noqa: F401


class _CountingTestModel(TestModel):
    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        del messages, model_settings, model_request_parameters
        return RequestUsage(input_tokens=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_process_evidence_reaches_provider_payload_before_and_after_launch(monkeypatch, responses_sse, protocol):
    """Inspect serialized provider requests, beyond the SDK's history projection."""
    import json
    from fastapi.responses import StreamingResponse
    from pydantic_ai.capabilities import Hooks
    from pydantic_ai.profiles.openai import openai_model_profile
    from app.harness.conversation import _process_launch_evidence
    from app.llm.pydantic_ai_utils import InternalLLMChatModel, InternalLLMResponsesModel
    from app.llm.provider_facade import ProviderResponsesPolicy

    requests = []
    launched = []
    run_id = str(uuid4())

    async def proxy(body, **kwargs):
        requests.append(body)
        first = len(requests) == 1

        async def chunks():
            if protocol == "responses":
                item = ({"id": "fc_synthetic", "type": "function_call", "call_id": "synthetic_call",
                    "name": "conversation_process_start", "arguments": '{"workflow_id":"synthetic"}', "status": "completed"}
                    if first else {"id": "msg_synthetic", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "Admitted.", "annotations": []}]})
                terminal = {"id": f"resp_synthetic_{len(requests)}", "object": "response", "created_at": 1,
                    "status": "completed", "model": "opaque", "output": [item],
                    "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}}
                yield responses_sse(terminal)
                return
            delta = ({"tool_calls": [{"index": 0, "id": "synthetic_call", "type": "function",
                "function": {"name": "conversation_process_start", "arguments": '{"workflow_id":"synthetic"}'}}]}
                if first else {"content": "Admitted."})
            payload = {"id": f"chat_synthetic_{len(requests)}", "object": "chat.completion.chunk", "created": 1,
                "model": "opaque", "choices": [{"index": 0, "delta": delta,
                    "finish_reason": "tool_calls" if first else "stop"}]}
            yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    monkeypatch.setattr("app.llm.pydantic_ai_utils.proxy_chat_completion", proxy)
    monkeypatch.setattr("app.llm.pydantic_ai_utils.proxy_responses", proxy)
    llm = cast(LLM, SimpleNamespace(code="synthetic", llm_name="gpt-4o", provider=SimpleNamespace(
        id=None, name="Synthetic provider", catalog_code=None, provider_type="openai",
        base_url="https://synthetic.invalid", configuration={},
    )))
    model = (InternalLLMChatModel(llm) if protocol == "chat" else InternalLLMResponsesModel(llm,
        responses_policy=ProviderResponsesPolicy(model_profile=openai_model_profile)))

    async def build_model(*args, **kwargs):
        return model

    monkeypatch.setattr(runtime, "build_model_for_llm", build_model)
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)

    async def conversation_process_start(workflow_id: str) -> dict[str, str]:
        launched.append(workflow_id)
        return {"run_id": run_id, "status": "queued"}

    agent = Agent(llm, system_prompt="Synthetic governed policy.", real_time=True,
        tools=[conversation_process_start], capabilities=[Hooks(before_model_request=_process_launch_evidence)])
    await agent.init()
    output = [message async for message in agent.run("Relaunch the synthetic process.", [
        TaskMessage(text="It was launched earlier.", sender_is_ai=True, sender_agent_id=7)])]
    assert not agent.error, agent.error
    assert output and launched == ["synthetic"]
    assert len(requests) == 2
    for index, body in enumerate(requests):
        instructions = (body.get("instructions", "") if protocol == "responses" else "\n".join(
            message["content"] for message in body["messages"] if message["role"] == "system"))
        assert "Synthetic governed policy." in instructions
        assert instructions.count("# Current turn execution evidence") == 1
        assert ("No successful Process launch receipt" if index == 0 else run_id) in instructions
        assert "conversation_process_start" in str(body["tools"])


def test_reply_now_closes_unexecuted_tools_and_preserves_confirmed_results() -> None:
    from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
    from app.harness.runtime import _response_only_history
    response = ModelResponse(parts=[
        ToolCallPart("read_report", "{}", tool_call_id="read"),
        ToolCallPart("send_report", "{}", tool_call_id="send"),
    ])
    confirmed = ToolReturnPart("read_report", {"content": "Verified synthetic content"}, tool_call_id="read")
    request = ModelRequest(parts=[confirmed])
    closed = _response_only_history([response, request])
    assert len(closed) == 2
    assert request.parts == [confirmed]
    returns = closed[-1].parts
    assert returns[0] == confirmed
    assert returns[1].tool_call_id == "send"
    assert returns[1].content["status"] == "not_executed"


def test_pydantic_history_keeps_file_only_message_reference() -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    room_id = "0d9fa1e7-584f-4b47-ab89-9e0b48effb95"
    file_id = "7ea95d47-1859-41da-a5eb-d6a836f25376"
    message = TaskMessage(
        room_id=room_id,
        room_external_id="!room:test",
        tool_code="matrix-primary",
        attachments=[
            TaskMessageAttachment(
                id=file_id,
                name="rapport.pdf",
            )
        ],
    )
    assert message.attachments
    assert message.attachments[0].uri == f"matrix-primary://!room:test/{file_id}"
    history = runtime._convert_message_history_to_pydantic(  # pyright: ignore[reportPrivateUsage]
        [message]
    )

    assert len(history) == 1
    assert isinstance(history[0], ModelRequest)
    part = history[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert "<galaris_message_context>" not in str(part.content)
    assert f"matrix-primary://!room:test/{file_id}" in str(part.content)


def test_pydantic_history_keeps_compact_context_with_each_message() -> None:
    from datetime import datetime, timezone

    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    posted_at = 1_700_000_000
    expected_timestamp = (
        datetime.fromtimestamp(posted_at, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="minutes")
    )
    file_id = uuid4()
    history = runtime._convert_message_history_to_pydantic(  # pyright: ignore[reportPrivateUsage]
        [
            TaskMessage(
                sender_external_id="nicolas",
                sender_display_name="Nicolas",
                timestamp=posted_at,
                text="Voici le rapport",
                tool_code="nextcloud",
                room_external_id="talk-room",
                attachments=[
                    TaskMessageAttachment(id=file_id, name="rapport.pdf")
                ],
            ),
            TaskMessage(
                sender_external_id="aster",
                sender_display_name="Aster",
                sender_agent_id=7,
                sender_is_ai=True,
                timestamp=posted_at + 60,
                text="Je l'ai annoté.",
            ),
        ], self_agent_id=7,
    )

    assert isinstance(history[0], ModelRequest)
    human_part = history[0].parts[0]
    assert isinstance(human_part, UserPromptPart)
    assert str(human_part.content).startswith(
        f"[{expected_timestamp} | Nicolas (id:nicolas) | human] Voici le rapport"
    )
    assert "<galaris_message_context>" not in str(human_part.content)
    assert "<conversation_history_metadata>" not in str(human_part.content)
    assert f"nextcloud://talk-room/{file_id}" in str(human_part.content)
    assert history[0].metadata["sender"] == {
        "user_id": None,
        "external_id": "nicolas",
        "nickname": "Nicolas",
        "kind": "human",
    }
    assert history[0].timestamp == datetime.fromtimestamp(
        posted_at, tz=timezone.utc
    )

    assert isinstance(history[1], ModelResponse)
    agent_part = history[1].parts[0]
    assert isinstance(agent_part, TextPart)
    assert f"[{expected_timestamp[:11]}" in agent_part.content
    assert "Aster" in agent_part.content and "agent:7" in agent_part.content
    assert "<galaris_message_context>" not in agent_part.content
    assert agent_part.content.endswith("Je l'ai annoté.")


def test_pydantic_history_context_uses_runtime_self_identity() -> None:
    from pydantic_ai.messages import ModelResponse, TextPart

    history = runtime._convert_message_history_to_pydantic(  # pyright: ignore[reportPrivateUsage]
        [
            TaskMessage(
                sender_external_id="agent-account",
                sender_display_name="Aster",
                text="Réponse précédente",
            )
        ],
        self_id="agent-account",
    )

    assert len(history) == 1
    assert isinstance(history[0], ModelResponse)
    part = history[0].parts[0]
    assert isinstance(part, TextPart)
    assert part.content.endswith("Réponse précédente")
    assert "agent-account" in part.content and "| AI]" in part.content


@pytest.mark.asyncio
@pytest.mark.parametrize("response_only", [False, True])
async def test_internal_prompt_is_sent_with_existing_message_history(
    monkeypatch: pytest.MonkeyPatch,
    response_only: bool,
) -> None:
    model = _CountingTestModel(call_tools=[])

    async def fake_build_model(*_args: object, **_kwargs: object) -> TestModel:
        return model

    monkeypatch.setattr(runtime, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)

    def forbidden_tool() -> str:
        raise AssertionError("Reply now must not execute tools")

    agent = Agent(
        cast(LLM, SimpleNamespace()),
        system_prompt="SYSTEM SENTINEL: conversation_task_submit is available.",
        response_only=response_only,
        tools=[forbidden_tool] if response_only else [],
    )
    await agent.init()

    history = [
        TaskMessage(
            external_message_id="previous-message",
            sender_external_id="human",
            sender_display_name="Nicolas",
            text="Message précédent",
        )
    ]
    output = [message async for message in agent.run("Nouveau message", history)]

    instruction_parts = model.last_model_request_parameters.instruction_parts
    assert [part.content for part in instruction_parts] == [
        "SYSTEM SENTINEL: conversation_task_submit is available."
    ]
    assert output
    if response_only:
        assert model.last_model_request_parameters.function_tools == []
