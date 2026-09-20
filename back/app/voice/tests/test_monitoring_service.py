from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

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


async def _agent(db: AsyncSession) -> Agent:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Voice monitoring {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
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
async def test_running_voice_turn_cannot_be_deleted(db: AsyncSession) -> None:
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

    with pytest.raises(management_service.VoiceTurnConflictError):
        await management_service.delete_turn(turn.id)


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
        update_voice_conversation_turn_topic,
    )

    for endpoint in (delete_voice_conversation_turn, update_voice_conversation_turn_topic):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.TASK_EDIT
        ]


@pytest.mark.asyncio
async def test_voice_monitoring_rejects_unauthenticated_requests(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/voice/conversations")
    assert response.status_code == 401
