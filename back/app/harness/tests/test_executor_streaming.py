from __future__ import annotations

import asyncio
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
async def test_voice_conversation_releases_context_locks_and_keeps_audio_trace(
    monkeypatch: pytest.MonkeyPatch,
    committed_database: object,
) -> None:
    from app.harness import conversation
    from app.agent import Agent, Title, authorization_policy
    from app.memory.models import MemoryItem, MemoryUsage
    from core.database import get_db_session
    from core.user import UserModel
    from sqlalchemy import select, text

    async with get_db_session() as db:
        user = UserModel(email=f"voice-{uuid4().hex}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic voice", gender="X")
        db.add_all([user, title])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"voice-{uuid4().hex}",
                      first_name="Synthetic", last_name="Caller")
        db.add(agent)
        await db.flush()
        memory = MemoryItem(owner_agent_id=agent.id, resource_id=str(uuid4()),
                            content="Synthetic context", title="Synthetic memory",
                            content_hash="0" * 64)
        db.add(memory)
        await db.flush()
        agent_id, memory_id = agent.id, memory.id

    request = _request(
        taskless=True,
        conversation_round_id=uuid4(),
        conversation_only=True,
    )
    request = replace(
        request,
        agent=replace(request.agent, id=agent_id),
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
            # Native tools authorize on another connection. Context usage holds a
            # foreign-key lock on this agent until preparation has committed.
            async with get_db_session() as db:
                await db.execute(text("SET LOCAL lock_timeout = '100ms'"))
                policy = await authorization_policy(agent_id, lock=True)
                assert policy.manager_user_id == user.id
                assert await db.scalar(select(MemoryUsage.id).where(
                    MemoryUsage.agent_id == agent_id, MemoryUsage.item_id == memory_id,
                )) is not None
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
    monkeypatch.setattr("app.conversation.facade.active_work_snapshot",
                        AsyncMock(return_value=request.task_data["linked_work"]))
    from app.skill import learning_service, skill_service

    assigned_skills = AsyncMock(return_value=["galaris-lab"])
    monkeypatch.setattr(
        skill_service, "get_assigned_codes", assigned_skills,
    )
    monkeypatch.setattr(learning_service, "list_injectable", AsyncMock(return_value=[]))

    async with get_db_session() as db:
        db.add(MemoryUsage(item_id=memory_id, agent_id=agent_id, access_kind="context"))
        await db.flush()
        events = [
            event async for event in conversation.stream_voice_conversation(request)
        ]

    assert captured["purpose"] == LLMCallPurpose.CONVERSATION_AUDIO
    assigned_skills.assert_any_await(request.agent_id)  # Resource reads revalidate after construction.
    assert [capability.id for capability in captured["capabilities"]] == ["galaris-lab"]
    assert captured["capabilities"][0].defer_loading is True
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
    assert events[-1].result.success, events[-1].result.metadata.get("error")
    assert events[-1].result.result == "Spoken answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tool", [True, False])
@pytest.mark.parametrize("argument_stream", [True, False])
@pytest.mark.parametrize("stream_kind", ["text", "thinking"])
@pytest.mark.parametrize("fragment_count", [9, 2048])
async def test_internal_stream_publishes_initial_and_tool_progress(
    monkeypatch: pytest.MonkeyPatch,
    use_tool: bool,
    argument_stream: bool,
    stream_kind: str,
    fragment_count: int,
) -> None:
    progress = AsyncMock()
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(executor, "time", SimpleNamespace(time=executor.time.time, monotonic=lambda: clock.now))
    streamed_content = "Searching" if fragment_count == 9 else "a" * fragment_count
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
                # Reasoning arrives as tool-typed fragments, but is not an executed tool.
                kind = "tool" if stream_kind == "thinking" else "text"
                tool_name = "thinking" if stream_kind == "thinking" else None
                for fragment in streamed_content:
                    yield AIMessage(type=kind, tool_name=tool_name, content=fragment,
                        stream_id="content", stream_complete=False)
                yield AIMessage(type=kind, tool_name=tool_name, content="",
                    stream_id="content", stream_complete=True)
                if argument_stream:
                    clock.now += executor._PROGRESS_PERSIST_INTERVAL + 0.01
                    await _kwargs["on_model_activity"]()
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

    assert progress.await_count == (3 if use_tool else 2) + int(argument_stream)
    initial = progress.await_args_list[0].args[0]
    assert isinstance(initial, ExecutionResult)
    assert initial.messages == []
    assert initial.metadata["runtime_status"] == "running"
    completed = progress.await_args_list[1].args[0]
    assert completed.messages[0].content == streamed_content
    assert completed.messages[0].stream_complete is True
    assert [event.message.stream_complete for event in events[:fragment_count + 1]] == [False] * fragment_count + [True]

    observed_tools = ["thinking"] if stream_kind == "thinking" else []
    message_type = "tool" if stream_kind == "thinking" else "text"

    if argument_stream:
        during_arguments = progress.await_args_list[2].args[0]
        assert during_arguments.tools_used == observed_tools
        assert [message.type for message in during_arguments.messages] == [message_type]
    if use_tool:
        after_tool = progress.await_args_list[-1].args[0]
        assert isinstance(after_tool, ExecutionResult)
        assert after_tool.tools_used == [*observed_tools, "search_web"]
        assert [message.type for message in after_tool.messages] == [message_type, "tool"]
    assert events[-1].kind == "result"
    assert events[-1].result is not None
    assert events[-1].result.success is True
    assert events[-1].result.tools_used == [*observed_tools, *(["search_web"] if use_tool else [])]
    assert events[-1].result.result == (streamed_content if stream_kind == "text" else "")


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


@pytest.fixture(autouse=True)
def generic_catalogue_only_in_stream_units(monkeypatch):
    # These stream units already replace generic and learned catalogue persistence.
    from unittest.mock import AsyncMock
    from app.skill import interface
    monkeypatch.setattr(interface, 'personal_packages', AsyncMock(return_value=[]))
