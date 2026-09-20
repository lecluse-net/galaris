from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import janus
from app.agent.janus import _agent_code_from_history, _messages_for_agent
from app.agent.openai_schemas import ChatCompletionRequest, Message


def _contents(messages: list[Message]) -> list[tuple[str, str]]:
    return [(message.role, str(message.content or "")) for message in messages]


def test_messages_for_agent_strips_janus_selection_history() -> None:
    messages = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Welcome to **Galaris**!\n\nI'm Janus.\n\nWhat's your name?"),
        Message(role="user", content="Nicolas"),
        Message(role="assistant", content="Nice to meet you, **Nicolas**!\n\nHere are the available agents:"),
        Message(role="user", content="@alice Can you review this folder?"),
    ]

    delegated = _messages_for_agent(
        messages,
        agent_code="alice",
        current_content_after_code="Can you review this folder?",
    )

    assert _contents(delegated) == [("user", "Can you review this folder?")]


def test_messages_for_agent_skips_switch_only_connection_message() -> None:
    messages = [
        Message(role="user", content="@alice"),
        Message(role="assistant", content="Connected to **Alice** (@alice). Say hi!"),
        Message(role="user", content="Hi, can you help me?"),
    ]

    delegated = _messages_for_agent(
        messages,
        agent_code="alice",
        current_content_after_code="Hi, can you help me?",
    )

    assert _contents(delegated) == [("user", "Hi, can you help me?")]


def test_messages_for_agent_keeps_agent_conversation_after_switch() -> None:
    messages = [
        Message(role="user", content="Nicolas"),
        Message(role="assistant", content="Here are the available agents:"),
        Message(role="user", content="@alice First question"),
        Message(role="assistant", content="Agent response"),
        Message(role="user", content="What comes next?"),
    ]

    delegated = _messages_for_agent(
        messages,
        agent_code="alice",
        current_content_after_code="What comes next?",
    )

    assert _contents(delegated) == [
        ("user", "First question"),
        ("assistant", "Agent response"),
        ("user", "What comes next?"),
    ]


def test_agent_code_is_recovered_from_the_latest_explicit_history_selection() -> None:
    messages = [
        Message(role="user", content="@alice First question"),
        Message(role="assistant", content="First response"),
        Message(role="user", content="@bob Second question"),
        Message(role="assistant", content="Second response"),
        Message(role="user", content="Continue"),
    ]

    assert _agent_code_from_history(messages) == "bob"


@pytest.mark.asyncio
async def test_janus_lists_agents_without_asking_for_the_user_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    janus._sessions.clear()
    monkeypatch.setattr(janus, "current_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(
        janus,
        "_get_agents",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    code="alice",
                    first_name="Alice",
                    last_name="Martin",
                    job_title="Analyst",
                )
            ]
        ),
    )

    response = await janus.handle(
        ChatCompletionRequest(
            model="janus",
            messages=[Message(role="user", content="Hello")],
        ),
        {},
        "new-session",
    )

    content = str(response.choices[0].message.content or "")
    assert "What's your name?" not in content
    assert "Who would you like to talk to?" in content
    assert "@alice" in content


@pytest.mark.asyncio
async def test_janus_recovers_routing_when_client_loses_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    janus._sessions.clear()
    agent = SimpleNamespace(
        code="alice",
        first_name="Alice",
        last_name="Martin",
        job_title="Analyst",
    )
    find_agent = AsyncMock(return_value=(agent, []))
    forwarded = AsyncMock(return_value=object())
    monkeypatch.setattr(janus, "current_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(janus, "_find_agent", find_agent)
    monkeypatch.setattr(
        "app.agent.openai_service.run_local_chat_completion",
        forwarded,
    )

    request = ChatCompletionRequest(
        model="janus",
        messages=[
            Message(role="user", content="@alice"),
            Message(role="assistant", content="Connected to **Alice Martin** (@alice). Say hi!"),
            Message(role="user", content="Can you continue?"),
        ],
    )
    expected = await janus.handle(request, {}, "replacement-session-id")

    assert expected is forwarded.return_value
    delegated_request = forwarded.await_args.args[1]
    assert _contents(delegated_request.messages) == [("user", "Can you continue?")]


@pytest.mark.asyncio
async def test_janus_preserves_and_authorizes_process_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    janus._sessions.clear()
    process_run_id = uuid4()
    agent = SimpleNamespace(
        code="alice",
        first_name="Alice",
        last_name="Martin",
        job_title="Analyst",
    )
    forwarded = AsyncMock(return_value=object())
    record = AsyncMock()
    monkeypatch.setattr(janus, "current_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(janus, "_find_agent", AsyncMock(return_value=(agent, [])))
    monkeypatch.setattr(
        janus,
        "current_management_scope",
        AsyncMock(return_value=SimpleNamespace(agent_ids=frozenset({7}))),
    )
    monkeypatch.setattr(
        "app.process.process_service.record_inbound_call",
        record,
    )
    monkeypatch.setattr(
        "app.agent.openai_service.run_local_chat_completion",
        forwarded,
    )
    raw_body = {
        "galaris_process_run_id": str(process_run_id),
        "galaris_correlation_id": "process-correlation",
    }

    result = await janus.handle(
        ChatCompletionRequest(
            model="janus",
            messages=[Message(role="user", content="@alice Run this process step")],
        ),
        raw_body,
        "process-session",
    )

    assert result is forwarded.return_value
    assert raw_body["galaris_process_run_id"] == str(process_run_id)
    record.assert_awaited_once_with(
        process_run_id,
        kind="agent",
        target_code="alice",
        metadata={"correlation_id": "process-correlation"},
        agent_ids=frozenset({7}),
    )
