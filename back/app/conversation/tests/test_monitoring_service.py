from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AIResult
from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation import (
    inspection_service,
    management_service,
    monitoring_service,
    scheduler,
)
from app.conversation.contracts import ConversationOutcome, ConversationTurn
from app.conversation.models import ConversationRound, ConversationRoundAttempt, ConversationTaskLink
from app.conversation.service import admit_message, claim_next_round, complete_round, fail_round
from app.llm import LLMCall
from app.messenger import Message, MessengerUser, Room
from app.tools.models import Tool
from app.topic import Topic
from core.authorize import Privileges


@pytest.mark.asyncio
async def test_admission_timings_are_durable_shared_with_round_and_not_rewritten_on_redelivery(db, monkeypatch):
    from app.conversation import mcp
    from app.task import task_startup_timings

    agent, connection, room, _sender = await _scope(db)
    round_ = ConversationRound(room_id=room.id, status="RUNNING", language="fr")
    db.add(round_)
    await db.flush()
    turn = ConversationTurn(
        room_id=room.id, round_id=round_.id, agent_id=agent.id, language="fr",
        objective="Génère une image.", messages=(),
        messaging_context={"connection_id": connection.id, "room_id": str(room.id), "platform": "telegram"},
    )
    generate = AsyncMock(return_value=("Image", "<p>Générer une image.</p>", 0.0))
    monkeypatch.setattr(mcp, "generate_task_fields", generate)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())
    monkeypatch.setattr("app.task.runner.go_next", lambda _id: None)
    arguments = dict(clean_label="Image", clean_objective=turn.objective,
                     normalized_effort="standard", action_key="one-image", requested_disposition="CREATE_NEW")
    first = await mcp._create_conversation_task(turn, **arguments)
    task_id = UUID(first["id"])
    timing = (await task_startup_timings([task_id]))[0]
    assert timing.preparation_started_at <= timing.preparation_finished_at <= timing.enqueued_at
    assert timing.queue_wait_upper_bound_seconds is None
    second = await mcp._create_conversation_task(turn, **arguments)
    assert second["id"] == first["id"]
    assert second["created"] is False
    generate.assert_awaited_once()
    fixed = {"lifecycle_seconds", "phase_seconds"}
    assert (await task_startup_timings([task_id]))[0].model_dump(exclude=fixed) == timing.model_dump(exclude=fixed)
    detail = await monitoring_service.get_round(round_.id)
    assert [item.model_dump(exclude=fixed) for item in detail.task_startup_timings] == [timing.model_dump(exclude=fixed)]
    inspected = await inspection_service.inspect_round(round_.id)
    assert [{key: value for key, value in item.items() if key not in fixed}
            for item in inspected["task_startup_timings"]] == [timing.model_dump(mode="json", exclude=fixed)]
    # Reassignment does not make the old round's link an authorization to read
    # the Task's new label or timing in another agent's scope.
    from app.task import Task

    other_agent, _connection, _room, _other_sender = await _scope(db)
    task = await db.get(Task, task_id)
    task.agent_id = other_agent.id
    task.label = "Private after reassignment"
    await db.flush()
    assert (await monitoring_service.get_round(round_.id)).task_startup_timings == []
    assert (await inspection_service.inspect_round(round_.id))["task_startup_timings"] == []


@pytest.mark.asyncio
async def test_historical_preparation_is_recovered_only_with_unambiguous_task_lineage(db):
    from sqlalchemy import update
    from app.task import Task, task_startup_timings
    from app.llm import LLMCall

    agent, _connection, room, _sender = await _scope(db)
    round_ = ConversationRound(room_id=room.id, status="COMPLETED", language="fr")
    task = Task(label="Historical image", agent_id=agent.id)
    db.add_all([round_, task])
    await db.flush()
    await db.execute(update(Task).where(Task.id == task.id).values(lifecycle_timing=None))
    start = datetime(2026, 9, 13, 5, 44, 40, tzinfo=timezone.utc)
    db.add_all([
        ConversationTaskLink(round_id=round_.id, task_id=task.id, action_key="create"),
        LLMCall(conversation_round_id=round_.id, purpose="conversation.task_objective",
                started_at=start, completed_at=start + timedelta(seconds=15), duration=15),
        LLMCall(task_id=task.id, purpose="agent.dispatch", started_at=start + timedelta(seconds=15.3),
                completed_at=start + timedelta(seconds=18), duration=2.7),
    ])
    await db.flush()
    recovered = (await task_startup_timings([task.id]))[0]
    assert recovered.preparation_source == "llm_calls"
    assert recovered.preparation_seconds == 15
    assert recovered.preparation_started_at == start
    assert recovered.preparation_to_first_call_seconds == pytest.approx(.3)
    assert recovered.queue_wait_upper_bound_seconds is None

    another = Task(label="Other admission", agent_id=agent.id)
    db.add(another)
    await db.flush()
    db.add(ConversationTaskLink(round_id=round_.id, task_id=another.id, action_key="another"))
    await db.flush()
    ambiguous = (await task_startup_timings([task.id]))[0]
    assert ambiguous.preparation_seconds is None
    assert [interval.purpose for interval in ambiguous.processing_intervals] == ["agent.dispatch"]


async def _scope(db: AsyncSession) -> tuple[Agent, Connection, Room, MessengerUser]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Conversation monitoring {suffix}", gender="X")
    tool = Tool(
        code=f"conversation-monitoring-{suffix}",
        label="Conversation monitoring",
        description="",
        connection_schema={},
        conversation_enabled=True,
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Conversation",
        code=f"conversation-monitoring-agent-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        id=uuid5(NAMESPACE_URL, f"{connection.id}:monitoring-room"),
        connection_id=connection.id,
        external_id="monitoring-room",
        label="Salon supervision",
        kind="direct",
        conversation_type="text",
    )
    sender = MessengerUser(
        id=uuid5(NAMESPACE_URL, f"{connection.tool_id}:human-monitoring"),
        tool_id=connection.tool_id,
        external_id="human-monitoring",
        display_name="Nicolas",
    )
    db.add_all([room, sender])
    await db.flush()
    return agent, connection, room, sender


async def _message(
    db: AsyncSession,
    connection: Connection,
    room: Room,
    sender: MessengerUser,
    sequence: int,
    text: str,
) -> Message:
    message = Message(
        id=uuid4(),
        connection_id=connection.id,
        remote_message_id=f"monitoring-message-{sequence}-{uuid4()}",
        direction="inbound",
        platform="telegram",
        tool_id=connection.tool_id,
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        user_id=sender.external_id,
        text=text,
        created_at=datetime.fromtimestamp(sequence, tz=timezone.utc),
    )
    db.add(message)
    await db.flush()
    message.sender = sender
    message.room = room
    return message


def _install_messenger(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    connection: Connection,
    room: Room,
) -> None:
    class LocalMessenger:
        async def send_to_room(
            self,
            room_id: UUID | str,
            text: str,
            *,
            publish_event: bool = True,
            journal_metadata: dict[str, object] | None = None,
        ) -> Message:
            del publish_event
            assert room_id == room.id
            message = Message(
                id=uuid4(),
                connection_id=connection.id,
                tool_id=connection.tool_id,
                platform="telegram",
                remote_message_id=f"monitoring-output-{uuid4()}",
                direction="outbound",
                messenger_room_id=room.id,
                room_id=room.external_id,
                text=text,
                metadata_=dict(journal_metadata or {}),
            )
            db.add(message)
            await db.flush()
            return message

    async def get_messenger(connection_id: int) -> LocalMessenger:
        assert connection_id == connection.id
        return LocalMessenger()

    import app.messenger as messenger_package

    monkeypatch.setattr(messenger_package, "get_messenger", get_messenger)


@pytest.mark.asyncio
async def test_monitoring_projects_canonical_messages_round_and_dataset(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room, sender = await _scope(db)
    _install_messenger(monkeypatch, db, connection, room)
    inputs: list[Message] = []
    for sequence, text in ((1, "Bonjour"), (2, "Avec plus de détails")):
        message = await _message(db, connection, room, sender, sequence, text)
        inputs.append(message)
        assert await admit_message(
            message,
            agent_id=agent.id,
            connection_id=connection.id,
            language="fr",
        )
    round_ = await claim_next_round("monitoring-worker")
    assert round_ is not None
    topic = Topic(title="Monitoring coherence")
    db.add(topic)
    await db.flush()
    round_.topic_id = topic.id
    assert await complete_round(
        round_.id,
        ConversationOutcome(
            text="Voici la réponse.",
            execution_result=AIResult(
                prompt="",
                result="Voici la réponse.",
                success=True,
            ),
        ),
        lease_token=round_.lease_token,
    ) == "SUCCEEDED"
    call = LLMCall(
        conversation_round_id=round_.id,
        agent_run_id=round_.id,
        agent_id=agent.id,
        provider_name="test",
        requested_model="test-model",
        effective_model="test-model",
        status="completed",
        request_messages=[],
        prompt="",
        system_prompt="",
        response_text="Voici la réponse.",
        reasoning="",
        tool_calls=[],
        usage={},
    )
    db.add(call)
    await db.commit()

    page = await monitoring_service.list_messages(
        page=1,
        page_size=50,
        agent_id=agent.id,
        search="Salon supervision",
    )
    assert page.total == 2
    assert page.summary.idle == 1
    assert [item.payload["text"] for item in reversed(page.items)] == [
        "Bonjour",
        "Avec plus de détails",
    ]
    assert all(item.room_id == room.id for item in page.items)
    assert all(item.round_id == round_.id for item in page.items)
    assert all(item.topic_id == topic.id for item in page.items)
    assert all(item.response_text == "Voici la réponse." for item in page.items)
    assert page.items[0].payload["sender"] == {
        "local_id": str(sender.id),
        "id": sender.external_id,
        "display_name": sender.display_name,
        "agent_id": None,
        "is_ai": False,
    }

    topic_page = await monitoring_service.list_messages(
        page=1,
        page_size=50,
        topic_id=topic.id,
    )
    assert topic_page.total == 2

    detail = await monitoring_service.get_round(round_.id)
    assert detail is not None
    assert detail.room_id == room.id
    assert detail.topic_id == topic.id
    assert [item["text"] for item in detail.rendered_input] == [
        "Bonjour",
        "Avec plus de détails",
    ]
    assert detail.response_text == "Voici la réponse."

    replacement_topic = Topic(title="Updated monitoring coherence")
    db.add(replacement_topic)
    await db.commit()
    assert await management_service.update_round_topic(round_.id, replacement_topic.id)
    updated_detail = await monitoring_service.get_round(round_.id)
    assert updated_detail is not None
    assert updated_detail.topic_id == replacement_topic.id

    dataset = await inspection_service.inspect_round(round_.id)
    assert dataset is not None
    assert dataset["room"]["id"] == str(room.id)
    assert [item["id"] for item in dataset["messages"][:2]] == [
        str(inputs[0].id),
        str(inputs[1].id),
    ]
    assert len(dataset["llm_calls"]) == 1

    assert await management_service.delete_round(round_.id)
    assert await db.get(Message, inputs[0].id) is not None
    await db.refresh(call)
    assert call.conversation_round_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "round_status",
    (
        "FROZEN",
        "CLAIMED",
        "RUNNING",
        "SUCCEEDED",
        "SUPERSEDED",
        "ERROR_RESOLVED",
        "CANCELLED",
    ),
)
async def test_delete_round_accepts_every_lifecycle_status(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    round_status: str,
) -> None:
    agent, connection, room, sender = await _scope(db)
    message = await _message(db, connection, room, sender, 1, "Tour à supprimer")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await db.scalar(
        select(ConversationRound).where(ConversationRound.room_id == room.id)
    )
    assert round_ is not None
    round_.status = round_status
    attempt_id: UUID | None = None
    if round_status in {"CLAIMED", "RUNNING"}:
        lease_token = uuid4()
        round_.lease_token = lease_token
        round_.lease_owner = "deletion-test-worker"
        round_.attempt_count = 1
        attempt = ConversationRoundAttempt(
            round_id=round_.id,
            attempt_number=1,
            worker_id="deletion-test-worker",
            lease_token=lease_token,
            status=round_status,
        )
        db.add(attempt)
        attempt_id = attempt.id
    call = LLMCall(
        conversation_round_id=round_.id,
        agent_run_id=round_.id,
        agent_id=agent.id,
        status="running",
    )
    db.add(call)
    await db.commit()
    cancel_round = AsyncMock(return_value=round_status in {"CLAIMED", "RUNNING"})
    monkeypatch.setattr(scheduler, "cancel_round", cancel_round)

    assert await management_service.delete_round(round_.id)

    cancel_round.assert_awaited_once_with(round_.id)
    assert await db.get(ConversationRound, round_.id) is None
    if attempt_id is not None:
        assert await db.get(ConversationRoundAttempt, attempt_id) is None
    assert await db.get(Message, message.id) is not None
    await db.refresh(call)
    assert call.conversation_round_id is None
    assert call.status == "cancelled"
    assert call.completed_at is not None
    assert call.error == (
        "LLM trace stopped because its conversation round was deleted."
    )


@pytest.mark.asyncio
async def test_monitoring_filters_ready_messages_by_date_and_sender(
    db: AsyncSession,
) -> None:
    agent, connection, room, sender = await _scope(db)
    message = await _message(db, connection, room, sender, 1, "Message filtrable")
    message.created_at = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)

    page = await monitoring_service.list_messages(
        page=1,
        page_size=10,
        status="READY",
        search="Nicolas",
        date_from=date(2026, 8, 9),
        date_to=date(2026, 8, 9),
    )
    assert page.total == 1
    assert page.summary.ready == 1
    assert page.items[0].round_status == "FROZEN"

    outside = await monitoring_service.list_messages(
        page=1,
        page_size=10,
        date_from=date(2026, 8, 10),
    )
    assert outside.total == 0


@pytest.mark.asyncio
async def test_monitoring_projects_failed_round(db: AsyncSession) -> None:
    agent, connection, room, sender = await _scope(db)
    message = await _message(db, connection, room, sender, 1, "Échec attendu")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("failure-1")
    assert round_ is not None
    await fail_round(round_.id, "first failure", lease_token=round_.lease_token)
    round_ = await claim_next_round("failure-2")
    assert round_ is not None
    await fail_round(round_.id, "second failure", lease_token=round_.lease_token)

    page = await monitoring_service.list_messages(
        page=1,
        page_size=10,
        errors_only=True,
    )
    assert page.total == 1
    assert page.summary.errors == 1
    assert page.items[0].round_status == "ERROR_RESOLVED"
    assert page.items[0].response_error == "second failure"


@pytest.mark.asyncio
async def test_monitoring_success_keeps_retry_errors_in_attempt_history(db: AsyncSession) -> None:
    agent, connection, room, sender = await _scope(db)
    message = await _message(db, connection, room, sender, 1, "Successful retry")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("first-attempt")
    assert round_ is not None
    await fail_round(round_.id, "Temporary failure", lease_token=round_.lease_token)
    round_ = await claim_next_round("successful-retry")
    assert round_ is not None
    assert await complete_round(
        round_.id, ConversationOutcome(text=""), lease_token=round_.lease_token,
    ) == "SUCCEEDED"
    # Historical rows may still carry the error preceding their successful retry.
    round_.last_error = "Temporary failure"
    await db.commit()

    page = await monitoring_service.list_messages(page=1, page_size=50)
    assert page.items[0].round_status == "SUCCEEDED"
    assert page.items[0].response_error is None
    assert page.summary.errors == 0
    detail = await monitoring_service.get_round(round_.id)
    assert detail is not None and detail.last_error is None
    errors = await monitoring_service.list_messages(page=1, page_size=50, errors_only=True)
    assert errors.total == 0
    attempt = await db.scalar(select(ConversationRoundAttempt).where(
        ConversationRoundAttempt.round_id == round_.id,
        ConversationRoundAttempt.status == "ERROR",
    ))
    assert attempt is not None and attempt.error == "Temporary failure"


def test_monitoring_routes_require_task_access() -> None:
    from app.conversation.router import (
        export_conversation_round,
        read_conversation_messages,
        read_conversation_round,
    )

    for endpoint in (
        read_conversation_messages,
        read_conversation_round,
        export_conversation_round,
    ):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.TASK_ACCESS
        ]

    from app.conversation.router import (
        delete_conversation_round,
        update_conversation_round_topic,
    )

    for endpoint in (delete_conversation_round, update_conversation_round_topic):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.TASK_EDIT
        ]


@pytest.mark.asyncio
async def test_monitoring_rejects_unauthenticated_requests(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/conversations/messages")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delivery_resolution_requires_authentication(client):
    from app.conversation.router import resolve_conversation_delivery
    assert resolve_conversation_delivery._authorize_meta["privileges"] == [Privileges.TASK_EDIT]
    response = await client.post(f"/api/conversations/rounds/{uuid4()}/delivery-resolution", json={"decision": "SKIPPED", "evidence": "An unauthenticated operation"})
    assert response.status_code == 401
