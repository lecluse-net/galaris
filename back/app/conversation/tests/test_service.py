from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
import httpx
import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.agent.contracts import AIMessage, AIResult, WorkingResource, WorkingSet
from app.connection.models import Connection
from app.conversation import service as conversation_service
from app.conversation import task_projection
from app.conversation import work_projection
from app.conversation.contracts import ConversationOutcome
from app.conversation.document_metadata import ConversationDocumentMetadata
from app.conversation.models import (
    ConversationProcessLink,
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.conversation.service import (
    admit_message,
    build_turn,
    claim_next_process_notification,
    claim_next_task_notification,
    claim_next_round,
    claim_next_round_notification,
    complete_round,
    deliver_process_notification,
    deliver_round_notification,
    deliver_task_notification,
    fail_round,
    mark_effect_if_fresh,
    reconcile_terminal_round_llm_calls,
    renew_round_lease,
    round_attempt_succeeded,
)
from app.llm import LLMCall
from app.file_share import DeliveredResource
from app.messenger import (
    CONVERSATION_OUTPUT_PENDING_METADATA_KEY,
    CONVERSATION_ROUND_METADATA_KEY,
    TASK_REQUESTED_METADATA_KEY,
    TASK_REASONING_EFFORT_METADATA_KEY,
    Interaction,
    Message,
    MessengerUser,
    Room,
    message_sent,
)
from app.process.models import ProcessDefinition, ProcessRun
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus
from app.task import parse_working_set
from app.topic import Topic
from app.tools.models import Tool
from tests.conftest import responses_sse  # noqa: F401


async def _scope(db: AsyncSession, *, user_id: int | None = None) -> tuple[Agent, Connection, Room]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Conversation {suffix}", gender="X")
    tool = Tool(
        code=f"messenger-{suffix}",
        label="Conversation transport",
        description="",
        connection_schema={},
        conversation_enabled=True,
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        user_id=user_id,
        title_id=title.id,
        first_name="Conversation",
        last_name="Test",
        code=f"conversation-{suffix}",
        agent_driver="hermes",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        id=uuid5(NAMESPACE_URL, f"{connection.id}:room-7"),
        connection_id=connection.id,
        external_id="room-7",
        label="Room 7",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    return agent, connection, room


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["resource", "checkpoint", "objective", "terminal"])
async def test_amendment_after_concurrent_update_keeps_one_task(db, monkeypatch, change):
    from app.conversation.mcp import conversation_task_submit
    from app.conversation import mcp
    from app.conversation.contracts import ConversationTurn
    from app.task.working_set import upsert_working_resource
    from app.task.models import TaskAmendment
    from app.tools import McpToolContext

    agent, connection, room = await _scope(db)
    task = Task(label="Report", objective="<p>Prepare the report.</p>",
                status=TaskStatus.CREATE, agent_id=agent.id,
                messenger_connection_id=connection.id, message_group_id=str(room.id))
    db.add(task)
    await db.commit()
    revision = task.revision
    snapshot = await conversation_service.linked_work_snapshot(room.id)
    assert snapshot[0]["task_id"] == str(task.id)
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=agent.id,
        language="fr", objective="Ajoute un PDF au rapport", messages=(),
        messaging_context={"connection_id": connection.id, "room_id": str(room.id)},
        linked_work=snapshot)
    if change == "resource":
        await upsert_working_resource(task.id, WorkingResource(
            resource_type="artifact", role="source", reference="https://example.test/source"))
    elif change == "checkpoint":
        task.data = {"_agent_run_checkpoint": {"driver_code": "internal",
            "runtime_run_id": "synthetic-run", "status": "interrupted",
            "data": {"version": 4, "resume_safe": True, "receipt": "confirmed"}}}
    elif change == "objective":
        task.objective = "<p>Prepare a different report.</p>"
    else:
        task.status = TaskStatus.SUCCESS
    await db.commit()
    assert task.revision > revision
    create = AsyncMock(return_value={"created": True})
    monkeypatch.setattr(mcp, "_create_conversation_task", create)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_: None)
    ctx = McpToolContext(agent_id=agent.id, runtime="internal", resources={"conversation_turn": turn})
    result = await conversation_task_submit(ctx, objective="Ajouter une version PDF.",
        disposition="AMEND_QUEUED", target_task_id=str(task.id), expected_revision=revision)

    create.assert_not_awaited()
    assert result["created"] is False
    if change in {"resource", "checkpoint"}:
        assert result["amended"] is True
        assert "Ajouter une version PDF." in task.objective
        # Redelivery of the same action uses its receipt even with the old revision.
        again = await conversation_task_submit(ctx, objective="Ajouter une version PDF.",
            disposition="AMEND_QUEUED", target_task_id=str(task.id), expected_revision=revision)
        assert again["amended"] is False
        assert len(list(await db.scalars(select(TaskAmendment).where(TaskAmendment.task_id == task.id)))) == 1
        if change == "checkpoint":
            assert task.data["_agent_run_checkpoint"]["data"]["receipt"] == "confirmed"
        else:
            assert parse_working_set(task).active()[0].reference == "https://example.test/source"
    else:
        assert result["amended"] is False
        assert result["conflict"] == "amendment_revision_changed"
        assert "Ajouter une version PDF." not in task.objective
        if change == "objective":
            # A fresh decision against the returned revision must not become stuck
            # just because resource registration progressed once more meanwhile.
            reviewed_revision = result["revision"]
            await upsert_working_resource(task.id, WorkingResource(
                resource_type="artifact", role="source", reference="https://example.test/reviewed"))
            await db.commit()
            reconsidered = await conversation_task_submit(ctx, objective="Ajouter une version PDF.",
                disposition="AMEND_QUEUED", target_task_id=str(task.id), expected_revision=reviewed_revision)
            assert reconsidered["amended"] is True
            assert "different report" in task.objective
            assert "Ajouter une version PDF." in task.objective
            create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["missing", "incomplete", "terminal", "plan", "remote_checkpoint", "starting"])
async def test_failed_amendment_preserves_target_and_explicit_new_work_is_idempotent(db, monkeypatch, blocker):
    from app.conversation import mcp
    from app.tools import McpToolContext

    agent, connection, room = await _scope(db)
    document = f"document://{uuid4()}"
    original = Task(
        label="Rapport existant", objective=f"<p>Ajouter un graphique au rapport {document}.</p>",
        agent_id=agent.id, messenger_connection_id=connection.id,
        message_group_id=str(room.id),
        status=TaskStatus.SUCCESS if blocker == "terminal" else TaskStatus.PLAN,
        plan={"steps": [{"label": "Analyse"}]} if blocker == "plan" else None,
        lease_token=uuid4() if blocker in {"remote_checkpoint", "starting"} else None,
        data={"_agent_run_checkpoint": {"driver_code": "hermes", "runtime_run_id": "synthetic-run",
            "status": "running", "data": {}}} if blocker == "remote_checkpoint" else None,
    )
    db.add(original)
    message = await _message(db, connection, room, 1, "Ajoute une synthèse au rapport.")
    await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("amendment-worker")
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    await db.commit()
    original_state = (original.revision, original.status, original.objective, original.plan, original.lease_token, original.data)
    generate = AsyncMock(return_value=("Glossaire", f"<p>Ajouter un glossaire à {document}, en préservant son contenu.</p>", 0.0))
    cancel = MagicMock()
    monkeypatch.setattr("app.task.scheduler.cancel", cancel)
    monkeypatch.setattr(mcp, "generate_task_fields", generate)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())
    monkeypatch.setattr("app.task.runner.go_next", lambda *_: None)
    ctx = McpToolContext(agent_id=agent.id, runtime="internal", resources={"conversation_turn": turn})

    result = await mcp.conversation_task_submit(
        ctx, objective="Ajouter une synthèse.", disposition="AMEND_CURRENT",
        target_task_id=str(uuid4() if blocker == "missing" else original.id),
        expected_revision=None if blocker == "incomplete" else original.revision,
    )

    assert result["action"] == "CONFLICT"
    assert result["created"] is False and result["amended"] is False
    assert result["conflict"] == {
        "missing": "amendment_target_unavailable", "incomplete": "incomplete_amendment_target",
        "terminal": "amendment_no_longer_safe", "plan": "amendment_no_longer_safe",
        "remote_checkpoint": "amendment_no_longer_safe", "starting": "amendment_no_longer_safe",
    }[blocker]
    generate.assert_not_awaited()
    await db.refresh(original)
    await db.refresh(round_)
    assert (original.revision, original.status, original.objective, original.plan, original.lease_token, original.data) == original_state
    assert round_.effect_started is False
    assert len(list(await db.scalars(select(Task).where(Task.agent_id == agent.id)))) == 1

    created = await mcp.conversation_task_submit(
        ctx, objective=f"Ajouter un glossaire à {document}.", disposition="CREATE_NEW",
    )
    repeated = await mcp.conversation_task_submit(
        ctx, objective=f"Ajouter un glossaire à {document}.", disposition="CREATE_NEW",
    )
    assert created["created"] is True and repeated["created"] is False
    assert created["resource_uri"] == repeated["resource_uri"]
    generate.assert_awaited_once()
    assert len(list(await db.scalars(select(Task).where(Task.agent_id == agent.id)))) == 2
    await db.refresh(original)
    assert (original.revision, original.status, original.objective, original.plan, original.lease_token, original.data) == original_state
    cancel.assert_not_called()
    successor = await db.scalar(select(Task).where(Task.agent_id == agent.id, Task.id != original.id))
    assert successor.status == TaskStatus.CREATE and successor.lease_token is None
    assert document in successor.objective


@pytest.mark.asyncio
async def test_voice_amendment_refusal_leaves_remote_work_running_and_new_task_queued(db, monkeypatch):
    from app.agent import submit_realtime_task
    from app.task import scheduler

    agent, connection, room = await _scope(db)
    document = f"document://{uuid4()}"
    original = Task(label="Chart", objective=f"<p>Add a chart to {document}.</p>",
        status=TaskStatus.EXEC, agent_id=agent.id, message_group_id=str(room.id),
        lease_token=uuid4(), data={"_agent_run_checkpoint": {"driver_code": "hermes",
            "runtime_run_id": "synthetic-voice-run", "status": "running", "data": {}}})
    db.add(original)
    await db.commit()
    original_state = (original.revision, original.objective, original.lease_token, original.data)
    cancel = MagicMock()
    monkeypatch.setattr(scheduler, "cancel", cancel)
    monkeypatch.setattr(scheduler, "wake", lambda *_, **__: None)
    args = dict(agent_id=agent.id, conversation_id=str(room.id), transport_kind="test",
        language="en", label="Glossary", objective=f"<p>Add a glossary to {document}.</p>")
    refused = await submit_realtime_task(**args, disposition="AMEND_CURRENT",
        target_task_id=original.id, expected_revision=original.revision)
    assert refused["action"] == "CONFLICT" and not refused["created"]
    assert len(list(await db.scalars(select(Task).where(Task.agent_id == agent.id)))) == 1
    created = await submit_realtime_task(**args, disposition="CREATE_NEW")
    assert created["created"]
    successor = await db.scalar(select(Task).where(Task.agent_id == agent.id, Task.id != original.id))
    assert successor.status == TaskStatus.CREATE and successor.lease_token is None
    # Exercise the real external driver's concurrency ceiling with the existing live lease.
    assert await scheduler._claim_locked_task(db, task_id=successor.id, status=successor.status,
        agent_id=agent.id, priority=0, now=datetime.now(timezone.utc)) is None
    await db.refresh(original)
    assert original.status == TaskStatus.EXEC
    assert (original.revision, original.objective, original.lease_token, original.data) == original_state
    cancel.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["text", "voice"])
async def test_explicit_replacement_admits_one_waiting_successor_and_keeps_independent_work(db, monkeypatch, transport):
    from app.conversation import mcp
    from app.agent import submit_realtime_task
    from app.task import reconcile_replacements
    from app.tools import McpToolContext

    agent, connection, room = await _scope(db)
    original = Task(label="Initial", objective="<p>Ancien rapport.</p>", status=TaskStatus.CREATE,
        agent_id=agent.id, messenger_connection_id=connection.id if transport == "text" else None,
        message_group_id=str(room.id) if transport == "text" else room.external_id)
    independent = Task(label="Independent", status=TaskStatus.CREATE, agent_id=agent.id)
    db.add_all([original, independent])
    message = await _message(db, connection, room, 1, "Remplace ce travail par un bilan corrigé.")
    await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("replace-worker")
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    await db.commit()
    revision = original.revision
    original_id = original.id
    monkeypatch.setattr(mcp, "generate_task_fields", AsyncMock(return_value=(
        "Bilan corrigé", "<p>Préparer le bilan corrigé.</p>", 0.0)))
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())
    monkeypatch.setattr("app.task.runner.go_next", lambda *_, **__: None)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_, **__: None)
    ctx = McpToolContext(agent_id=agent.id, runtime="internal", resources={"conversation_turn": turn})
    async def submit():
        if transport == "text":
            return await mcp.conversation_task_submit(ctx, disposition="REPLACE",
                objective="Préparer le bilan corrigé.", target_task_id=str(original_id), expected_revision=revision)
        return await submit_realtime_task(agent_id=agent.id, disposition="REPLACE",
            objective="Préparer le bilan corrigé.", label="Bilan", conversation_id=room.external_id,
            transport_kind="test", language="fr", target_task_id=original_id, expected_revision=revision)
    first, repeated = await submit(), await submit()
    assert first["created"] is True and repeated["created"] is False
    assert first["action"] == "REPLACE"
    assert first["replacement"]["state"] == "pending"
    tasks = list(await db.scalars(select(Task).where(Task.agent_id == agent.id)))
    assert len(tasks) == 3
    successor = next(item for item in tasks if item.source_task_id == original.id)
    assert successor.paused and successor.status == TaskStatus.CREATE
    assert original.status == TaskStatus.ERROR
    assert independent.status == TaskStatus.CREATE and not independent.paused
    await reconcile_replacements()
    await db.refresh(successor)
    assert not successor.paused
    assert successor.data["_replacement"]["state"] == "confirmed"


async def _message(
    db: AsyncSession,
    connection: Connection,
    room: Room,
    sequence: int,
    text: str,
) -> Message:
    sender_id = uuid5(NAMESPACE_URL, f"{connection.tool_id}:human-42")
    sender = await db.get(MessengerUser, sender_id)
    if sender is None:
        sender = MessengerUser(
            id=sender_id,
            tool_id=connection.tool_id,
            external_id="human-42",
            display_name="Nicolas",
        )
        db.add(sender)
        await db.flush()
    message = Message(
        id=uuid4(),
        connection_id=connection.id,
        tool_id=connection.tool_id,
        platform="telegram",
        remote_message_id=f"message-{sequence}-{uuid4()}",
        direction="inbound",
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
    sent: list[tuple[UUID | str, str]],
    transaction_states: list[bool] | None = None,
    publish_events: list[bool] | None = None,
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
            if transaction_states is not None:
                transaction_states.append(db.in_transaction())
            if publish_events is not None:
                publish_events.append(publish_event)
            sent.append((room_id, text))
            message = Message(
                id=uuid4(),
                connection_id=connection.id,
                tool_id=connection.tool_id,
                platform="telegram",
                remote_message_id=f"outbound-{uuid4()}",
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


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        ("HTTP 429: rate limit exceeded", "quota ou d’une limite de débit"),
        ("HTTP 401: invalid API key", "authentification ou de ses autorisations"),
        ("request timed out", "expiration du délai"),
        (
            "Conversation model 7 is unavailable",
            "absent, indisponible ou mal configuré",
        ),
        (
            "finish_reason=length",
            "interrompu sa réponse avant qu’elle soit complète",
        ),
        (
            "HTTP 503 Service Unavailable",
            "temporairement indisponible ou inaccessible",
        ),
        ("unexpected failure", "erreur technique interne"),
    ],
)
def test_degraded_response_includes_the_llm_error_and_explains_its_nature(
    error: str,
    expected_reason: str,
) -> None:
    text = conversation_service._degraded_response(language="fr", error=error)

    assert expected_reason in text
    assert f"Erreur renvoyée par le LLM : {error}" in text


def test_degraded_response_redacts_credentials_from_the_llm_error() -> None:
    text = conversation_service._degraded_response(
        language="fr",
        error=(
            "HTTP 401 api_key=sk-live-secret123 password=hunter2 "
            "Authorization: Bearer opaque-credential"
        ),
    )

    assert "HTTP 401" in text
    assert "sk-live-secret123" not in text
    assert "hunter2" not in text
    assert "opaque-credential" not in text
    assert text.count("[redacted]") >= 3


@pytest.mark.asyncio
async def test_failed_round_notification_includes_the_latest_llm_error(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "bonjour")
    assert await admit_message(
        message,
        agent_id=agent.id,
        connection_id=connection.id,
        language="fr",
    )
    first = await claim_next_round("failure-worker-1")
    assert first is not None
    await fail_round(first.id, "first provider failure", lease_token=first.lease_token)
    second = await claim_next_round("failure-worker-2")
    assert second is not None
    await fail_round(second.id, "HTTP 503: model backend unavailable", lease_token=second.lease_token)

    sent: list[tuple[UUID | str, str]] = []
    transaction_states: list[bool] = []
    _install_messenger(
        monkeypatch,
        db,
        connection,
        room,
        sent,
        transaction_states,
    )
    assert await claim_next_round_notification() == second.id
    await deliver_round_notification(second.id)

    assert len(sent) == 1
    assert transaction_states == [False]
    assert "Nature du problème" in sent[0][1]
    assert (
        "Erreur renvoyée par le LLM : HTTP 503: model backend unavailable"
        in sent[0][1]
    )


@pytest.mark.asyncio
async def test_admission_prefers_requester_language_and_refreshes_pending_round(db):
    from core.user.models import User

    agent, connection, room = await _scope(db)
    user = User(email=f"language-{uuid4().hex}@example.test", hashed_password="unused", language="fr")
    db.add(user)
    await db.flush()
    first = await _message(db, connection, room, 1, "Hello")
    first.requester_user_id = user.id
    assert await admit_message(first, agent_id=agent.id, connection_id=connection.id, language="en")
    round_ = await db.scalar(select(ConversationRound).where(ConversationRound.room_id == room.id))
    assert round_.language == "fr"

    user.language = "zh"
    second = await _message(db, connection, room, 2, "Continue")
    second.requester_user_id = user.id
    assert await admit_message(second, agent_id=agent.id, connection_id=connection.id, language="en")
    await db.refresh(round_)
    assert round_.language == "zh"


@pytest.mark.asyncio
@pytest.mark.parametrize("bounded", [False, True])
async def test_admission_uses_only_canonical_room_messages_and_is_idempotent(
    db: AsyncSession,
    bounded: bool,
) -> None:
    agent, connection, room = await _scope(db)
    first = await _message(db, connection, room, 1, "premier")
    latest_text = "dernier" + (" complément" * 2000 if bounded else "")
    second = await _message(db, connection, room, 2, latest_text)

    assert await admit_message(first, agent_id=agent.id, connection_id=connection.id)
    assert await admit_message(second, agent_id=agent.id, connection_id=connection.id)
    assert not await admit_message(second, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("test-worker")
    assert round_ is not None
    assert round_.room_id == room.id
    links = list(
        (
            await db.scalars(
                select(ConversationRoundMessage)
                .where(ConversationRoundMessage.round_id == round_.id)
                .order_by(ConversationRoundMessage.sequence)
            )
        ).all()
    )
    assert [(link.message_id, link.role, link.sequence) for link in links] == [
        (first.id, "input", 1),
        (second.id, "input", 2),
    ]
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    assert turn.room_id == room.id
    assert "premier" in turn.source_request
    assert latest_text in turn.source_request
    assert turn.omitted_input_count == (1 if bounded else 0)
    if not bounded:
        assert turn.objective == "[Nicolas] premier\n[Nicolas] dernier"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_outcome", ["success", "invalid", "unavailable"])
async def test_internal_messenger_turn_exposes_background_task_admission(
    inference_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    provider_outcome: str,
    responses_sse,
) -> None:
    from app.llm import LlmProfile
    from app.llm.provider_models import LLM, LLMProvider
    from app.task import runner

    db = inference_db
    agent, connection, room = await _scope(db)
    provider = LLMProvider(name=f"OpenRouter {uuid4()}", catalog_code="openrouter",
        provider_type="openai_compatible", base_url="https://openrouter.ai/api/v1", api_key="test-key")
    llm = LLM(code=f"admission-{uuid4()}", label="DeepSeek", llm_name="deepseek/deepseek-v4-flash-0731",
        provider=provider, cost_per_input_token=0, cost_per_output_token=0)
    db.add_all([provider, llm])
    await db.flush()
    profile = LlmProfile(label="Admission", text_standard_llm_id=llm.id)
    db.add(profile)
    await db.flush()
    agent.profile_id = profile.id
    source_request = (
        "Crée un tableau filtrable de planètes fictives.\n"
        "Conserve les valeurs < 7 & la colonne « phase » ; exporte aussi en CSV."
    )
    message = await _message(db, connection, room, 1, source_request)
    message.platform = "internal"
    await db.flush()

    requests = []
    # The provider omits constraints: admission must preserve the source independently.
    objective = "<p>Utiliser le catalogue fictif joint pour créer le tableau.</p>"

    async def upstream(_transport, request):
        assert request.url.host == "openrouter.ai"
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == "required"
        assert body["stream"] is True
        if provider_outcome == "unavailable":
            return httpx.Response(503, json={"error": {"message": "Provider unavailable"}})
        tool = next(tool for tool in body["tools"] if tool["type"] == "function")
        # Exercise output validation inside the actual admission workflow.
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=responses_sse({"id": f"resp-{len(requests)}", "object": "response",
            "created_at": 1, "status": "completed", "model": llm.llm_name,
            "output": [{"id": f"fc-{len(requests)}", "type": "function_call",
                "call_id": f"call-{len(requests)}", "name": tool["name"],
                "arguments": json.dumps({"label": "Catalogue fictif",
                    "objective": "" if len(requests) == 1 or provider_outcome == "invalid" else objective}), "status": "completed"}]}))

    async def unexpected_network(*args, **kwargs):
        pytest.fail("Admission must only contact the simulated provider")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", upstream)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", unexpected_network)
    wakeups = []
    monkeypatch.setattr(runner, "go_next", wakeups.append)

    assert await admit_message(
        message,
        agent_id=agent.id,
        connection_id=connection.id,
        language="fr",
    )
    round_ = await claim_next_round("chat-worker")
    assert round_ is not None

    turn = await build_turn(round_.id, lease_token=round_.lease_token)

    assert turn.messaging_context["platform"] == "internal"
    assert turn.admit_background_task is not None
    assert turn.linked_work == ()
    assert turn.pending_interactions == ()

    if provider_outcome != "success":
        from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

        error_type = ModelHTTPError if provider_outcome == "unavailable" else UnexpectedModelBehavior
        with pytest.raises(error_type):
            await turn.admit_background_task(turn.objective)
        assert len(requests) == (1 if provider_outcome == "unavailable" else 3)
        assert await db.scalar(select(ConversationTaskLink).where(ConversationTaskLink.round_id == round_.id)) is None
        assert await db.scalar(select(Task).where(Task.agent_id == agent.id)) is None
        assert wakeups == []
        return

    created = await turn.admit_background_task(turn.objective)
    repeated = await turn.admit_background_task(turn.objective)
    assert created["created"] is True
    assert repeated["created"] is False
    assert len(requests) == 2
    task_link = await db.scalar(select(ConversationTaskLink).where(ConversationTaskLink.round_id == round_.id))
    assert task_link is not None
    task = await db.get(Task, task_link.task_id)
    assert task is not None
    from core.util import visible_text

    assert source_request in visible_text(task.objective)
    assert visible_text(objective) in visible_text(task.objective)
    assert "&lt; 7 &amp;" in task.objective
    assert task.messages is None
    assert task.data["objective_is_standalone"] is True
    assert source_request in visible_text(task.data["_original_demand"])
    assert task.label == "Catalogue fictif"
    assert task.status == TaskStatus.CREATE
    assert wakeups == [task.id]
    calls = list((await db.scalars(select(LLMCall).where(LLMCall.conversation_round_id == round_.id))).all())
    assert len(calls) == 2
    assert all(call.status == "completed" for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "expected_effort"),
    [
        ({TASK_REQUESTED_METADATA_KEY: True}, None),
        (
            {
                TASK_REQUESTED_METADATA_KEY: True,
                TASK_REASONING_EFFORT_METADATA_KEY: "xhigh",
            },
            "xhigh",
        ),
    ],
)
async def test_build_turn_exposes_hidden_task_request_and_optional_reasoning_override(
    db: AsyncSession,
    metadata: dict[str, object],
    expected_effort: str | None,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "Analyse le rapport")
    message.metadata_ = metadata
    await db.flush()

    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("reasoning-worker")
    assert round_ is not None

    turn = await build_turn(round_.id, lease_token=round_.lease_token)

    assert turn.direct_task_requested is True
    assert turn.reasoning_effort_override == expected_effort


@pytest.mark.asyncio
@pytest.mark.parametrize("latest_uri", [None, "document://12345678-1234-4234-8234-123456789abc", "https://example.invalid/injected"])
async def test_build_turn_includes_only_the_latest_chat_document_in_the_prompt(
    db: AsyncSession, latest_uri: str | None,
) -> None:
    agent, connection, room = await _scope(db)
    old = await _message(db, connection, room, 1, "Premier message")
    old.platform = "internal"
    old.metadata_ = {"displayed_document_uri": f"document://{uuid4()}"}
    latest = await _message(db, connection, room, 2, "Continue ici")
    latest.platform = "internal"
    latest.metadata_ = {"displayed_document_uri": latest_uri} if latest_uri else {}
    await db.flush()
    for message in [old, latest]:
        assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("visible-document-worker")
    assert round_ is not None
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    expected = latest_uri is not None and latest_uri.startswith("document://")
    assert "Chat display context" not in turn.source_request
    assert "Premier message" in turn.source_request and "Continue ici" in turn.source_request
    assert ("Chat display context" in turn.objective) is expected
    assert ("Chat display context" in str(turn.messages[-1]["text"])) is expected
    if expected:
        assert latest_uri in turn.objective
    assert old.metadata_["displayed_document_uri"] not in turn.objective
    assert latest.text == "Continue ici"
    assert old.text == "Premier message"


@pytest.mark.asyncio
async def test_build_turn_treats_plan_directive_as_a_direct_task(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "@plan Analyse le rapport")
    await db.flush()

    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("plan-worker")
    assert round_ is not None

    turn = await build_turn(round_.id, lease_token=round_.lease_token)

    assert turn.direct_task_requested is True


@pytest.mark.asyncio
async def test_build_turn_projects_a_pending_choice_for_the_exact_sender(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(
        db,
        connection,
        room,
        1,
        "Ne lance pas cette commande, corrige plutôt le rapport.",
    )
    interaction = Interaction(
        reference="DEC1DE42",
        kind="hermes_approval",
        agent_id=agent.id,
        connection_id=connection.id,
        tool_id=connection.tool_id,
        room_id=str(room.id),
        user_id="human-42",
        title="Approbation requise",
        body="Commande: rm rapport.tmp",
        options=[
            {"id": "once", "label": "Approuver une fois"},
            {"id": "deny", "label": "Refuser"},
        ],
        metadata_={"task_id": str(uuid4())},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(interaction)
    await db.flush()

    assert await admit_message(
        message,
        agent_id=agent.id,
        connection_id=connection.id,
        language="fr",
    )
    round_ = await claim_next_round("pending-choice-worker")
    assert round_ is not None

    turn = await build_turn(round_.id, lease_token=round_.lease_token)

    assert turn.messaging_context["tool_id"] == connection.tool_id
    assert turn.pending_interactions == (
        {
            "reference": "DEC1DE42",
            "kind": "hermes_approval",
            "title": "Approbation requise",
            "body": "Commande: rm rapport.tmp",
            "options": (
                {"id": "once", "label": "Approuver une fois"},
                {"id": "deny", "label": "Refuser"},
            ),
            "task_id": interaction.metadata_["task_id"],
            "expires_at": interaction.expires_at.isoformat(),
        },
    )


@pytest.mark.asyncio
async def test_admission_copies_exact_contact_before_topic_classification(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import MessengerContactObservation, observe_messenger_contact

    agent, connection, room = await _scope(db)
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="telegram",
            user_id="human-42",
            display_name="Nicolas",
        )
    )
    message = await _message(db, connection, room, 1, "nouveau sujet")
    message.contact_memory_item_id = contact_id
    await db.flush()

    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id
    )
    round_ = await db.scalar(
        select(ConversationRound).where(ConversationRound.room_id == room.id)
    )

    assert round_ is not None
    assert round_.topic_id is None
    assert round_.contact_memory_item_id == contact_id

    sent: list[tuple[UUID | str, str]] = []
    _install_messenger(monkeypatch, db, connection, room, sent)
    claimed = await claim_next_round("contact-output-worker")
    assert claimed is not None and claimed.id == round_.id
    assert await complete_round(
        claimed.id,
        ConversationOutcome(text="réponse liée au contact"),
        lease_token=claimed.lease_token,
    ) == "SUCCEEDED"
    output_message = await db.scalar(
        select(Message)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == round_.id,
            ConversationRoundMessage.role == "output",
        )
    )
    assert output_message is not None
    assert output_message.contact_memory_item_id == contact_id


@pytest.mark.asyncio
async def test_linked_work_uses_creation_time_for_a_never_updated_task(
    db: AsyncSession,
) -> None:
    agent, _connection, room = await _scope(db)
    historical_round = ConversationRound(
        room_id=room.id,
        language="fr",
        status="SUCCEEDED",
        finished_at=datetime.now(timezone.utc),
    )
    task = Task(
        label="Tâche historique",
        objective="Conserver une tâche qui n'a jamais été modifiée.",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
    )
    db.add_all([historical_round, task])
    await db.flush()
    assert task.updated_at is None
    db.add(
        ConversationTaskLink(
            round_id=historical_round.id,
            task_id=task.id,
            action_key=f"task-{uuid4()}",
        )
    )
    await db.flush()

    snapshots = await conversation_service.linked_work_snapshot(room.id)

    assert len(snapshots) == 1
    assert snapshots[0]["task_id"] == str(task.id)
    assert snapshots[0]["created_at"] == task.created_at.astimezone().isoformat(
        timespec="minutes"
    )
    assert snapshots[0]["state_since"] == task.created_at.astimezone().isoformat(
        timespec="minutes"
    )
    assert snapshots[0]["updated_at"] == task.created_at.isoformat()


@pytest.mark.asyncio
async def test_linked_work_includes_voice_task_bound_to_the_canonical_room(
    db: AsyncSession,
) -> None:
    agent, _connection, room = await _scope(db)
    task = Task(
        label="Tâche audio",
        objective="<p>Travail admis pendant l'appel.</p>",
        status=TaskStatus.CREATE,
        agent_id=agent.id,
        message_group_id=str(room.id),
        message_platform="voice:nextcloud_talk",
    )
    db.add(task)
    await db.flush()

    snapshots = await conversation_service.linked_work_snapshot(room.id)

    assert [snapshot["task_id"] for snapshot in snapshots] == [str(task.id)]
    assert snapshots[0]["objective"] == "<p>Travail admis pendant l'appel.</p>"


@pytest.mark.asyncio
async def test_linked_work_filters_and_orders_tasks_by_operational_recency(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(conversation_service, "_now", lambda: now)
    agent, _connection, room = await _scope(db)
    historical_round = ConversationRound(
        room_id=room.id,
        language="fr",
        status="SUCCEEDED",
        finished_at=now,
    )
    db.add(historical_round)
    await db.flush()

    tasks = [
        Task(
            label="Running",
            objective="R" * 400,
            status=TaskStatus.EXEC,
            agent_id=agent.id,
            lease_token=uuid4(),
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=3),
        ),
        Task(
            label="Waiting old",
            status=TaskStatus.DISPATCH,
            paused=True,
            data={"pause_reasons": ["await"]},
            agent_id=agent.id,
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=3),
        ),
        Task(
            label="Queued",
            status=TaskStatus.CREATE,
            agent_id=agent.id,
            created_at=now - timedelta(days=5),
        ),
        Task(
            label="Paused recent",
            status=TaskStatus.DISPATCH,
            paused=True,
            data={"pause_reasons": ["user"]},
            agent_id=agent.id,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=24),
        ),
        Task(
            label="Paused stale",
            status=TaskStatus.DISPATCH,
            paused=True,
            data={"pause_reasons": ["user"]},
            agent_id=agent.id,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=25),
        ),
        Task(
            label="Terminal newest",
            status=TaskStatus.SUCCESS,
            agent_id=agent.id,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=10),
        ),
        Task(
            label="Terminal second",
            status=TaskStatus.ERROR,
            agent_id=agent.id,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=20),
        ),
        Task(
            label="Terminal third",
            status=TaskStatus.SUCCESS,
            agent_id=agent.id,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=30),
        ),
        Task(
            label="Terminal stale",
            status=TaskStatus.ERROR,
            agent_id=agent.id,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=60),
        ),
    ]
    db.add_all(tasks)
    await db.flush()
    for task in tasks:
        db.add(
            ConversationTaskLink(
                round_id=historical_round.id,
                task_id=task.id,
                action_key=f"task-{task.id}",
            )
        )
    await db.flush()

    snapshots = await conversation_service.linked_work_snapshot(room.id)

    assert [snapshot["label"] for snapshot in snapshots] == [
        "Running",
        "Waiting old",
        "Queued",
        "Paused recent",
        "Terminal newest",
        "Terminal second",
    ]
    assert len(str(snapshots[0]["objective"])) == 250
    assert datetime.fromisoformat(str(snapshots[0]["created_at"])) == datetime(
        2026, 8, 20, 12, tzinfo=timezone.utc
    )
    assert datetime.fromisoformat(str(snapshots[0]["state_since"])) == datetime(
        2026, 8, 21, 12, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_linked_work_keeps_every_non_terminal_task_beyond_legacy_limit(
    db: AsyncSession,
) -> None:
    agent, _connection, room = await _scope(db)
    historical_round = ConversationRound(
        room_id=room.id,
        language="fr",
        status="SUCCEEDED",
        finished_at=datetime.now(timezone.utc),
    )
    tasks = [
        Task(
            label=f"Queued {index}",
            status=TaskStatus.CREATE,
            agent_id=agent.id,
        )
        for index in range(12)
    ]
    db.add_all([historical_round, *tasks])
    await db.flush()
    db.add_all(
        [
            ConversationTaskLink(
                round_id=historical_round.id,
                task_id=task.id,
                action_key=f"task-{task.id}",
            )
            for task in tasks
        ]
    )
    await db.flush()

    snapshots = await conversation_service.linked_work_snapshot(room.id)

    assert len(snapshots) == 12
    assert {snapshot["task_id"] for snapshot in snapshots} == {
        str(task.id) for task in tasks
    }


@pytest.mark.asyncio
async def test_room_task_projection_keeps_the_full_cross_agent_hierarchy(
    db: AsyncSession,
) -> None:
    agent, _connection, room = await _scope(db)
    other_agent = Agent(
        title_id=agent.title_id,
        first_name="Delegated",
        last_name="Agent",
        code=f"delegated-{uuid4().hex[:10]}",
        agent_driver="hermes",
    )
    db.add(other_agent)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, language="fr", status="SUCCEEDED")
    stale_topic = Topic(title=f"Stale task topic {uuid4().hex[:8]}")
    db.add(stale_topic)
    await db.flush()
    root = Task(
        label="Conversation root",
        status=TaskStatus.EXEC,
        agent_id=agent.id,
        topic_id=stale_topic.id,
    )
    unrelated_parent = Task(label="Outside parent", status=TaskStatus.EXEC, agent_id=agent.id)
    unrelated = Task(label="Unrelated", status=TaskStatus.EXEC, agent_id=agent.id)
    db.add_all([round_, root, unrelated_parent, unrelated])
    await db.flush()
    delegated = Task(
        label="Delegated task",
        status=TaskStatus.EXEC,
        agent_id=other_agent.id,
        parent_id=root.id,
        source_task_id=root.id,
    )
    db.add(delegated)
    await db.flush()
    causal_only = Task(
        label="Causal continuation",
        status=TaskStatus.EXEC,
        agent_id=other_agent.id,
        parent_id=unrelated_parent.id,
        source_task_id=delegated.id,
    )
    db.add(causal_only)
    await db.flush()
    grandchild = Task(
        label="Grandchild",
        status=TaskStatus.CREATE,
        agent_id=agent.id,
        parent_id=causal_only.id,
    )
    db.add(grandchild)
    await db.flush()
    db.add(
        ConversationTaskLink(
            round_id=round_.id,
            task_id=root.id,
            action_key="root-task",
        )
    )
    await db.flush()

    first_page = await task_projection.list_room_tasks(room.id, page=1, page_size=2)
    second_page = await task_projection.list_room_tasks(room.id, page=2, page_size=2)

    by_id = {item.id: item for item in [*first_page.items, *second_page.items]}
    assert set(by_id) == {root.id, delegated.id, causal_only.id, grandchild.id}
    assert first_page.total == second_page.total == 4
    assert first_page.page == 1
    assert second_page.page == 2
    assert first_page.page_size == second_page.page_size == 2
    assert by_id[root.id].tree_parent_id is None
    assert by_id[root.id].directly_linked is True
    assert by_id[root.id].topic_id is None
    assert by_id[delegated.id].tree_parent_id == root.id
    assert by_id[delegated.id].agent_id == other_agent.id
    assert by_id[causal_only.id].tree_parent_id == delegated.id
    assert by_id[grandchild.id].tree_parent_id == causal_only.id


@pytest.mark.asyncio
async def test_room_work_projection_starts_at_oldest_displayed_message(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    old_message = await _message(db, connection, room, 1, "Ancien échange")
    visible_document_id = uuid4()
    second_visible_document_id = uuid4()
    visible_message = await _message(
        db,
        connection,
        room,
        2,
        (
            f"Documents courants document://{visible_document_id} "
            f"document://{second_visible_document_id}"
        ),
    )
    old_round = ConversationRound(room_id=room.id, language="fr", status="SUCCEEDED")
    visible_round = ConversationRound(room_id=room.id, language="fr", status="SUCCEEDED")
    db.add_all([old_round, visible_round])
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=old_round.id,
                message_id=old_message.id,
                role="input",
                sequence=1,
            ),
            ConversationRoundMessage(
                round_id=visible_round.id,
                message_id=visible_message.id,
                role="input",
                sequence=1,
            ),
        ]
    )
    old_document_id = uuid4()
    old_task = Task(
        label="Old task",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        data={
            "working_set": WorkingSet(
                resources=[
                    WorkingResource(
                        resource_type="memory_document",
                        role="draft",
                        reference=f"document://{old_document_id}",
                        label="Old document",
                    )
                ]
            ).model_dump(mode="json")
        },
    )
    visible_task = Task(
        label="Visible task",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        data={
            "working_set": WorkingSet(
                resources=[
                    WorkingResource(
                        resource_type="memory_document",
                        role="draft",
                        reference=f"document://{visible_document_id}",
                        label="Visible document",
                    )
                ]
            ).model_dump(mode="json")
        },
    )
    db.add_all([old_task, visible_task])
    await db.flush()
    db.add_all(
        [
            ConversationTaskLink(
                round_id=old_round.id,
                task_id=old_task.id,
                action_key="old-task",
            ),
            ConversationTaskLink(
                round_id=visible_round.id,
                task_id=visible_task.id,
                action_key="visible-task",
            ),
        ]
    )
    definition = ProcessDefinition(
        agent_id=agent.id,
        tool_id=connection.tool_id,
        engine_process_id=f"workflow-{uuid4()}",
        label="Conversation process",
    )
    db.add(definition)
    await db.flush()
    old_run = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        task_id=old_task.id,
        engine_code="fake",
        correlation_id=f"old-{uuid4()}",
        callback_token=uuid4().hex,
        status="success",
        input={},
    )
    visible_run = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        task_id=visible_task.id,
        engine_code="fake",
        correlation_id=f"visible-{uuid4()}",
        callback_token=uuid4().hex,
        status="running",
        input={},
    )
    visible_direct_run = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        engine_code="fake",
        correlation_id=f"visible-direct-{uuid4()}",
        callback_token=uuid4().hex,
        status="queued",
        input={},
    )
    db.add_all([old_run, visible_run, visible_direct_run])
    await db.flush()
    db.add(
        ConversationProcessLink(
            round_id=visible_round.id,
            process_run_id=visible_direct_run.id,
            action_key="visible-process",
        )
    )
    await db.flush()

    canonical_updated_at = datetime.now(timezone.utc)
    metadata_resolver = AsyncMock(
        return_value={
            visible_document_id: ConversationDocumentMetadata(
                id=visible_document_id,
                title="Canonical visible document title",
                revision=7,
                updated_at=canonical_updated_at,
            )
        }
    )
    monkeypatch.setattr(
        work_projection,
        "resolve_conversation_document_metadata",
        metadata_resolver,
    )
    monkeypatch.setattr(
        work_projection,
        "resolve_conversation_room_documents",
        AsyncMock(return_value=()),
    )

    tasks = await task_projection.list_room_tasks(room.id, visible_message.id)
    first_document_page = await work_projection.list_room_documents(
        room.id, visible_message.id, agent_id=agent.id, page=1, page_size=1
    )
    second_document_page = await work_projection.list_room_documents(
        room.id, visible_message.id, agent_id=agent.id, page=2, page_size=1
    )
    first_process_page = await work_projection.list_room_processes(
        room.id, visible_message.id, page=1, page_size=1
    )
    second_process_page = await work_projection.list_room_processes(
        room.id, visible_message.id, page=2, page_size=1
    )

    assert [item.id for item in tasks.items] == [visible_task.id]
    documents = [*first_document_page.items, *second_document_page.items]
    assert first_document_page.total == second_document_page.total == 2
    assert {item.id for item in documents} == {
        visible_document_id,
        second_visible_document_id,
    }
    visible_document = next(
        item for item in documents if item.id == visible_document_id
    )
    assert visible_document.label == "Canonical visible document title"
    assert visible_document.revision == 7
    assert visible_document.updated_at == canonical_updated_at
    metadata_resolver.assert_awaited()
    processes = [*first_process_page.items, *second_process_page.items]
    assert first_process_page.total == second_process_page.total == 2
    assert {item.id for item in processes} == {
        visible_run.id,
        visible_direct_run.id,
    }


@pytest.mark.asyncio
async def test_room_never_claims_two_rounds_concurrently(db: AsyncSession) -> None:
    agent, connection, room = await _scope(db)
    first = await _message(db, connection, room, 1, "version A")
    assert await admit_message(first, agent_id=agent.id, connection_id=connection.id)
    running = await claim_next_round("worker-1")
    assert running is not None

    second = await _message(db, connection, room, 2, "correction B")
    assert await admit_message(second, agent_id=agent.id, connection_id=connection.id)
    assert await claim_next_round("worker-2") is None
    assert not await mark_effect_if_fresh(running.id, lease_token=running.lease_token)
    assert await complete_round(
        running.id, ConversationOutcome(text="réponse obsolète"),
        lease_token=running.lease_token,
    ) == "SUPERSEDED"

    successor = await claim_next_round("worker-2")
    assert successor is not None
    linked_ids = list(
        await db.scalars(
            select(ConversationRoundMessage.message_id)
            .where(
                ConversationRoundMessage.round_id == successor.id,
                ConversationRoundMessage.role == "input",
            )
            .order_by(ConversationRoundMessage.sequence)
        )
    )
    assert linked_ids == [first.id, second.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("effect_started", [False, True])
async def test_text_turn_detects_new_input_without_replaying_effects(
    db: AsyncSession, effect_started: bool,
) -> None:
    agent, connection, room = await _scope(db)
    first = await _message(db, connection, room, 1, "version A")
    await admit_message(first, agent_id=agent.id, connection_id=connection.id)
    running = await claim_next_round("interrupt-worker")
    assert running is not None
    turn = await build_turn(running.id, lease_token=running.lease_token)
    assert turn.should_interrupt is not None
    assert not await turn.should_interrupt()
    await db.refresh(running)
    assert not running.effect_started
    if effect_started:
        assert await turn.assert_fresh_before_effect()

    second = await _message(db, connection, room, 2, "correction B")
    await admit_message(second, agent_id=agent.id, connection_id=connection.id)
    assert not await admit_message(second, agent_id=agent.id, connection_id=connection.id)
    third = await _message(db, connection, room, 3, "et précision C")
    await admit_message(third, agent_id=agent.id, connection_id=connection.id)
    assert await turn.should_interrupt()
    assert not await conversation_service.newer_input_pending(running.id, lease_token=uuid4())
    assert await claim_next_round("other-worker") is None
    status = await complete_round(
        running.id, ConversationOutcome(
            text="", metadata={"interrupted": True},
            execution_result=AIResult(prompt="version A", messages=[
                AIMessage(type="text", content="Ancien brouillon"),
                AIMessage(type="tool", tool_name="test_effect", content="receipt"),
            ]),
        ), lease_token=running.lease_token,
    )
    assert status == ("STALE_AFTER_EFFECT" if effect_started else "SUPERSEDED")
    await db.refresh(running)
    assert running.execution_result["messages"][-1]["content"] == "receipt"
    assert not await db.scalar(select(ConversationRoundMessage.message_id).where(
        ConversationRoundMessage.round_id == running.id,
        ConversationRoundMessage.role == "output",
    ))
    assert not await turn.should_interrupt()
    successor = await claim_next_round("other-worker")
    assert successor is not None
    next_turn = await build_turn(successor.id, lease_token=successor.lease_token)
    assert ("version A" in next_turn.objective) is (not effect_started)
    assert "correction B" in next_turn.objective
    assert "précision C" in next_turn.objective


@pytest.mark.asyncio
@pytest.mark.parametrize("effect_started", [False, True])
async def test_interrupted_draft_is_never_delivered_without_a_successor(
    db: AsyncSession, effect_started: bool,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "première demande")
    await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("interrupted-worker")
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    if effect_started:
        assert await turn.assert_fresh_before_effect()
    status = await complete_round(round_.id, ConversationOutcome(
        text="", metadata={"interrupted": True},
        execution_result=AIResult(prompt="", messages=[AIMessage(type="text", content="Brouillon")]),
    ), lease_token=round_.lease_token)
    assert status == ("STALE_AFTER_EFFECT" if effect_started else "INTERRUPTED")
    await db.refresh(round_)
    assert round_.status == ("SUCCEEDED" if effect_started else "FROZEN")
    links = list(await db.scalars(select(ConversationRoundMessage).where(
        ConversationRoundMessage.round_id == round_.id,
    )))
    assert len(links) == 1 and links[0].role == "input"
    assert (links[0].consumed_at is not None) is effect_started


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["dispatcher", "objective", "attachment", "history"])
async def test_preparation_interruption_preserves_inputs_and_starts_successor(committed_database, monkeypatch, phase):
    from core.database import get_db_session
    from core.user.models import User
    from app.conversation import controller, scheduler, facade, mcp
    from app.harness import conversation as harness

    entered = asyncio.Event()
    stopped = asyncio.Event()
    release = asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(controller, "run", harness.HarnessConversationController().run)
    monkeypatch.setattr(facade, "publish_round_activity", AsyncMock())
    monkeypatch.setattr(facade, "publish_runtime_event", AsyncMock())
    monkeypatch.setattr(harness, "build_conversation_session", AsyncMock(return_value=SimpleNamespace(messages=[])))
    resend = AsyncMock()
    monkeypatch.setattr("app.file_share.resource_copy", resend)
    if phase == "attachment":
        async def attachment_history(*args, **kwargs):
            entered.set()
            await release.wait()
            stopped.set()
            return SimpleNamespace(messages=[{"attachments": [{
                "local_id": str(uuid4()), "name": "rapport.pdf",
            }]}])
        monkeypatch.setattr(harness, "build_conversation_session", attachment_history)
    elif phase == "history":
        monkeypatch.setattr(harness, "build_conversation_session", blocked)
    elif phase == "objective":
        monkeypatch.setattr(mcp, "generate_task_fields", blocked)
    else:
        monkeypatch.setattr(harness, "dispatch_conversation", blocked)
    initial = "@task Prépare le rapport" if phase == "objective" else "Prépare le rapport"
    if phase == "attachment":
        initial = "Renvoie le fichier rapport.pdf déjà créé."
    async with get_db_session() as db:
        user = User(email=f"preparation-{uuid4()}@example.test", hashed_password="unused", is_active=True)
        db.add(user)
        await db.flush()
        agent, connection, room = await _scope(db, user_id=user.id)
        message = await _message(db, connection, room, 1, initial)
        await admit_message(message, agent_id=agent.id, connection_id=connection.id)
        round_ = await claim_next_round("first-worker")
        round_id, lease_token = round_.id, round_.lease_token

    work = asyncio.create_task(scheduler._execute_action(round_id, lease_token))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with get_db_session() as db:
            correction = await _message(db, connection, room, 2, "Utilise les chiffres corrigés")
            await admit_message(correction, agent_id=agent.id, connection_id=connection.id)
        release.set()
        await asyncio.wait_for(work, 3)
        assert stopped.is_set()
        resend.assert_not_awaited()
        async with get_db_session() as db:
            previous = await db.get(ConversationRound, round_id)
            assert previous.status == "SUPERSEDED"
            assert previous.effect_started is False
            assert not list(await db.scalars(select(Task).where(Task.agent_id == agent.id)))
            successor = await claim_next_round("next-worker")
            assert successor is not None
            turn = await build_turn(successor.id, lease_token=successor.lease_token)
            assert initial in turn.objective
            assert "Utilise les chiffres corrigés" in turn.objective
    finally:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)


@pytest.mark.asyncio
async def test_expired_round_heartbeat_cannot_resurrect_its_owner(db):
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "Prépare le rapport")
    await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("old-worker")
    token = round_.lease_token
    round_.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert not await renew_round_lease(round_.id, token)
    recovered = await claim_next_round("new-worker")
    assert recovered.id == round_.id and recovered.lease_token != token
    assert not await mark_effect_if_fresh(round_.id, lease_token=token)


@pytest.mark.asyncio
async def test_round_lease_renews_only_for_its_exact_owner(db: AsyncSession) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "travail en cours")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("lease-worker")
    assert round_ is not None
    assert round_.lease_token is not None
    lease_token = round_.lease_token
    previous_expiry = round_.lease_expires_at

    assert await renew_round_lease(round_.id, round_.lease_token)
    await db.refresh(round_)
    assert previous_expiry is not None
    assert round_.lease_expires_at is not None
    assert round_.lease_expires_at >= previous_expiry
    assert not await renew_round_lease(round_.id, uuid4())
    assert not await round_attempt_succeeded(round_.id, lease_token)

    assert await complete_round(
        round_.id, ConversationOutcome(text=""), lease_token=lease_token,
    ) == "SUCCEEDED"
    assert not await renew_round_lease(round_.id, lease_token)
    assert await round_attempt_succeeded(round_.id, lease_token)
    assert not await round_attempt_succeeded(round_.id, uuid4())


@pytest.mark.asyncio
async def test_successful_round_finishes_its_stream_when_heartbeat_observes_released_lease(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conversation import controller, facade, scheduler
    from app.conversation.contracts import ConversationRuntimeEvent

    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "ça va ?")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("completion-worker")
    assert round_ is not None and round_.lease_token is not None
    lease_token = round_.lease_token
    sent: list[tuple[UUID | str, str]] = []
    _install_messenger(monkeypatch, db, connection, room, sent)
    publishing = asyncio.Event()
    release_publication = asyncio.Event()
    heartbeat_finished = asyncio.Event()
    events: list[ConversationRuntimeEvent] = []
    original_heartbeat = scheduler._heartbeat_round

    @asynccontextmanager
    async def test_db_session() -> AsyncIterator[None]:
        # The action is suspended after commit while the heartbeat uses this session.
        yield

    async def publish_message(_message: Message) -> None:
        publishing.set()
        await release_publication.wait()

    async def publish_runtime_event(
        _room_id: UUID, event: ConversationRuntimeEvent,
    ) -> None:
        events.append(event)

    async def heartbeat(round_id: UUID, token: UUID) -> None:
        await publishing.wait()
        try:
            await original_heartbeat(round_id, token)
        finally:
            heartbeat_finished.set()

    monkeypatch.setattr(scheduler, "get_db_session", test_db_session)
    monkeypatch.setattr(scheduler, "_heartbeat_round", heartbeat)
    monkeypatch.setattr(controller, "run", AsyncMock(return_value=ConversationOutcome(
        text="Ça va bien !", execution_result=AIResult(prompt="ça va ?", result="Ça va bien !"),
    )))
    monkeypatch.setattr(facade, "publish_round_activity", AsyncMock())
    monkeypatch.setattr(facade, "publish_runtime_event", publish_runtime_event)
    monkeypatch.setattr(message_sent, "send_async", publish_message)
    worker = asyncio.create_task(scheduler._execute(round_.id, lease_token))
    try:
        async with asyncio.timeout(15):
            await heartbeat_finished.wait()
            # Keep publication pending while the scheduler handles the heartbeat.
            await asyncio.wait({worker}, timeout=0.1)
            release_publication.set()
            await worker
        await db.refresh(round_)
        assert round_.status == "SUCCEEDED"
        assert round_.delivery_state == "DELIVERED"
        assert sent == [(room.id, "Ça va bien !")]
        terminal = [event for event in events if event.kind == "finished"]
        assert len(terminal) == 1
        assert terminal[0].success is True
        assert terminal[0].result is not None
        assert terminal[0].result.success is True
        assert terminal[0].result.result == "Ça va bien !"
    finally:
        release_publication.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_terminal_round_reconciles_orphaned_running_llm_call(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "réponse interrompue")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("orphaned-call-worker")
    assert round_ is not None
    call = LLMCall(
        conversation_round_id=round_.id,
        agent_run_id=round_.id,
        agent_id=agent.id,
        status="running",
        stream=True,
        response_text="réponse partielle conservée",
    )
    db.add(call)
    await db.flush()
    assert await complete_round(round_.id, ConversationOutcome(text=""), lease_token=round_.lease_token) == "SUCCEEDED"

    assert await reconcile_terminal_round_llm_calls() == 1
    await db.refresh(call)
    assert call.status == "cancelled"
    assert call.completed_at is not None
    assert call.response_text == "réponse partielle conservée"
    assert "conversation round became terminal" in str(call.error)


@pytest.mark.asyncio
async def test_terminal_freshness_guard_releases_its_transaction(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "travail long")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id
    )
    round_ = await claim_next_round("terminal-guard-worker")
    assert round_ is not None
    await build_turn(round_.id, lease_token=round_.lease_token)
    assert await complete_round(
        round_.id, ConversationOutcome(text=""),
        lease_token=round_.lease_token,
    ) == "SUCCEEDED"
    assert not db.in_transaction()

    assert not await mark_effect_if_fresh(round_.id, lease_token=round_.lease_token)

    # A rejected guard used to leave SELECT ... FOR UPDATE open in the caller's
    # session, blocking every subsequent LLMCall correlated to this round.
    assert not db.in_transaction()


@pytest.mark.asyncio
async def test_successful_retry_clears_the_previous_round_error(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "réessaie")
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("retry-success-worker")
    assert round_ is not None
    round_.last_error = "Conversation round execution timed out."
    await db.commit()

    assert await complete_round(
        round_.id,
        ConversationOutcome(text=""),
        lease_token=round_.lease_token,
    ) == "SUCCEEDED"

    await db.refresh(round_)
    assert round_.status == "SUCCEEDED"
    assert round_.last_error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_mode", ["manual", "detected", "unknown", "cleared"])
async def test_completed_round_links_persisted_outgoing_message(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    topic_mode: str,
) -> None:
    agent, connection, room = await _scope(db)
    topic = Topic(title="Sujet explicite", description="", keywords=[])
    db.add(topic)
    await db.flush()
    message = await _message(db, connection, room, 1, "bonjour")
    expected_topic_id = topic.id if topic_mode in {"manual", "detected"} else None
    expected_override = topic_mode in {"manual", "cleared"}
    message.topic_id = expected_topic_id
    message.topic_overridden = expected_override
    await db.flush()
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("output-worker")
    assert round_ is not None
    assert round_.topic_id == expected_topic_id
    sent: list[tuple[UUID | str, str]] = []
    publish_events: list[bool] = []
    _install_messenger(
        monkeypatch,
        db,
        connection,
        room,
        sent,
        publish_events=publish_events,
    )

    published: list[UUID] = []

    async def observe_committed_output(message: Message) -> None:
        assert not db.in_transaction()
        link = await db.scalar(
            select(ConversationRoundMessage).where(
                ConversationRoundMessage.round_id == round_.id,
                ConversationRoundMessage.message_id == message.id,
                ConversationRoundMessage.role == "output",
            )
        )
        assert link is not None
        published.append(message.id)
        await db.commit()

    message_sent.connect(observe_committed_output)

    try:
        assert await complete_round(
            round_.id,
            ConversationOutcome(text="salut"),
            lease_token=round_.lease_token,
        ) == "SUCCEEDED"
    finally:
        message_sent.disconnect(observe_committed_output)
    assert sent == [(room.id, "salut")]
    assert publish_events == [False]
    output = await db.scalar(
        select(ConversationRoundMessage).where(
            ConversationRoundMessage.round_id == round_.id,
            ConversationRoundMessage.role == "output",
        )
    )
    assert output is not None and output.response_sequence == 1
    stored = await db.get(Message, output.message_id)
    assert stored is not None and stored.text == "salut"
    assert stored.topic_id == expected_topic_id
    assert stored.topic_overridden is expected_override
    assert stored.metadata_[CONVERSATION_ROUND_METADATA_KEY] == str(round_.id)
    assert CONVERSATION_OUTPUT_PENDING_METADATA_KEY not in stored.metadata_
    assert published == [stored.id]


def test_completed_round_uses_only_all_text_ai_messages() -> None:
    result = AIResult(
        prompt="Répondre",
        result="NE PAS UTILISER CE CHAMP",
        messages=[
            AIMessage(type="text", content="Première partie."),
            AIMessage(
                type="tool",
                tool_name="search",
                content="Détail technique masqué",
            ),
            AIMessage(type="text", content="Deuxième partie."),
        ],
    )

    assert conversation_service._conversation_response_text(  # pyright: ignore[reportPrivateUsage]
        ConversationOutcome(
            text="Réponse finale de secours",
            execution_result=result,
        )
    ) == "Première partie.\n\nDeuxième partie."


def test_completed_round_falls_back_to_outcome_text_for_tool_only_trace() -> None:
    acknowledgement = "J’ai créé et lancé la tâche « Dire bonjour »."
    result = AIResult(
        prompt="@task dis bonjour",
        result=acknowledgement,
        messages=[
            AIMessage(
                type="tool",
                tool_name="conversation_task_submit",
                content="Task admission completed",
            )
        ],
    )

    assert conversation_service._conversation_response_text(  # pyright: ignore[reportPrivateUsage]
        ConversationOutcome(
            text=acknowledgement,
            effect_started=True,
            execution_result=result,
        )
    ) == acknowledgement


@pytest.mark.asyncio
async def test_room_topic_flows_to_round_and_response_without_becoming_an_override(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    topic = Topic(title="Topic de room", description="", keywords=[])
    db.add(topic)
    await db.flush()
    room.topic_id = topic.id
    message = await _message(db, connection, room, 1, "bonjour")
    assert message.topic_id is None
    assert await admit_message(message, agent_id=agent.id, connection_id=connection.id)
    round_ = await claim_next_round("room-topic-worker")
    assert round_ is not None
    assert round_.topic_id == topic.id

    sent: list[tuple[UUID | str, str]] = []
    _install_messenger(monkeypatch, db, connection, room, sent)
    assert await complete_round(
        round_.id,
        ConversationOutcome(text="réponse"),
        lease_token=round_.lease_token,
    ) == "SUCCEEDED"
    output = await db.scalar(
        select(Message)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == round_.id,
            ConversationRoundMessage.role == "output",
        )
    )
    assert output is not None
    assert output.topic_id is None
    assert output.topic_overridden is False


@pytest.mark.asyncio
async def test_terminal_process_notification_uses_link_directly(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "lance l'export")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("process-worker")
    assert round_ is not None
    definition = ProcessDefinition(
        agent_id=agent.id,
        tool_id=connection.tool_id,
        engine_process_id=f"workflow-{uuid4()}",
        label="Export nocturne",
    )
    db.add(definition)
    await db.flush()
    run = ProcessRun(
        process_id=definition.id,
        launcher_agent_id=agent.id,
        launch_snapshot={"process_label": definition.label},
        engine_code=f"engine-{uuid4()}",
        correlation_id=f"correlation-{uuid4()}",
        callback_token=f"callback-{uuid4()}",
        status="error",
        input={},
        engine_metadata={},
        error_message="La génération du fichier a échoué.",
    )
    db.add(run)
    await db.flush()
    link = ConversationProcessLink(
        round_id=round_.id,
        process_run_id=run.id,
        action_key=f"process-{uuid4()}",
    )
    db.add(link)
    await db.commit()

    sent: list[tuple[UUID | str, str]] = []
    transaction_states: list[bool] = []
    _install_messenger(
        monkeypatch,
        db,
        connection,
        room,
        sent,
        transaction_states,
    )
    assert await claim_next_process_notification() == link.id
    await deliver_process_notification(link.id)
    await db.refresh(link)
    assert link.notification_state == "DELIVERED"
    assert link.notification_message_id is not None
    assert transaction_states == [False]
    assert sent == [
        (
            room.id,
            "Export nocturne — arrêté avec l’état error.\n\n"
            "La génération du fichier a échoué.",
        )
    ]


@pytest.mark.asyncio
async def test_terminal_task_failure_creates_message_with_redacted_cause(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "prépare le rapport")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("task-worker")
    assert round_ is not None
    task = Task(
        label="Rapport mensuel",
        objective="Préparer le rapport.",
        status=TaskStatus.ERROR,
        agent_id=agent.id,
        messenger_connection_id=connection.id,
        message_platform="telegram",
        message_group_id=room.external_id,
        attempt_count=1,
        last_error="HTTP 401 api_key=sk-live-secret123",
        execution_result={
            "prompt": "Préparer le rapport.",
            "result": "HTTP 401 api_key=sk-live-secret123",
            "success": False,
            "cost": 0.0,
        },
    )
    db.add(task)
    await db.flush()
    attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        status=TaskAttemptStatus.ERROR.value,
        worker_id="task-worker",
        lease_token=uuid4(),
        error=task.last_error,
    )
    link = ConversationTaskLink(
        round_id=round_.id,
        task_id=task.id,
        action_key=f"task-{uuid4()}",
        notification_task_attempt_count=0,
    )
    db.add_all([attempt, link])
    await db.commit()

    sent: list[tuple[UUID | str, str]] = []
    transaction_states: list[bool] = []
    _install_messenger(
        monkeypatch,
        db,
        connection,
        room,
        sent,
        transaction_states,
    )

    assert await claim_next_task_notification() == link.id
    await deliver_task_notification(link.id)
    await db.refresh(link)

    assert link.notification_state == "DELIVERED"
    assert link.notification_message_id is not None
    assert link.notification_task_attempt_count == 1
    assert transaction_states == [False]
    assert sent == [
        (
            room.id,
            "⚠️ Un problème s’est produit pendant la tâche « Rapport mensuel » et "
            "je n’ai pas pu la terminer.\n\nCause : HTTP 401 api_key=[redacted]",
        )
    ]

    task.attempt_count = 2
    retry_attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=2,
        phase=TaskStatus.DISPATCH.value,
        status=TaskAttemptStatus.ERROR.value,
        worker_id="task-worker-retry",
        lease_token=uuid4(),
        error="HTTP 503 provider unavailable",
    )
    task.last_error = retry_attempt.error
    task.execution_result = {
        "prompt": "Préparer le rapport.",
        "result": retry_attempt.error,
        "success": False,
        "cost": 0.0,
    }
    db.add(retry_attempt)
    await db.commit()

    assert await claim_next_task_notification() == link.id
    await deliver_task_notification(link.id)
    await db.refresh(link)
    assert link.notification_task_attempt_count == 2
    assert transaction_states == [False, False]
    assert len(sent) == 2
    assert "HTTP 503 provider unavailable" in sent[1][1]


@pytest.mark.asyncio
async def test_terminal_task_success_delivers_its_result_once(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "calcule")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("successful-task-worker")
    assert round_ is not None
    task = Task(
        label="Calcul",
        objective="Calcule 4 + 3.",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        messenger_connection_id=connection.id,
        message_platform="telegram",
        message_group_id=room.external_id,
        attempt_count=1,
        feedback="4 + 3 = 7.",
        execution_result={
            "prompt": "Calcule 4 + 3.",
            "result": "4 + 3 = 7.",
            "success": True,
            "cost": 0.0,
        },
    )
    db.add(task)
    await db.flush()
    db.add_all(
        [
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                phase=TaskStatus.DISPATCH.value,
                status=TaskAttemptStatus.SUCCESS.value,
                worker_id="successful-task-worker",
                lease_token=uuid4(),
            ),
            ConversationTaskLink(
                round_id=round_.id,
                task_id=task.id,
                action_key=f"task-{uuid4()}",
                notification_task_attempt_count=0,
            ),
        ]
    )
    await db.commit()

    sent: list[tuple[UUID | str, str]] = []
    transaction_states: list[bool] = []
    _install_messenger(
        monkeypatch,
        db,
        connection,
        room,
        sent,
        transaction_states,
    )

    link = await db.scalar(
        select(ConversationTaskLink).where(ConversationTaskLink.task_id == task.id)
    )
    assert link is not None
    assert await claim_next_task_notification() == link.id
    await deliver_task_notification(link.id)
    await db.refresh(link)

    assert sent == [(room.id, "4 + 3 = 7.")]
    assert transaction_states == [False]
    assert link.notification_state == "DELIVERED"
    assert link.notification_message_id is not None
    assert link.notification_task_attempt_count == 1
    assert await claim_next_task_notification() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("already_uploaded", [False, True])
async def test_terminal_task_copies_presented_provider_file_to_origin_room(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    already_uploaded: bool,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "crée une page")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("artifact-task-worker")
    assert round_ is not None
    source_uri = "nextcloud://foreign-room/attachment-12"
    working_set = WorkingSet(
        resources=[
            WorkingResource(
                resource_type="artifact",
                role="final_artifact",
                reference=source_uri,
                label="index.html",
                metadata={
                    "source": "console://index.html",
                    "delivery_destination": "other-user",
                    "delivered": True,
                },
            ),
            WorkingResource(
                resource_type="delivery_receipt",
                role="delivery_receipt:console://index.html",
                reference="messenger_send_file_to_user:other-user:console://index.html",
                label="index.html",
                metadata={
                    "destination": "other-user",
                    "filename": "console://index.html",
                    "uri": source_uri,
                    "tool": "messenger_send_file_to_user",
                },
            ),
        ]
    )
    task = Task(
        label="Page HTML",
        objective="Crée index.html.",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        messenger_connection_id=connection.id,
        message_platform="internal",
        message_group_id=room.external_id,
        attempt_count=1,
        data={
            "origin": "conversation",
            "working_set": working_set.model_dump(mode="json"),
        },
        execution_result={
            "prompt": "Crée index.html.",
            "result": f"Votre fichier : {source_uri}",
            "success": True,
            "cost": 0.0,
        },
    )
    db.add(task)
    await db.flush()
    link = ConversationTaskLink(
        round_id=round_.id,
        task_id=task.id,
        action_key=f"task-{uuid4()}",
        notification_task_attempt_count=0,
    )
    db.add_all(
        [
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                phase=TaskStatus.DISPATCH.value,
                status=TaskAttemptStatus.SUCCESS.value,
                worker_id="artifact-task-worker",
                lease_token=uuid4(),
            ),
            link,
        ]
    )
    await db.commit()

    if already_uploaded:
        from app.file_share import ResourceContext, resource_create
        from app.file_share import resource_service
        from app.file_share.messenger_transport import MessengerFileTransport

        uploaded_id = uuid4()
        upload = AsyncMock(return_value=SimpleNamespace(
            id=uuid4(), room=room,
            files=[SimpleNamespace(id=uploaded_id, name="index.html")],
        ))
        transport = MessengerFileTransport(SimpleNamespace(upload_file_path=upload))
        monkeypatch.setattr(resource_service, "resolve_resource_transport_with_service",
                            AsyncMock(return_value=(transport, "messenger")))
        mutation = await resource_create(
            ResourceContext(agent_id=agent.id, runtime="hermes", task_id=task.id),
            f"chat-test://{room.id}/index.html", b"<html>page</html>",
        )
        source_uri = mutation.uri
        task.execution_result = {**task.execution_result, "result": f"Votre fichier : {source_uri}"}
        # The image tool returns the URI without a generic artifact effect. Only
        # the receipt written by resource_create proves delivery after a reload.
        from app.file_share import ResourceDescriptor
        monkeypatch.setattr("app.conversation.artifact_delivery.resource_info", AsyncMock(
            return_value=ResourceDescriptor(uri=source_uri, name="index.html")))
        await db.commit()
        await db.refresh(task)
        assert upload.await_count == 1

    sent: list[tuple[UUID | str, str]] = []
    _install_messenger(monkeypatch, db, connection, room, sent)
    delivery = AsyncMock(
        return_value=DeliveredResource(
            source_uri=source_uri,
            uri=f"chat-test://{room.external_id}/copied-attachment",
            name="index.html",
            media_type="text/html",
            size=42,
        )
    )
    import app.file_share as file_share_package

    monkeypatch.setattr(
        file_share_package,
        "deliver_resource_to_messenger",
        delivery,
    )

    assert await claim_next_task_notification() == link.id
    await deliver_task_notification(link.id)
    await db.refresh(task)
    await db.refresh(link)

    assert sent == [(room.id, "Votre fichier : index.html")]
    assert delivery.await_count == (0 if already_uploaded else 1)
    if not already_uploaded:
        resource_ctx, _messenger, target_room, delivered_source = delivery.await_args.args
        assert resource_ctx.task_id == task.id
        assert target_room == room.id
        assert delivered_source == source_uri
    receipts = [
        item
        for item in parse_working_set(task).active()
        if item.resource_type == "delivery_receipt"
        and item.metadata.get("tool") == "conversation_task_notification"
    ]
    assert len(receipts) == (0 if already_uploaded else 1)
    if receipts:
        assert receipts[0].metadata["destination_room_id"] == str(room.id)
        assert receipts[0].metadata["connection_id"] == connection.id
    assert link.notification_state == "DELIVERED"


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered_text", ["résultat", "progression"])
async def test_terminal_task_success_skips_only_an_already_delivered_result(
    db: AsyncSession,
    delivered_text: str,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "travaille")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round(f"delivery-proof-{delivered_text}")
    assert round_ is not None
    result_text = "Travail terminé."
    sent_text = result_text if delivered_text == "résultat" else "Je commence."
    task = Task(
        label="Travail",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        attempt_count=1,
        execution_result={
            "prompt": "Travaille.",
            "result": result_text,
            "success": True,
            "cost": 0.0,
            "messages": [
                {
                    "type": "tool",
                    "tool_name": "messenger_room_send_message",
                    "tool_arguments": {
                        "room_id": room.external_id,
                        "message": sent_text,
                    },
                    "content": "Message envoyé.",
                    "success": True,
                }
            ],
        },
    )
    db.add(task)
    await db.flush()
    link = ConversationTaskLink(
        round_id=round_.id,
        task_id=task.id,
        action_key=f"task-{uuid4()}",
        notification_task_attempt_count=0,
    )
    db.add_all(
        [
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                phase=TaskStatus.DISPATCH.value,
                status=TaskAttemptStatus.SUCCESS.value,
                worker_id="delivery-proof-worker",
                lease_token=uuid4(),
            ),
            link,
        ]
    )
    await db.commit()

    claimed = await claim_next_task_notification()
    await db.refresh(link)
    if delivered_text == "résultat":
        assert claimed is None
        assert link.notification_state == "SKIPPED"
        assert link.notification_task_attempt_count == 1
    else:
        assert claimed == link.id
        assert link.notification_state == "SENDING"


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", [TaskStatus.EXEC, TaskStatus.SUCCESS, TaskStatus.ERROR])
async def test_conversation_stop_preserves_terminal_state_on_repeated_request(
    db: AsyncSession, initial_status: TaskStatus,
) -> None:
    from app.conversation import ConversationTurn
    from app.conversation.mcp import conversation_task_stop
    from app.tools import McpToolContext

    agent, connection, room = await _scope(db)
    task = Task(
        label="Travail à arrêter",
        status=initial_status,
        agent_id=agent.id,
        last_error="Cause initiale" if initial_status == TaskStatus.ERROR else None,
        execution_result={"prompt": "", "result": "Résultat conservé", "success": True},
        data={"receipt": "existing-effect"},
    )
    db.add(task)
    await db.commit()
    before = (task.revision, task.last_error, task.updated_at)
    ctx = McpToolContext(
        agent_id=agent.id,
        runtime="internal",
        resources={"conversation_turn": ConversationTurn(
            room_id=room.id, round_id=uuid4(), agent_id=agent.id, language="fr",
            objective="Arrête cette tâche", messages=(),
            messaging_context={"connection_id": connection.id, "room_id": room.external_id},
        )},
    )

    first = await conversation_task_stop(ctx, task_id=f"galaris://task/{task.id}")
    await db.commit()
    await db.refresh(task)
    after_first = (task.revision, task.last_error, task.updated_at)
    second = await conversation_task_stop(ctx, task_id=f"galaris://task/{task.id}")
    await db.commit()
    await db.refresh(task)

    expected = TaskStatus.ERROR if initial_status == TaskStatus.EXEC else initial_status
    assert first["status"] == second["status"] == expected.value
    assert first["operational_state"] == second["operational_state"] == "TERMINAL"
    assert first["result"] == second["result"] == "Résultat conservé"
    assert task.status == expected
    assert task.data == {"receipt": "existing-effect"}
    assert (task.revision, task.last_error, task.updated_at) == after_first
    if initial_status != TaskStatus.EXEC:
        assert after_first == before

    # A terminal state must not bypass the agent scope check.
    other_agent, _, _ = await _scope(db)
    other_ctx = McpToolContext(
        agent_id=other_agent.id, runtime="internal", resources=ctx.resources,
    )
    with pytest.raises(ValueError, match="Task not found for this agent"):
        await conversation_task_stop(other_ctx, task_id=f"galaris://task/{task.id}")


@pytest.mark.asyncio
async def test_cancelled_task_does_not_create_failure_notification(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "lance puis arrête")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("cancelled-task-worker")
    assert round_ is not None
    task = Task(
        label="Tâche arrêtée",
        status=TaskStatus.ERROR,
        agent_id=agent.id,
        attempt_count=1,
    )
    db.add(task)
    await db.flush()
    db.add_all(
        [
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                phase=TaskStatus.DISPATCH.value,
                status=TaskAttemptStatus.CANCELLED.value,
                worker_id="cancelled-task-worker",
                lease_token=uuid4(),
            ),
            ConversationTaskLink(
                round_id=round_.id,
                task_id=task.id,
                action_key=f"task-{uuid4()}",
            ),
        ]
    )
    await db.commit()

    assert await claim_next_task_notification() is None


@pytest.mark.asyncio
async def test_historical_task_failure_is_not_notified_retroactively(
    db: AsyncSession,
) -> None:
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "ancien travail")
    assert await admit_message(
        message, agent_id=agent.id, connection_id=connection.id, language="fr"
    )
    round_ = await claim_next_round("historical-task-worker")
    assert round_ is not None
    task = Task(
        label="Ancienne tâche en échec",
        status=TaskStatus.ERROR,
        agent_id=agent.id,
        attempt_count=1,
    )
    db.add(task)
    await db.flush()
    db.add_all(
        [
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                phase=TaskStatus.DISPATCH.value,
                status=TaskAttemptStatus.ERROR.value,
                worker_id="historical-task-worker",
                lease_token=uuid4(),
                error="ancienne erreur",
            ),
            ConversationTaskLink(
                round_id=round_.id,
                task_id=task.id,
                action_key=f"task-{uuid4()}",
                notification_task_attempt_count=None,
            ),
        ]
    )
    await db.commit()

    assert await claim_next_task_notification() is None


@pytest.mark.asyncio
async def test_unknown_delivery_can_be_resolved_once_without_replaying_effects(db):
    from app.conversation.management_service import resolve_unknown_delivery, DeliveryResolutionConflict
    from app.conversation.models import ConversationDeliveryResolution
    from core.user.models import User

    _, _, room = await _scope(db)
    actor = User(email=f"resolution-{uuid4()}@example.test", display_name="Operator", hashed_password="unused", is_active=True)
    db.add(actor)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state="UNKNOWN", effect_started=True)
    db.add(round_)
    await db.commit()
    arguments = dict(actor_user_id=actor.id, decision="DELIVERED", evidence="Verified message in recipient channel")
    await resolve_unknown_delivery(round_.id, **arguments)
    await resolve_unknown_delivery(round_.id, **arguments)
    assert round_.status == "SUCCEEDED"
    assert round_.delivery_state == "DELIVERED"
    assert round_.effect_started is True
    records = list(await db.scalars(select(ConversationDeliveryResolution).where(ConversationDeliveryResolution.round_id == round_.id)))
    assert len(records) == 1
    assert records[0].actor_user_id == actor.id
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_delivery(round_.id, actor_user_id=actor.id, decision="SKIPPED", evidence="Contradictory late resolution")


@pytest.mark.asyncio
async def test_active_delivery_cannot_be_resolved_by_operator(db):
    from app.conversation.management_service import resolve_unknown_delivery, DeliveryResolutionConflict
    _, _, room = await _scope(db)
    round_ = ConversationRound(room_id=room.id, status="RUNNING", delivery_state="SENDING", lease_token=uuid4())
    db.add(round_)
    await db.flush()
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_delivery(round_.id, actor_user_id=1, decision="SKIPPED", evidence="Still in flight and not resolvable")
    assert round_.delivery_state == "SENDING"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "process"])
@pytest.mark.parametrize("decision", ["DELIVERED", "SKIPPED"])
async def test_notification_resolution_is_scoped_versioned_and_does_not_replay_work(db, kind, decision):
    from app.conversation.management_service import resolve_unknown_notification, DeliveryResolutionConflict
    from app.conversation.models import ConversationNotificationResolution
    from app.conversation.monitoring_service import get_round
    from core.user.models import User

    agent, connection, room = await _scope(db)
    actor = User(email=f"notification-{uuid4()}@example.test", display_name="Operator", hashed_password="unused", is_active=True)
    round_ = ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state="DELIVERED")
    db.add_all([actor, round_])
    await db.flush()
    if kind == "task":
        work = Task(label="Completed work", status=TaskStatus.ERROR, feedback="Preserved result")
        db.add(work)
        await db.flush()
        link = ConversationTaskLink(round_id=round_.id, task_id=work.id, action_key="notification")
    else:
        definition = ProcessDefinition(agent_id=agent.id, tool_id=connection.tool_id,
                                       engine_process_id=f"workflow-{uuid4()}", label="Completed work")
        db.add(definition)
        await db.flush()
        work = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id,
                          engine_code="test", correlation_id=str(uuid4()), callback_token="test",
                          status="error", input={}, engine_metadata={}, error_message="Preserved result")
        db.add(work)
        await db.flush()
        link = ConversationProcessLink(round_id=round_.id, process_run_id=work.id, action_key="notification")
    work_status = work.status
    link.notification_state = "UNKNOWN"
    link.notification_attempt_count = 2
    db.add(link)
    await db.commit()
    detail = await get_round(round_.id)
    assert detail is not None
    assert [(item.kind, item.link_id, item.target_id, item.attempt_number) for item in detail.unknown_notifications] == [(kind, link.id, work.id, 2)]
    arguments = dict(kind=kind, link_id=link.id, attempt_number=2, actor_user_id=actor.id,
                     decision=decision, evidence="Verified in the destination channel")
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_notification(uuid4(), **arguments)
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_notification(round_.id, **{**arguments, "attempt_number": 1})
    link.notification_lease_token = uuid4()
    await db.flush()
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_notification(round_.id, **arguments)
    link.notification_lease_token = None
    await db.flush()
    await resolve_unknown_notification(round_.id, **arguments)
    await resolve_unknown_notification(round_.id, **arguments)
    assert link.notification_state == decision
    assert work.status == work_status
    assert round_.delivery_state == "DELIVERED"
    assert not (await get_round(round_.id)).unknown_notifications
    receipt = (await db.scalars(select(ConversationNotificationResolution))).one()
    assert receipt.actor_user_id == actor.id
    assert receipt.evidence == arguments["evidence"]
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_notification(round_.id, **{**arguments, "decision": "SKIPPED" if decision == "DELIVERED" else "DELIVERED"})
    # A later explicit retry is a distinct delivery; a stale dialog cannot resolve it.
    link.notification_attempt_count = 3
    link.notification_state = "UNKNOWN"
    await db.commit()
    with pytest.raises(DeliveryResolutionConflict):
        await resolve_unknown_notification(round_.id, **arguments)
    await resolve_unknown_notification(round_.id, **{**arguments, "attempt_number": 3})
    assert len(list(await db.scalars(select(ConversationNotificationResolution)))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "process"])
async def test_remote_success_before_local_commit_recovers_unknown_without_resend(db, monkeypatch, kind):
    """The remote effect cannot be rolled back when recording its receipt fails."""
    from datetime import timedelta
    from sqlalchemy import update
    import app.messenger as messenger_package

    agent, connection, room = await _scope(db)
    round_ = ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state="DELIVERED")
    db.add(round_)
    await db.flush()
    if kind == "task":
        work = Task(label="Durable result", agent_id=agent.id, status=TaskStatus.ERROR,
                    attempt_count=1, last_error="Preserved error")
        db.add(work)
        await db.flush()
        db.add(TaskAttempt(task_id=work.id, attempt_number=1, phase="DISPATCH", status="ERROR",
                           worker_id="crashed", lease_token=uuid4()))
        link = ConversationTaskLink(round_id=round_.id, task_id=work.id, action_key="crash",
                                    notification_task_attempt_count=1)
        deliver = deliver_task_notification
        claim = claim_next_task_notification
    else:
        definition = ProcessDefinition(agent_id=agent.id, tool_id=connection.tool_id,
                                       engine_process_id=uuid4().hex, label="Durable result")
        db.add(definition)
        await db.flush()
        work = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code="test",
                          correlation_id=uuid4().hex, callback_token="test", status="error",
                          input={}, engine_metadata={}, error_message="Preserved error")
        db.add(work)
        await db.flush()
        link = ConversationProcessLink(round_id=round_.id, process_run_id=work.id, action_key="crash")
        deliver = deliver_process_notification
        claim = claim_next_process_notification
    link.notification_state = "SENDING"
    link.notification_lease_token = uuid4()
    link.notification_lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    link.notification_attempt_count = 1
    db.add(link)
    await db.commit()
    link_id = link.id
    sent = []

    async def remote_send(destination, text):
        sent.append((destination, text))
        return SimpleNamespace(id="remote-receipt")

    monkeypatch.setattr(messenger_package, "get_messenger", AsyncMock(return_value=SimpleNamespace(send_to_room=remote_send)))
    commit = db.commit

    async def failing_commit():
        if sent:
            raise ConnectionError("Connection lost before local receipt commit")
        await commit()

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", failing_commit)
        with pytest.raises(ConnectionError, match="local receipt"):
            await deliver(link_id)
    await db.rollback()
    # A new worker finds only the durable SENDING lease, not the returned remote receipt.
    await db.execute(update(type(link)).where(type(link).id == link_id).values(
        notification_lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    await db.commit()
    assert await claim() is None
    stored = await db.get(type(link), link_id, populate_existing=True)
    assert stored.notification_state == "UNKNOWN"
    assert stored.notification_message_id is None
    await deliver(link_id)
    assert await claim() is None
    assert len(sent) == 1
