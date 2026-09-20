from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation.models import ConversationRound
from app.conversation.resource_facade import (
    list_conversation_round_resources,
    read_conversation_round_resource,
)
from app.messenger import Room
from app.task.models import Task, TaskAmendment, TaskStatus
from app.tools.models import Tool
from app.voice.models import VoiceConversationSession


async def _round_scope(
    db: AsyncSession,
    label: str,
) -> tuple[Agent, ConversationRound]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Round {suffix}", gender="X")
    tool = Tool(
        code=f"round-messenger-{suffix}",
        label="Round transport",
        description="",
        connection_schema={},
        conversation_enabled=True,
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Round",
        last_name="Owner",
        code=f"round-owner-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        id=uuid5(NAMESPACE_URL, f"{connection.id}:{suffix}"),
        connection_id=connection.id,
        external_id=f"room-{suffix}",
        label=label,
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    round_ = ConversationRound(
        room_id=room.id,
        status="COMPLETED",
        language="fr",
        execution_result={"result": label},
    )
    db.add(round_)
    await db.flush()
    return agent, round_


@pytest.mark.asyncio
async def test_conversation_round_resources_are_scoped_by_connection_owner(
    db: AsyncSession,
) -> None:
    owner, own_round = await _round_scope(db, "Own room")
    foreign_owner, foreign_round = await _round_scope(db, "Foreign room")

    rows = await list_conversation_round_resources(actor_agent_id=owner.id)

    assert [row["id"] for row in rows] == [str(own_round.id)]
    assert await read_conversation_round_resource(
        own_round.id,
        actor_agent_id=owner.id,
    ) is not None
    assert await read_conversation_round_resource(
        foreign_round.id,
        actor_agent_id=owner.id,
    ) is None
    assert foreign_owner.id != owner.id


@pytest.mark.asyncio
async def test_conversation_round_resource_exposes_task_amendment_lineage(
    db: AsyncSession,
) -> None:
    owner, round_ = await _round_scope(db, "Amendment room")
    task = Task(
        label="Clean repository",
        objective="Reset Galaris.",
        status=TaskStatus.CREATE,
        paused=False,
        ai=True,
        cost=0.0,
        agent_id=owner.id,
    )
    db.add(task)
    await db.flush()
    amendment = TaskAmendment(
        task_id=task.id,
        source_kind="conversation_round",
        source_id=f"text:{round_.id}",
        idempotency_key=uuid4().hex,
        disposition="AMEND_CURRENT",
        instruction="Move Galaris and MaLibFin into a development directory.",
        reason="Related preventive work.",
    )
    db.add(amendment)
    await db.flush()

    payload = await read_conversation_round_resource(
        round_.id,
        actor_agent_id=owner.id,
    )

    assert payload is not None
    assert payload["task_links"] == []
    assert payload["task_amendments"] == [
        {
            "id": str(amendment.id),
            "task_id": str(task.id),
            "task_uri": f"galaris://task/{task.id}",
            "source_kind": "conversation_round",
            "source_id": f"text:{round_.id}",
            "disposition": "AMEND_CURRENT",
            "instruction": "Move Galaris and MaLibFin into a development directory.",
            "reason": "Related preventive work.",
            "created_at": amendment.created_at.isoformat(),
            "applied_at": amendment.applied_at.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_conversation_round_resources_are_split_between_text_and_voice(
    db: AsyncSession,
) -> None:
    owner, text_round = await _round_scope(db, "Text room")
    connection = await db.scalar(
        select(Connection).where(Connection.agent_id == owner.id)
    )
    assert connection is not None
    suffix = uuid4().hex[:10]
    voice_room = Room(
        id=uuid5(NAMESPACE_URL, f"{connection.id}:voice:{suffix}"),
        connection_id=connection.id,
        external_id=f"voice-room-{suffix}",
        label="Voice room",
        kind="direct",
        conversation_type="audio",
    )
    db.add(voice_room)
    await db.flush()
    session = VoiceConversationSession(
        messenger_room_id=voice_room.id,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()
    voice_round = ConversationRound(
        room_id=voice_room.id,
        voice_session_id=session.id,
        sequence=1,
        status="COMPLETED",
        language="fr",
        execution_result={"result": "voice"},
    )
    db.add(voice_round)
    await db.flush()

    text_rows = await list_conversation_round_resources(
        actor_agent_id=owner.id,
        medium="text",
    )
    voice_rows = await list_conversation_round_resources(
        actor_agent_id=owner.id,
        medium="voice",
    )

    assert [row["id"] for row in text_rows] == [str(text_round.id)]
    assert [row["resource_uri"] for row in text_rows] == [
        f"galaris://text/{text_round.id}"
    ]
    assert [row["id"] for row in voice_rows] == [str(voice_round.id)]
    assert [row["resource_uri"] for row in voice_rows] == [
        f"galaris://voice/{voice_round.id}"
    ]
    assert await read_conversation_round_resource(
        text_round.id,
        actor_agent_id=owner.id,
        medium="voice",
    ) is None
    assert await read_conversation_round_resource(
        voice_round.id,
        actor_agent_id=owner.id,
        medium="text",
    ) is None
