from __future__ import annotations

from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import executor_service
from app.agent.contracts import (
    AgentRunRequest,
    AgentSnapshot,
    ResolvedModel,
)


@pytest.mark.asyncio
async def test_executor_prompt_prefers_current_user_language(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.user.user_service.get_current_user",
        AsyncMock(return_value=SimpleNamespace(language="zh")),
    )
    prompt = await executor_service.build_task_prompt(_request(voice_call=False))

    assert '"language": "zh"' in prompt


def _request(
    *,
    voice_call: bool,
    taskless: bool = False,
    parent_task_id: object | None = None,
) -> AgentRunRequest:
    conversation_round_id = uuid4()
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=None if taskless else uuid4(),
        agent=AgentSnapshot(
            id=10,
            code="lyra",
            first_name="Lyra",
            last_name="Test",
            driver_code="hermes",
        ),
        driver_code="hermes",
        effort="standard",
        objective="Dis bonjour",
        model=ResolvedModel(
            id=16,
            code="voice",
            model_name="provider/model",
            label="Voice",
            requested_effort="standard",
        ),
        message_platform="voice:nextcloud_talk" if voice_call else "nextcloud_talk",
        message_group_id="room-1",
        parent_task_id=parent_task_id,
        task_data={
            "language": "fr",
            **({"voice_call": True} if voice_call else {}),
            **({"conversation_round_id": str(conversation_round_id)} if taskless else {}),
        },
        messaging_context={
            "platform": "voice:nextcloud_talk" if voice_call else "nextcloud_talk",
            "room_id": "room-1",
        },
    )


@pytest.mark.asyncio
async def test_live_voice_prompt_does_not_require_a_second_messenger_reply() -> None:
    prompt = await executor_service.build_task_prompt(
        _request(voice_call=True)
    )

    assert "# Voice Conversation" in prompt
    assert "# Reply Contract" not in prompt
    assert "do not send the same reply" in prompt
    assert "voice_call_stop tool is mandatory" in prompt
    assert "never merely say or role-play" in prompt


@pytest.mark.asyncio
async def test_messenger_prompt_keeps_explicit_tool_delivery_contract() -> None:
    request = _request(voice_call=False)
    prompt = await executor_service.build_task_prompt(request)

    assert "# Voice Conversation" not in prompt
    assert "# Reply Contract" in prompt
    assert f'"task_uri": "galaris://task/{request.task_id}"' in prompt
    assert '"task_id":' not in prompt


@pytest.mark.asyncio
async def test_conversation_task_prompt_delegates_reply_and_files_to_controller() -> None:
    request = _request(voice_call=False)
    request.task_data["origin"] = "conversation"

    prompt = await executor_service.build_task_prompt(request)

    assert "conversation controller publishes it" in prompt
    assert "cite the exact canonical URI" in prompt
    assert "Do not call a Messenger tool merely" in prompt


@pytest.mark.asyncio
async def test_taskless_voice_prompt_exposes_run_and_turn_but_no_task() -> None:
    request = _request(
        voice_call=True,
        taskless=True,
    )

    prompt = await executor_service.build_task_prompt(request)

    assert f'"run_id": "{request.run_id}"' in prompt
    assert (
        f'"conversation_round_id": "{request.task_data["conversation_round_id"]}"'
        in prompt
    )
    assert '"task_id":' not in prompt
    assert '"task_uri":' not in prompt


@pytest.mark.asyncio
async def test_plan_leaf_prompt_does_not_publish_a_user_facing_reply() -> None:
    prompt = await executor_service.build_task_prompt(
        _request(voice_call=False, parent_task_id=uuid4())
    )

    assert "# Reply Contract" not in prompt
