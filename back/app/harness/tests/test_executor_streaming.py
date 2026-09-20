from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

from app.agent.contracts import (
    AIMessage,
    AgentEvent,
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunRequest,
    AgentSnapshot,
    DispatchResult,
    ExecutionResult,
    ResolvedModel,
)
from app.agent import executor_service
from app.harness import executor
from app.llm import LLMCallPurpose


def _request(
    *,
    taskless: bool,
    conversation_round_id: object | None = None,
    conversation_only: bool = False,
) -> AgentRunRequest:
    return AgentRunRequest(
        run_id=uuid4(),
        task_id=None if taskless else uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Find the answer",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        task_data={
            "language": "en",
            **({"conversation_only": True} if conversation_only else {}),
            **(
                {"conversation_round_id": str(conversation_round_id)}
                if conversation_round_id is not None
                else {}
            ),
        },
    )


def test_taskless_voice_correlation_does_not_promote_run_to_task() -> None:
    conversation_round_id = uuid4()
    request = _request(taskless=True, conversation_round_id=conversation_round_id)

    task_id, agent_run_id, correlated_round_id = executor._correlation_ids(
        request
    )

    assert task_id is None
    assert agent_run_id == request.run_id
    assert correlated_round_id == conversation_round_id


def test_task_correlation_preserves_both_task_and_run() -> None:
    request = _request(taskless=False)

    task_id, agent_run_id, conversation_round_id = executor._correlation_ids(request)

    assert task_id == request.task_id
    assert agent_run_id == request.run_id
    assert conversation_round_id is None


@pytest.mark.asyncio
async def test_conversation_only_request_uses_dedicated_voice_conversation_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.harness import conversation

    request = _request(
        taskless=True,
        conversation_round_id=uuid4(),
        conversation_only=True,
    )
    terminal = ExecutionResult(prompt=request.objective, result="Spoken answer")

    async def dedicated_stream(received: AgentRunRequest):
        assert received is request
        yield AgentEvent.from_result(terminal)

    monkeypatch.setattr(conversation, "stream_voice_conversation", dedicated_stream)

    events = [event async for event in executor.stream(request)]

    assert len(events) == 1
    assert events[0].result == terminal


@pytest.mark.asyncio
async def test_voice_conversation_runtime_is_traced_as_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.harness import conversation

    request = _request(
        taskless=True,
        conversation_round_id=uuid4(),
        conversation_only=True,
    )
    request = replace(
        request,
        task_data={
            **request.task_data,
            "linked_work": (
                {
                    "task_id": "voice-task",
                    "revision": 2,
                    "label": "Voice work",
                    "objective": "Keep the same projection",
                    "operational_state": "QUEUED",
                    "amendable": True,
                },
            ),
        },
    )
    captured: dict[str, object] = {}

    class FakeRuntime:
        system_prompt = "Voice prompt"
        messages: list[AIMessage] = []
        cost = 0.0
        error = ""

        async def run(self, *_args: object, **_kwargs: object) -> AsyncIterator[AIMessage]:
            yield AIMessage(type="text", content="Spoken answer")

    async def fake_create_agent(**kwargs: object) -> FakeRuntime:
        captured.update(kwargs)
        return FakeRuntime()

    monkeypatch.setattr(
        conversation.llm_service,
        "get_llm",
        AsyncMock(return_value=SimpleNamespace(id=7, llm_name="fast")),
    )
    monkeypatch.setattr(
        conversation,
        "build_conversation_toolset",
        AsyncMock(return_value=object()),
    )
    tool_advertisement = AsyncMock(
        return_value=SimpleNamespace(text="", tool_names=frozenset())
    )
    monkeypatch.setattr(
        conversation,
        "build_agent_tool_advertisement",
        tool_advertisement,
    )
    monkeypatch.setattr(
        conversation,
        "build_agent_process_advertisement",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(conversation.params_service, "get", AsyncMock(return_value=""))
    monkeypatch.setattr(
        conversation.params_service,
        "get_or_default",
        AsyncMock(return_value="Use tools for actions; answer directly otherwise."),
    )
    monkeypatch.setattr(conversation, "create_agent", fake_create_agent)

    events = [
        event async for event in conversation.stream_voice_conversation(request)
    ]

    assert captured["purpose"] == LLMCallPurpose.CONVERSATION_AUDIO
    assert "task=galaris://task/voice-task" in str(captured["system_prompt"])
    tool_advertisement.assert_awaited_once_with(
        request.agent_id,
        runtime="internal",
        conversation_only=True,
        include_task_only_tools=True,
        resources={"conversation_turn": ANY},
    )
    turn = tool_advertisement.await_args.kwargs["resources"]["conversation_turn"]
    assert turn.origin == "voice"
    assert str(turn.round_id) == request.task_data["conversation_round_id"]
    assert turn.linked_work == request.task_data["linked_work"]
    assert events[-1].result is not None
    assert events[-1].result.result == "Spoken answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tool", [True, False])
async def test_internal_stream_publishes_initial_and_tool_progress(
    monkeypatch: pytest.MonkeyPatch,
    use_tool: bool,
) -> None:
    progress = AsyncMock()
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Find the answer",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        task_data={"language": "en"},
        dispatch_result=DispatchResult.model_validate({
            "prompt": "Find the answer",
            "decision": {"route": "EXEC", "requires_action": True},
        }),
        control=AgentRunControl(save_progress=progress),
    )

    class FakeRuntime:
        budget_exhausted = False

        def run(self, **_kwargs: object) -> AsyncIterator[AIMessage]:
            async def messages() -> AsyncIterator[AIMessage]:
                yield AIMessage(type="text", content="Searching", stream_id="text", stream_complete=False)
                yield AIMessage(type="text", content="", stream_id="text", stream_complete=True)
                if not use_tool:
                    return
                yield AIMessage(
                    type="tool",
                    tool_name="search_web",
                    tool_arguments={"query": "answer"},
                    content="Found it",
                )

            return messages()

    monkeypatch.setattr(
        executor_service,
        "build_task_prompt",
        AsyncMock(return_value="Find the answer"),
    )
    monkeypatch.setattr(
        executor,
        "build_tool_context_instructions",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        executor,
        "_build_agent_executor",
        AsyncMock(
            return_value=SimpleNamespace(
                agent=FakeRuntime(),
                system_prompt="System",
            )
        ),
    )
    from app import console

    monkeypatch.setattr(console, "resolve_ssh_connection", AsyncMock(return_value=None))

    events = [event async for event in executor.stream(request)]

    assert progress.await_count == (3 if use_tool else 2)
    initial = progress.await_args_list[0].args[0]
    assert isinstance(initial, ExecutionResult)
    assert initial.messages == []
    assert initial.metadata["runtime_status"] == "running"
    completed = progress.await_args_list[1].args[0]
    assert completed.messages[0].content == "Searching"
    assert completed.messages[0].stream_complete is True
    assert [event.message.stream_complete for event in events[:2]] == [False, True]

    if use_tool:
        after_tool = progress.await_args_list[2].args[0]
        assert isinstance(after_tool, ExecutionResult)
        assert after_tool.tools_used == ["search_web"]
        assert [message.type for message in after_tool.messages] == ["text", "tool"]
    assert events[-1].kind == "result"
    assert events[-1].result is not None
    assert events[-1].result.success is True
    assert events[-1].result.tools_used == (["search_web"] if use_tool else [])
    assert events[-1].result.result == "Searching"


@pytest.mark.asyncio
async def test_internal_runtime_never_falls_back_to_terminal_messenger_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Implement the fix",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        messenger_connection_id=9,
        message_platform="nextcloud_talk",
        message_group_id="room-1",
        task_data={"language": "en"},
    )

    class FakeRuntime:
        budget_exhausted = False

        def run(self, **_kwargs: object) -> AsyncIterator[AIMessage]:
            async def messages() -> AsyncIterator[AIMessage]:
                yield AIMessage(
                    type="tool",
                    tool_name="messenger_room_send_message",
                    tool_arguments={
                        "room_id": "room-1",
                        "message": "I am starting.",
                    },
                    content="Message sent.",
                )
                yield AIMessage(type="text", content="The fix is complete and pushed.")

            return messages()

    messenger = SimpleNamespace(
        send_to_room=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(
        executor_service,
        "build_task_prompt",
        AsyncMock(return_value="Implement the fix"),
    )
    monkeypatch.setattr(
        executor,
        "build_tool_context_instructions",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        executor,
        "_build_agent_executor",
        AsyncMock(
            return_value=SimpleNamespace(
                agent=FakeRuntime(),
                system_prompt="System",
            )
        ),
    )

    from app import console, messenger as messenger_module

    monkeypatch.setattr(
        messenger_module,
        "resolve_task_messaging",
        AsyncMock(return_value=(messenger, "galaris-bot")),
    )
    monkeypatch.setattr(console, "resolve_ssh_connection", AsyncMock(return_value=None))

    events = [event async for event in executor.stream(request)]

    messenger.send_to_room.assert_not_awaited()
    terminal = events[-1].result
    assert terminal is not None
    assert terminal.result == "The fix is complete and pushed."
    assert terminal.tools_used == ["messenger_room_send_message"]

@pytest.mark.asyncio
async def test_exact_explicit_task_message_suppresses_only_terminal_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_text = "The fix is complete and pushed."
    request = AgentRunRequest(
        run_id=uuid4(),
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=3,
            code="alice",
            first_name="Alice",
            last_name="Martin",
            driver_code="internal",
        ),
        driver_code="internal",
        effort="standard",
        objective="Implement the fix",
        model=ResolvedModel(
            id=7,
            code="fast",
            model_name="provider/model",
            label="Fast",
            requested_effort="standard",
        ),
        messenger_connection_id=9,
        message_platform="nextcloud_talk",
        message_group_id="room-1",
        task_data={"language": "en"},
    )

    class FakeRuntime:
        budget_exhausted = False

        def run(self, **_kwargs: object) -> AsyncIterator[AIMessage]:
            async def messages() -> AsyncIterator[AIMessage]:
                yield AIMessage(
                    type="tool",
                    tool_name="messenger_room_send_message",
                    tool_arguments={"room_id": "room-1", "message": final_text},
                    content="Message sent.",
                )
                yield AIMessage(type="text", content=final_text)

            return messages()

    messenger = SimpleNamespace(send_to_room=AsyncMock())
    monkeypatch.setattr(
        executor_service,
        "build_task_prompt",
        AsyncMock(return_value="Implement the fix"),
    )
    monkeypatch.setattr(
        executor,
        "build_tool_context_instructions",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        executor,
        "_build_agent_executor",
        AsyncMock(
            return_value=SimpleNamespace(
                agent=FakeRuntime(),
                system_prompt="System",
            )
        ),
    )

    from app import console, messenger as messenger_module

    monkeypatch.setattr(
        messenger_module,
        "resolve_task_messaging",
        AsyncMock(return_value=(messenger, "galaris-bot")),
    )
    monkeypatch.setattr(console, "resolve_ssh_connection", AsyncMock(return_value=None))

    events = [event async for event in executor.stream(request)]

    messenger.send_to_room.assert_not_awaited()
    terminal = events[-1].result
    assert terminal is not None
    assert terminal.result == final_text
    assert terminal.tools_used == ["messenger_room_send_message"]
