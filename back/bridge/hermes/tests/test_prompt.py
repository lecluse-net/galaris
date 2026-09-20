from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.agent import AgentSnapshot
from app.task import TaskMessage
from app.task.models import Task, TaskStatus
from app.tools.agent_registry import AgentToolAdvertisement
from bridge.hermes import prompt
from bridge.hermes.prompt import build_message_context


def _task(**kw) -> Task:
    defaults = dict(
        id=uuid4(),
        label="Hermes prompt",
        objective="Current request",
        status=TaskStatus.CREATE,
        data=None,
        messages=None,
        message_group_id="room-1",
        message_platform="talk",
        parent_id=None,
    )
    defaults.update(kw)
    return Task(**defaults)


def _message(message_id: str, text: str) -> TaskMessage:
    return TaskMessage(
        external_message_id=message_id,
        text=text,
        sender_external_id="alice",
        sender_display_name="Alice",
    )


def test_message_context_limits_hermes_history_to_five_previous_messages():
    messages = [_message(f"m{i}", f"Message {i:02d}") for i in range(8)]
    task = _task(
        data={
            "id": "current",
            "text": "Current request",
            "sender.display_name": "Alice",
        },
        messages=messages,
    )

    context = build_message_context(task)

    assert "<history>" in context
    assert "<current_message>" not in context
    assert "Message 00" not in context
    assert "Message 01" not in context
    assert "Message 02" not in context
    assert "Message 03" in context
    assert "Message 07" in context


@pytest.mark.asyncio
async def test_context_instructions_advertise_only_effectively_available_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advertisement = AgentToolAdvertisement(
        text=(
            "Only the following native Galaris MCP functions are available in this run.\n\n"
            "- `galaris`: `process_list`, `process_get`, `process_start`"
        ),
        tool_names=frozenset({"process_list", "process_get", "process_start"}),
    )
    tool_builder = AsyncMock(return_value=advertisement)
    process_builder = AsyncMock(return_value="## Business processes\n\n- invoice-recording")
    monkeypatch.setattr(prompt, "build_agent_tool_advertisement", tool_builder)
    monkeypatch.setattr(prompt, "build_agent_process_advertisement", process_builder)
    monkeypatch.setattr(prompt, "_has_galaris_skill", AsyncMock(return_value=True))
    monkeypatch.setattr(
        prompt.params_service,
        "get",
        AsyncMock(return_value="FINAL EXECUTOR SUFFIX"),
    )

    agent = AgentSnapshot(
        id=7,
        code="ada",
        first_name="Ada",
        last_name="Lovelace",
        driver_code="hermes",
        gender="F",
        job_title="Analyste",
        personality="Rigoureuse et signe ses travaux Ada.",
        job_description="Produire des analyses vérifiables.",
    )
    instructions = await prompt.build_context_instructions(
        agent,
        run_context_instructions="Current run constraint.",
    )

    assert "**Your name:** **Ada Lovelace**" in instructions
    assert "Rigoureuse et signe ses travaux Ada." in instructions
    assert "Produire des analyses vérifiables." in instructions
    assert "authorship or signature preferences" in instructions
    assert "process_list" in instructions
    assert "invoice-recording" in instructions
    assert "assigned `galaris` skill" in instructions
    assert "image_generate" not in instructions
    assert "messenger_room_send_message" not in instructions
    assert "task_stop" not in instructions
    assert instructions.index("Current run constraint.") < instructions.index(
        "FINAL EXECUTOR SUFFIX"
    )
    assert instructions.endswith("FINAL EXECUTOR SUFFIX")
    tool_builder.assert_awaited_once_with(agent.id, runtime="hermes")
    process_builder.assert_awaited_once_with(agent.id, advertisement.tool_names)
