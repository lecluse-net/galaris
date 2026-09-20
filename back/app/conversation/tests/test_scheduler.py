from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent import AIMessage, AIResult
from app.conversation import (
    ConversationOutcome,
    ConversationRuntimeEvent,
    ConversationTurn,
    controller,
    facade,
    scheduler,
    service,
)


@pytest.mark.asyncio
async def test_superseded_preparation_completes_through_the_freshness_barrier(monkeypatch):
    from app.conversation import ConversationSuperseded

    turn = ConversationTurn(room_id=uuid4(), round_id=uuid4(), agent_id=1,
        language="fr", objective="Old request", messages=())
    @asynccontextmanager
    async def session():
        yield
    events = []
    async def publish(room_id, event):
        events.append(event)
    async def run(current):
        await current.publish_progress(AIMessage(type="tool", tool_name="read", content="source read"))
        raise ConversationSuperseded
    complete = AsyncMock(return_value="SUPERSEDED")
    fail = AsyncMock()
    monkeypatch.setattr(scheduler, "get_db_session", session)
    monkeypatch.setattr(service, "build_turn", AsyncMock(return_value=turn))
    monkeypatch.setattr(service, "complete_round", complete)
    monkeypatch.setattr(service, "fail_round", fail)
    monkeypatch.setattr(facade, "publish_runtime_event", publish)
    monkeypatch.setattr(facade, "publish_round_activity", AsyncMock())
    monkeypatch.setattr(controller, "run", run)
    await scheduler._execute_action(turn.round_id, uuid4())
    outcome = complete.await_args.args[1]
    assert outcome.metadata["interrupted"] is True
    assert outcome.text == ""
    assert outcome.execution_result.messages[0].content == "source read"
    fail.assert_not_awaited()
    assert events[-1].kind == "finished" and events[-1].success is False


@pytest.mark.asyncio
async def test_round_stream_starts_before_the_controller_and_finishes_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    room_id = uuid4()
    topic_id = uuid4()
    events: list[ConversationRuntimeEvent] = []

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def build_turn(_round_id: object, *, lease_token: object) -> ConversationTurn:
        return ConversationTurn(
            room_id=room_id,
            round_id=round_id,
            agent_id=1,
            language="fr",
            objective="Salut",
            messages=(),
            topic_id=topic_id,
        )

    async def publish_runtime_event(
        current_room_id: object,
        event: ConversationRuntimeEvent,
    ) -> None:
        assert current_room_id == room_id
        events.append(event)

    async def run(turn: ConversationTurn) -> ConversationOutcome:
        assert [event.kind for event in events] == ["started"]
        assert turn.publish_progress is not None
        await turn.publish_progress(
            AIMessage(type="text", content="Bon")
        )
        await turn.publish_progress(AIMessage(type="text", content="jour"))
        return ConversationOutcome(
            text="Bonjour",
            execution_result=AIResult(prompt="Salut", result="Bonjour"),
        )

    monkeypatch.setattr(scheduler, "get_db_session", fake_db_session)
    monkeypatch.setattr(service, "build_turn", build_turn)
    monkeypatch.setattr(service, "complete_round", AsyncMock(return_value="SUCCEEDED"))
    monkeypatch.setattr(service, "fail_round", AsyncMock())
    monkeypatch.setattr(facade, "publish_runtime_event", publish_runtime_event)
    monkeypatch.setattr(facade, "publish_round_activity", AsyncMock())
    monkeypatch.setattr(controller, "run", run)

    await scheduler._execute_action(round_id, uuid4())  # pyright: ignore[reportPrivateUsage]

    assert [event.kind for event in events] == ["started", "message", "message", "finished"]
    assert [event.sequence for event in events] == [0, 1, 2, 3]
    assert {event.topic_id for event in events} == {topic_id}
    assert [event.message.content for event in events[1:3] if event.message] == [
        "Bon",
        "jour",
    ]
    assert events[-1].success is True
    assert events[-1].result is not None
    assert events[-1].result.result == "Bonjour"
    assert [message.content for message in events[-1].result.messages] == ["Bonjour"]
    completed_outcome = service.complete_round.await_args.args[1]
    assert completed_outcome.execution_result is not None
    assert [
        message.content for message in completed_outcome.execution_result.messages
    ] == ["Bonjour"]


@pytest.mark.asyncio
async def test_tool_only_effect_persists_its_visible_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    room_id = uuid4()
    completed = AsyncMock(return_value="SUCCEEDED")

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def build_turn(_round_id: object, *, lease_token: object) -> ConversationTurn:
        return ConversationTurn(
            room_id=room_id,
            round_id=round_id,
            agent_id=1,
            language="fr",
            objective="@task dis bonjour",
            messages=(),
        )

    async def run(_turn: ConversationTurn) -> ConversationOutcome:
        acknowledgement = (
            "J’ai créé et lancé la tâche « Dire bonjour ». "
            "Je publierai son résultat ici dès qu’elle sera terminée."
        )
        return ConversationOutcome(
            text=acknowledgement,
            effect_started=True,
            execution_result=AIResult(
                prompt="@task dis bonjour",
                result=acknowledgement,
                messages=[
                    AIMessage(
                        type="tool",
                        tool_name="conversation_task_submit",
                        content="Task admission completed",
                    )
                ],
            ),
        )

    monkeypatch.setattr(scheduler, "get_db_session", fake_db_session)
    monkeypatch.setattr(service, "build_turn", build_turn)
    monkeypatch.setattr(service, "complete_round", completed)
    monkeypatch.setattr(service, "fail_round", AsyncMock())
    monkeypatch.setattr(facade, "publish_runtime_event", AsyncMock())
    monkeypatch.setattr(facade, "publish_round_activity", AsyncMock())
    monkeypatch.setattr(controller, "run", run)

    await scheduler._execute_action(round_id, uuid4())  # pyright: ignore[reportPrivateUsage]

    completed_outcome = completed.await_args.args[1]
    assert completed_outcome.execution_result is not None
    assert [
        (message.type, message.content)
        for message in completed_outcome.execution_result.messages
    ] == [
        ("tool", "Task admission completed"),
        (
            "text",
            "J’ai créé et lancé la tâche « Dire bonjour ». "
            "Je publierai son résultat ici dès qu’elle sera terminée.",
        ),
    ]


def test_conversation_live_contract_rejects_parallel_message_payloads() -> None:
    round_id = uuid4()
    with pytest.raises(ValidationError, match="must contain an AIMessage"):
        ConversationRuntimeEvent(
            round_id=round_id,
            kind="message",
            sequence=1,
        )
    with pytest.raises(ValidationError, match="Only a snapshot or finished conversation"):
        ConversationRuntimeEvent(
            round_id=round_id,
            kind="started",
            sequence=0,
            result=AIResult(prompt="Test", result="Interdit"),
        )


@pytest.mark.asyncio
async def test_cancel_round_cancels_a_local_worker_and_waits_for_cleanup() -> None:
    round_id = uuid4()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_worker() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker = asyncio.create_task(blocked_worker())
    scheduler._running[round_id] = worker  # pyright: ignore[reportPrivateUsage]
    try:
        await started.wait()

        assert await scheduler.cancel_round(round_id)

        assert worker.cancelled()
        assert cancelled.is_set()
    finally:
        scheduler._running.pop(round_id, None)  # pyright: ignore[reportPrivateUsage]
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_round_action_is_cancelled_immediately_after_lease_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_action(_round_id: object, _lease_token: object) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def lose_lease(_round_id: object, _lease_token: object) -> None:
        await started.wait()
        raise scheduler.ConversationLeaseLostError("lease lost")

    monkeypatch.setattr(scheduler, "_execute_action", blocked_action)
    monkeypatch.setattr(scheduler, "_heartbeat_round", lose_lease)

    await scheduler._execute(uuid4(), uuid4())  # pyright: ignore[reportPrivateUsage]

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_round_can_finish_after_a_long_model_and_search_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A five-minute inference must still leave time to consume search results."""
    completed = asyncio.Event()
    original_timeout = asyncio.timeout
    scale = 1_000

    async def action(_round_id: object, _lease_token: object) -> None:
        await asyncio.sleep(350 / scale)
        completed.set()

    async def heartbeat(_round_id: object, _lease_token: object) -> None:
        await asyncio.Event().wait()

    def scaled_timeout(delay: float | None) -> asyncio.Timeout:
        return original_timeout(None if delay is None else delay / scale)

    fail_timed_out_round = AsyncMock()
    monkeypatch.setattr(scheduler, "_execute_action", action)
    monkeypatch.setattr(scheduler, "_heartbeat_round", heartbeat)
    monkeypatch.setattr(scheduler, "_fail_timed_out_round", fail_timed_out_round)
    monkeypatch.setattr(scheduler.asyncio, "timeout", scaled_timeout)

    await scheduler._execute(uuid4(), uuid4())  # pyright: ignore[reportPrivateUsage]

    assert completed.is_set()
    fail_timed_out_round.assert_not_awaited()


@pytest.mark.asyncio
async def test_round_action_timeout_cancels_runtime_and_releases_durable_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = asyncio.Event()

    async def blocked(_round_id: object, *_args: object) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    fail_timed_out_round = AsyncMock()
    monkeypatch.setattr(scheduler, "_execute_action", blocked)
    monkeypatch.setattr(scheduler, "_heartbeat_round", blocked)
    monkeypatch.setattr(scheduler, "_fail_timed_out_round", fail_timed_out_round)
    monkeypatch.setattr(scheduler, "_ACTION_TIMEOUT_SECONDS", 0.01)
    round_id = uuid4()
    lease_token = uuid4()

    await scheduler._execute(  # pyright: ignore[reportPrivateUsage]
        round_id, lease_token
    )

    assert cancelled.is_set()
    fail_timed_out_round.assert_awaited_once_with(round_id, lease_token)
