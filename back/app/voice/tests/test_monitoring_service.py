from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.llm import LLMCall
from app.messenger import (
    ConversationType,
    MessengerUser,
    Room,
    RoomUser,
    voice_journal,
)
from app.tools import ToolModel
from app.topic import Topic
from app.voice import (
    conversation_service,
    inspection_service,
    management_service,
    monitoring_service,
)
from app.voice.models import VoiceConversationSession, VoiceConversationStatus
from core.authorize import Privileges


async def _agent(db: AsyncSession, *, user_id: int | None = None) -> Agent:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Voice monitoring {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        user_id=user_id,
        title_id=title.id,
        first_name="Alice",
        last_name="Voice",
        code=f"voice-monitoring-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _session(
    db: AsyncSession,
    *,
    agent: Agent,
    transport_kind: str,
    room_id: str,
):
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == transport_kind))
    if tool is None:
        tool = ToolModel(
            code=transport_kind,
            label=f"Voice monitoring {transport_kind}",
            description="",
            connection_schema={},
        )
        db.add(tool)
        await db.flush()
    connection = await db.scalar(
        select(Connection).where(
            Connection.tool_id == tool.id,
            Connection.agent_id == agent.id,
        )
    )
    if connection is None:
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=room_id,
        label=room_id,
        kind="direct",
        conversation_type=ConversationType.AUDIO.value,
    )
    db.add(room)
    await db.flush()
    caller = MessengerUser(
        tool_id=tool.id,
        external_id=f"caller-{room_id}",
        display_name="Nicolas",
        is_ai=False,
    )
    db.add(caller)
    await db.flush()
    db.add(RoomUser(room_id=room.id, user_id=caller.id))
    session = VoiceConversationSession(
        messenger_room_id=room.id,
        status=VoiceConversationStatus.ACTIVE.value,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.commit()
    return session


@pytest.mark.asyncio
async def test_voice_monitoring_lists_and_details_transcribed_turns(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_messenger(connection_id: int):
        connection = await db.get(Connection, connection_id)
        assert connection is not None
        tool = await db.get(ToolModel, connection.tool_id)
        assert tool is not None
        return SimpleNamespace(tool_id=tool.id, self_id=None, kind=tool.code)

    monkeypatch.setattr(voice_journal, "get_messenger", get_messenger)
    agent = await _agent(db)
    session = await _session(
        db,
        agent=agent,
        transport_kind="nextcloud_talk",
        room_id="room-audit",
    )
    interrupted = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Peux-tu vérifier la météo ?",
        run_id=uuid4(),
    )
    await conversation_service.record_turn_input(
        interrupted.id,
        "Peux-tu vérifier la météo ?",
    )
    await conversation_service.record_turn_outputs(interrupted.id, ("Je vérifie",))
    await conversation_service.interrupt_turn(
        interrupted.id,
        assistant_response="Je vérifie",
    )
    completed = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Et prends Caen comme ville.",
        run_id=uuid4(),
    )
    await conversation_service.record_turn_input(
        completed.id,
        "Et prends Caen comme ville.",
    )
    await conversation_service.record_turn_outputs(
        completed.id,
        ("Il fera beau à Caen.",),
    )
    await conversation_service.complete_turn(
        completed.id,
        assistant_response="Il fera beau à Caen.",
        execution_result={
            "prompt": completed.effective_objective or "",
            "system_prompt": "Tu es Alice Voice.",
            "messages": [
                {
                    "type": "tool",
                    "tool_name": "weather_get",
                    "content": "18 °C",
                }
            ],
            "result": "Il fera beau à Caen.",
            "success": True,
        },
    )
    await conversation_service.finish_session(
        session.id,
        VoiceConversationStatus.COMPLETED,
    )
    topic = Topic(title="Weather in Caen")
    db.add(topic)
    await db.flush()
    interrupted.topic_id = topic.id
    completed.topic_id = topic.id
    db.add(
        LLMCall(
            conversation_round_id=completed.id,
            agent_run_id=completed.id,
            agent_id=agent.id,
            provider_name="test",
            requested_model="test-model",
            effective_model="test-model",
            status="completed",
            request_messages=[],
            prompt="",
            system_prompt="",
            response_text="Il fera beau à Caen.",
            reasoning="",
            tool_calls=[],
            usage={},
        )
    )
    await db.commit()

    page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        search="Caen",
        status=VoiceConversationStatus.COMPLETED.value,
    )

    assert page.total == 1
    assert page.items[0].id == session.id
    assert page.items[0].agent_name == "Alice Voice"
    assert page.items[0].caller_name == "Nicolas"
    assert page.items[0].transport_kind == "nextcloud_talk"
    assert page.items[0].turn_count == 2
    assert page.items[0].interrupted_count == 1
    assert page.items[0].failed_count == 0
    assert [turn.sequence for turn in page.items[0].turns] == [1, 2]
    assert page.items[0].turns[1].llm_call_count == 1
    assert all(turn.topic_id == topic.id for turn in page.items[0].turns)
    assert page.summary.completed == 1

    topic_page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        topic_id=topic.id,
    )
    assert topic_page.total == 1

    detail = await monitoring_service.get_conversation(session.id)

    assert detail is not None
    assert [turn.sequence for turn in detail.turns] == [1, 2]
    assert detail.turns[0].assistant_response == "Je vérifie"
    assert detail.turns[1].transcript == "Et prends Caen comme ville."
    assert detail.turns[1].effective_objective == (
        "Peux-tu vérifier la météo ?\nEt prends Caen comme ville."
    )
    assert detail.turns[1].llm_call_count == 1
    turn_detail = await monitoring_service.get_turn(completed.id)
    assert turn_detail is not None
    assert turn_detail.session_id == session.id
    assert turn_detail.agent_name == "Alice Voice"
    assert turn_detail.caller_name == "Nicolas"
    assert turn_detail.llm_call_count == 1
    assert turn_detail.execution_result is not None
    assert turn_detail.execution_result["system_prompt"] == "Tu es Alice Voice."
    replacement_topic = Topic(title="Updated weather in Caen")
    db.add(replacement_topic)
    await db.commit()
    assert await management_service.update_turn_topic(completed.id, replacement_topic.id)
    updated_turn = await monitoring_service.get_turn(completed.id)
    assert updated_turn is not None
    assert updated_turn.topic_id == replacement_topic.id
    dataset = await inspection_service.inspect_turn(completed.id)
    assert dataset is not None
    assert dataset["turn"]["id"] == str(completed.id)
    assert dataset["turn"]["run_id"] == str(completed.id)
    assert dataset["session"]["id"] == str(session.id)
    assert dataset["agent"]["id"] == agent.id
    assert len(dataset["llm_calls"]) == 1
    assert dataset["llm_calls"][0]["conversation_round_id"] == str(completed.id)


@pytest.mark.asyncio
async def test_terminal_voice_turn_can_be_deleted_without_deleting_llm_audit(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    session = await _session(
        db,
        agent=agent,
        transport_kind="matrix",
        room_id="delete-voice-turn",
    )
    turn = await conversation_service.start_turn(
        session_id=session.id,
        transcript="À supprimer",
        run_id=uuid4(),
    )
    await conversation_service.complete_turn(turn.id, assistant_response="Réponse")
    call = LLMCall(
        conversation_round_id=turn.id,
        agent_run_id=turn.id,
        agent_id=agent.id,
        provider_name="test",
        requested_model="test-model",
        effective_model="test-model",
        status="completed",
        request_messages=[],
        prompt="",
        system_prompt="",
        response_text="Réponse",
        reasoning="",
        tool_calls=[],
        usage={},
    )
    db.add(call)
    await db.commit()

    assert await management_service.delete_turn(turn.id)
    assert await monitoring_service.get_turn(turn.id) is None
    await db.refresh(call)
    assert call.conversation_round_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "round_status", ["RUNNING", "CLAIMED", "WAITING_APPROVAL", "INTERRUPTED", "FAILED", "COMPLETED"]
)
@pytest.mark.parametrize("session_status", ["ACTIVE", "COMPLETED", "ERROR"])
async def test_voice_turn_deletion_is_idempotent_in_every_state(
    db: AsyncSession,
    round_status: str,
    session_status: str,
) -> None:
    agent = await _agent(db)
    session = await _session(
        db,
        agent=agent,
        transport_kind="matrix",
        room_id="active-voice-turn",
    )
    turn = await conversation_service.start_turn(
        session_id=session.id,
        transcript="Toujours actif",
        run_id=uuid4(),
    )

    turn.status = round_status
    session.status = session_status
    await db.commit()
    assert await management_service.delete_turn(turn.id)
    assert await management_service.delete_turn(turn.id)
    assert await monitoring_service.get_turn(turn.id) is None
    with pytest.raises(LookupError):
        await conversation_service.record_turn_outputs(turn.id, ("Late callback",))
    with pytest.raises(RuntimeError):
        await conversation_service.start_turn(
            session_id=session.id, transcript="Late input", run_id=uuid4()
        )


@pytest.mark.asyncio
async def test_voice_monitoring_filters_by_agent_and_transport(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    first = await _session(
        db,
        agent=agent,
        transport_kind="matrix",
        room_id="matrix-room",
    )
    await _session(
        db,
        agent=agent,
        transport_kind="nextcloud_talk",
        room_id="talk-room",
    )

    page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        agent_id=agent.id,
        transport_kind="matrix",
    )

    assert page.total == 1
    assert page.items[0].id == first.id
    assert page.summary.active == 1


@pytest.mark.asyncio
async def test_voice_monitoring_summary_ignores_only_the_status_filter(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    active = await _session(
        db,
        agent=agent,
        transport_kind="matrix",
        room_id="active-room",
    )
    completed = await _session(
        db,
        agent=agent,
        transport_kind="matrix",
        room_id="completed-room",
    )
    await conversation_service.finish_session(
        completed.id,
        VoiceConversationStatus.COMPLETED,
    )

    page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        agent_id=agent.id,
        status=VoiceConversationStatus.ACTIVE.value,
    )

    assert page.total == 1
    assert page.items[0].id == active.id
    assert page.summary.active == 1
    assert page.summary.completed == 1
    assert page.summary.cancelled == 0
    assert page.summary.errors == 0

    active_page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        agent_id=agent.id,
        active=True,
    )
    history_page = await monitoring_service.list_conversations(
        page=1,
        page_size=50,
        agent_id=agent.id,
        active=False,
    )
    assert [item.id for item in active_page.items] == [active.id]
    assert [item.id for item in history_page.items] == [completed.id]


@pytest.mark.asyncio
async def test_voice_monitoring_detail_exposes_session_startup_error(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    session = await _session(
        db,
        agent=agent,
        transport_kind="nextcloud_talk",
        room_id="realtime-quota-error",
    )
    await conversation_service.finish_session(
        session.id,
        VoiceConversationStatus.ERROR,
        error="OpenAI Realtime error: insufficient_quota",
    )

    detail = await monitoring_service.get_conversation(session.id)

    assert detail is not None
    assert detail.status == VoiceConversationStatus.ERROR.value
    assert detail.error == "OpenAI Realtime error: insufficient_quota"
    assert detail.turns == []


def test_voice_monitoring_routes_require_task_access() -> None:
    from app.voice.router import (
        export_voice_conversation_turn,
        read_voice_conversation,
        read_voice_conversation_turn,
        read_voice_conversations,
    )

    for endpoint in (
        read_voice_conversation,
        read_voice_conversation_turn,
        export_voice_conversation_turn,
        read_voice_conversations,
    ):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.TASK_ACCESS
        ]

    from app.voice.router import (
        delete_voice_conversation_turn,
        force_hangup_voice_conversation_turn,
        update_voice_conversation_turn_topic,
    )

    for endpoint in (
        delete_voice_conversation_turn,
        force_hangup_voice_conversation_turn,
        update_voice_conversation_turn_topic,
    ):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.TASK_EDIT
        ]


@pytest.mark.asyncio
async def test_voice_monitoring_rejects_unauthenticated_requests(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/voice/conversations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_pending_teardown_is_durable_and_retryable(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.voice import runtime_control

    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="pending-delete")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Stop", run_id=uuid4()
    )

    async def pending(_session_id: UUID) -> bool:
        return False

    monkeypatch.setattr(runtime_control, "session_stopped", pending)
    with pytest.raises(management_service.VoiceTurnConflictError, match="enregistrée"):
        await management_service.delete_turn(turn.id)
    await db.refresh(turn)
    await db.refresh(session)
    assert turn.status == "CANCELLED"
    assert session.status == "CANCELLED"
    assert turn.lease_token is None
    assert turn.encrypted_checkpoint is None
    with pytest.raises(PermissionError):
        await conversation_service.record_turn_outputs(turn.id, ("late",))

    async def stopped(_session_id: UUID) -> bool:
        return True

    monkeypatch.setattr(runtime_control, "session_stopped", stopped)
    assert await management_service.delete_turn(turn.id)


@pytest.mark.asyncio
async def test_session_finish_closes_orphan_running_turn(db: AsyncSession) -> None:
    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="orphan-round")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Active", run_id=uuid4()
    )
    await conversation_service.finish_session(session.id, VoiceConversationStatus.COMPLETED)
    await db.refresh(turn)
    assert turn.status == "INTERRUPTED"
    assert turn.finished_at is not None
    assert turn.encrypted_checkpoint is None
    assert await management_service.delete_turn(turn.id)


@pytest.mark.asyncio
async def test_pending_teardown_keeps_durable_fence_and_can_be_retried(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.voice import runtime_control
    from app.conversation import ConversationRound
    from unittest.mock import AsyncMock

    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="pending-stop")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Hello", run_id=uuid4()
    )
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=False))
    with pytest.raises(management_service.VoiceTurnConflictError, match="enregistrée"):
        await management_service.delete_turn(turn.id)
    await db.refresh(session)
    persisted = await db.get(ConversationRound, turn.id, populate_existing=True)
    assert persisted is not None
    assert persisted.status == "CANCELLED"
    assert persisted.lease_token is None
    assert persisted.encrypted_checkpoint is None
    assert session.status == "CANCELLED"
    with pytest.raises(PermissionError):
        await conversation_service.record_turn_outputs(turn.id, ("Late output",))
    await conversation_service.complete_turn(turn.id, assistant_response="Late response")
    await db.refresh(persisted)
    assert persisted.status == "CANCELLED"
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=True))
    assert await management_service.delete_turn(turn.id)
    assert await db.get(ConversationRound, turn.id, populate_existing=True) is None


@pytest.mark.asyncio
async def test_session_close_interrupts_running_round(db: AsyncSession) -> None:
    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="close-running")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Hello", run_id=uuid4()
    )
    await conversation_service.finish_session(session.id, VoiceConversationStatus.COMPLETED)
    await db.refresh(turn)
    assert turn.status == "INTERRUPTED"
    assert turn.finished_at is not None
    assert turn.encrypted_checkpoint is None
    assert turn.lease_token is None


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [False, True])
async def test_force_hangup_retains_history_releases_room_and_fences_late_writes(
    db: AsyncSession,
    closed: bool,
) -> None:
    from app.conversation import ConversationRound

    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id=f"hangup-{closed}")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Hello", run_id=uuid4()
    )
    old_lease = uuid4()
    turn.lease_token = old_lease
    if closed:
        session.status = "COMPLETED"
        session.finished_at = datetime.now(timezone.utc)
    await db.commit()
    result = await management_service.force_hangup(turn.id)
    assert result is not None and result["revoked"] is True
    assert result["interrupted_round_ids"] == [str(turn.id)]
    await db.refresh(turn)
    await db.refresh(session)
    assert turn.status == "INTERRUPTED"
    assert turn.lease_token is None
    assert turn.encrypted_checkpoint is None
    assert session.status == ("COMPLETED" if closed else "CANCELLED")
    with pytest.raises(PermissionError):
        await conversation_service.record_turn_outputs(turn.id, ("Late",))
    with pytest.raises(PermissionError):
        await conversation_service.save_turn_checkpoint(turn.id, {"late": True})
    await conversation_service.complete_turn(turn.id, assistant_response="Late")
    await db.refresh(turn)
    assert turn.status == "INTERRUPTED"
    again = await management_service.force_hangup(turn.id)
    assert again is not None and again["interrupted_round_ids"] == []
    assert await db.get(ConversationRound, turn.id) is not None
    # Same room accepts another processing round after restart (no local registry).
    successor = ConversationRound(room_id=turn.room_id, status="RUNNING")
    db.add(successor)
    await db.commit()
    assert successor.id != turn.id


@pytest.mark.asyncio
async def test_force_hangup_reports_pending_teardown_but_releases_round(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock
    from app.voice import runtime_control

    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="hangup-pending")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Hello", run_id=uuid4()
    )
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=False))
    result = await management_service.force_hangup(turn.id)
    assert result is not None and result["local_audio_stopped"] is False
    await db.refresh(turn)
    assert turn.status == "INTERRUPTED"
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=True))
    result = await management_service.force_hangup(turn.id)
    assert result is not None and result["local_audio_stopped"] is True


@pytest.mark.asyncio
async def test_force_hangup_serializes_with_concurrent_finalization(
    inference_db: AsyncSession, committed_database
) -> None:
    import asyncio
    from core.database.database import db_session_ctx

    db = inference_db
    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="hangup-race")
    turn = await conversation_service.start_turn(
        session_id=session.id, transcript="Concurrent", run_id=uuid4()
    )
    turn_id = turn.id
    session_id = session.id
    await db.commit()

    async def finish() -> None:
        async with committed_database() as worker_db:
            token = db_session_ctx.set(worker_db)
            try:
                await conversation_service.complete_turn(turn_id, assistant_response="Late")
                await worker_db.commit()
            finally:
                db_session_ctx.reset(token)

    async def hangup() -> None:
        async with committed_database() as worker_db:
            token = db_session_ctx.set(worker_db)
            try:
                result = await management_service.force_hangup(turn_id)
                assert result is not None and result["revoked"]
                await worker_db.commit()
            finally:
                db_session_ctx.reset(token)

    await asyncio.wait_for(asyncio.gather(finish(), hangup(), hangup()), timeout=10)
    await db.refresh(turn)
    await db.refresh(session)
    assert session.id == session_id and session.status == "CANCELLED"
    assert turn.status in ("COMPLETED", "INTERRUPTED")
    assert turn.lease_token is None
    with pytest.raises(PermissionError):
        await conversation_service.record_turn_outputs(turn_id, ("Post-revocation",))


@pytest.mark.asyncio
async def test_remote_owner_blocks_deletion_then_restarted_job_completes(db: AsyncSession) -> None:
    from core.database import engine
    from sqlalchemy import text
    from app.voice import runtime_control
    from app.voice.models import VoiceTurnDeletion

    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="remote-owner")
    turn = await conversation_service.start_turn(session_id=session.id, transcript="Delete", run_id=uuid4())
    async with engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock_shared(:key)"), {"key": runtime_control._lock_key(session.id)})
        await connection.commit()
        try:
            with pytest.raises(management_service.VoiceTurnConflictError):
                await management_service.delete_turn(turn.id)
            assert await monitoring_service.get_turn(turn.id) is not None
            request = await db.get(VoiceTurnDeletion, turn.id)
            assert request is not None and request.status == "PENDING"
            assert not await runtime_control.session_stopped(session.id)
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock_shared(:key)"), {"key": runtime_control._lock_key(session.id)})
            await connection.commit()
    # Independent execution context: no local owner/request state is required.
    await management_service.process_deletions()
    assert await monitoring_service.get_turn(turn.id) is None
    result = await management_service.deletion_status(turn.id)
    assert result is not None and result["status"] == "COMPLETED"
    await management_service.process_deletions()
    assert await management_service.delete_turn(turn.id)


@pytest.mark.asyncio
async def test_transport_teardown_failure_retains_pending_request(db: AsyncSession) -> None:
    agent = await _agent(db)
    session = await _session(db, agent=agent, transport_kind="matrix", room_id="failed-teardown")
    turn = await conversation_service.start_turn(session_id=session.id, transcript="Delete", run_id=uuid4())
    session.teardown_error = "bridge timeout"
    await db.commit()
    with pytest.raises(management_service.VoiceTurnConflictError):
        await management_service.delete_turn(turn.id)
    result = await management_service.deletion_status(turn.id)
    assert result is not None and "bridge timeout" in str(result["last_error"])
    assert await monitoring_service.get_turn(turn.id) is not None


@pytest.mark.asyncio
async def test_force_hangup_observes_teardown_error_written_by_another_worker(
    inference_db: AsyncSession, committed_database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.voice import runtime_control

    agent = await _agent(inference_db)
    session = await _session(inference_db, agent=agent, transport_kind="matrix", room_id="late-teardown-error")
    turn = await conversation_service.start_turn(session_id=session.id, transcript="Stop", run_id=uuid4())

    async def stop(session_id: UUID) -> bool:
        async with committed_database() as worker_db:
            stored = await worker_db.get(VoiceConversationSession, session_id)
            assert stored is not None
            stored.teardown_error = "synthetic transport timeout"
            await worker_db.commit()
        return True

    monkeypatch.setattr(runtime_control, "cancel_session", stop)
    result = await management_service.force_hangup(turn.id)
    assert result is not None and result["audio_stopped"] is False


@pytest.mark.asyncio
async def test_audio_administration_http_permissions_scope_and_deferred_deletion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock
    from app.voice import runtime_control
    from core.authorize.models import Assignment, Privilege, Role, RolePrivilege
    from core.database import get_db_session
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    suffix = uuid4().hex
    password = "Synthetic-voice-password-42!"
    async with get_db_session() as db:
        users = [UserModel(email=f"voice-admin-{i}-{suffix}@example.com", is_active=True,
                           hashed_password=encrypt_password(password)) for i in range(3)]
        roles = [Role(code=f"voice-admin-{i}-{suffix}") for i in range(2)]
        db.add_all([*users, *roles])
        await db.flush()
        privileges = {p.code: p.id for p in await db.scalars(select(Privilege).where(
            Privilege.code.in_(["TASK_ACCESS", "TASK_EDIT"])
        ))}
        assert len(privileges) == 2
        db.add_all([RolePrivilege(role_id=roles[0].id, privilege_id=value)
                    for value in privileges.values()])
        db.add(RolePrivilege(role_id=roles[1].id, privilege_id=privileges["TASK_ACCESS"]))
        for i, user in enumerate(users):
            db.add(Assignment(user_id=user.id, role_id=roles[1 if i == 2 else 0].id, is_default=True))
        agent = await _agent(db, user_id=users[0].id)
        session = await _session(db, agent=agent, transport_kind="matrix", room_id=f"http-{suffix}")
        turn = await conversation_service.start_turn(session_id=session.id, transcript="Stop", run_id=uuid4())
        turn_id = turn.id
        emails = [user.email for user in users]
    url = f"/api/voice/conversations/turns/{turn_id}"
    assert (await client.post(url + "/force-hangup")).status_code == 401
    assert (await client.delete(url)).status_code == 401
    assert (await client.get(url + "/deletion")).status_code == 401
    headers = []
    for email in emails:
        client.cookies.clear()  # Independent browser families for the three synthetic users.
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    client.cookies.clear()
    for index, expected in [(2, 403), (1, 404)]:
        assert (await client.post(url + "/force-hangup", headers=headers[index])).status_code == expected
        assert (await client.delete(url, headers=headers[index])).status_code == expected
    response = await client.post(url + "/force-hangup", headers=headers[0])
    assert response.status_code == 200, response.text
    assert response.json()["revoked"] is True
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=False))
    response = await client.delete(url, headers=headers[0])
    assert response.status_code == 202, response.text
    assert (await client.get(url + "/deletion", headers=headers[0])).json()["status"] == "PENDING"
    assert (await client.get(url + "/deletion", headers=headers[1])).status_code == 404
    monkeypatch.setattr(runtime_control, "session_stopped", AsyncMock(return_value=True))
    async with get_db_session():
        await management_service.process_deletions()
    assert (await client.get(url + "/deletion", headers=headers[0])).json()["status"] == "COMPLETED"
    assert (await client.get(url, headers=headers[0])).status_code == 404
    assert (await client.delete(url, headers=headers[0])).status_code == 204
