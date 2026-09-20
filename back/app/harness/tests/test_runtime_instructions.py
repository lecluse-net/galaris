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


class _CountingTestModel(TestModel):
    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        del messages, model_settings, model_request_parameters
        return RequestUsage(input_tokens=1)


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
        ]
    )

    assert isinstance(history[0], ModelRequest)
    human_part = history[0].parts[0]
    assert isinstance(human_part, UserPromptPart)
    assert str(human_part.content).startswith(
        f"[{expected_timestamp} | Nicolas] Voici le rapport"
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
    assert "| Aster]" in agent_part.content
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
    assert part.content == "Réponse précédente"


@pytest.mark.asyncio
async def test_internal_prompt_is_sent_with_existing_message_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _CountingTestModel(call_tools=[])

    async def fake_build_model(*_args: object, **_kwargs: object) -> TestModel:
        return model

    monkeypatch.setattr(runtime, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(runtime, "estimate_cost_from_usage", lambda *_args: 0.0)

    agent = Agent(
        cast(LLM, SimpleNamespace()),
        system_prompt="SYSTEM SENTINEL: conversation_task_submit is available.",
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
