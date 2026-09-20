from __future__ import annotations

import pytest

from app.dream.mechanisms import task_memory
from app.dream.mechanisms import voice_memory
from app.task.models import Task, TaskStatus


def test_task_memory_prompt_binds_durable_facts_to_exact_human_contact() -> None:
    task = Task(
        label="Message Matrix de Alice",
        objective="Je préfère les comptes rendus mensuels.",
        status=TaskStatus.SUCCESS,
        agent_id=7,
        message_platform="matrix",
        data={
            "sender.user_id": "@alice:example.org",
            "sender.display_name": "Alice Martin",
            "sender_is_ai": False,
        },
    )

    prompt = task_memory._task_prompt(task)  # pyright: ignore[reportPrivateUsage]
    query = task_memory._novelty_query(task)  # pyright: ignore[reportPrivateUsage]

    assert "Current human contact (exact identity)" in prompt
    assert "messaging_id: matrix" in prompt
    assert "user_id: @alice:example.org" in prompt
    assert "display_name: Alice Martin" in prompt
    assert query.startswith(
        "messaging_id: matrix\nuser_id: @alice:example.org"
    )


def test_task_memory_prompt_does_not_attribute_ai_sender_as_human() -> None:
    task = Task(
        label="Peer message",
        objective="Continue the delegated task.",
        status=TaskStatus.SUCCESS,
        agent_id=7,
        message_platform="matrix",
        data={
            "sender.user_id": "@agent:example.org",
            "sender.display_name": "Peer agent",
            "sender_is_ai": True,
        },
    )

    prompt = task_memory._task_prompt(task)  # pyright: ignore[reportPrivateUsage]

    assert "Current human contact" not in prompt


@pytest.mark.asyncio
async def test_capture_setting_disables_task_and_voice_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        task_memory.runtime_settings,
        "MEMORY_CAPTURE_ENABLED",
        False,
    )

    assert not await task_memory.task_memory_mechanism.is_available()
    assert not await voice_memory.voice_memory_mechanism.is_available()
