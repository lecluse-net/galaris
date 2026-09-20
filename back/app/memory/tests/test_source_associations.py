from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.connection.models import Connection
from app.conversation import (
    ConversationRound,
    ConversationTurn,
)
from app.messenger import Room
from app.memory import mcp, service
from app.memory.models import MemorySource
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemorySourceCreate
from app.task import Task, TaskStatus
from app.tools.mcp_loader import McpToolContext
from app.tools.models import Tool
from app.voice import VoiceConversationSession, VoiceTurnStatus


async def _canonical_rounds(
    db: AsyncSession,
    owner: Agent,
) -> tuple[ConversationRound, ConversationRound]:
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"memory-source-{suffix}",
        label="Memory source test",
        description="",
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"room-{suffix}",
        label="Memory source",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    round_ = ConversationRound(
        room_id=room.id,
    )
    now = datetime.now(timezone.utc)
    voice_session = VoiceConversationSession(
        messenger_room_id=room.id,
        started_at=now,
    )
    db.add_all([round_, voice_session])
    await db.flush()
    audio_round_id = uuid4()
    audio_round = ConversationRound(
        id=audio_round_id,
        room_id=room.id,
        voice_session_id=voice_session.id,
        sequence=1,
        effective_objective="Remember this durable preference.",
        status=VoiceTurnStatus.COMPLETED.value,
        created_at=now,
    )
    db.add(audio_round)
    await db.flush()
    return round_, audio_round


@pytest.mark.asyncio
async def test_existing_memory_is_linked_to_every_new_canonical_source(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    first_task = Task(
        label="First source",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
    )
    second_task = Task(
        label="Second source",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
    )
    db.add_all([first_task, second_task])
    await db.flush()
    round_, audio_round = await _canonical_rounds(db, owner)

    content = "The user always wants concise release summaries."
    first = json.loads(
        await mcp.memory_remember(
            McpToolContext(
                agent_id=owner.id,
                runtime="internal",
                task_id=first_task.id,
            ),
            content=content,
            title="Concise release summaries",
        )
    )
    memory_id = str(first["memory_id"])
    memory_uuid = UUID(memory_id)
    assert first["created"] is True

    second = json.loads(
        await mcp.memory_remember(
            McpToolContext(
                agent_id=owner.id,
                runtime="internal",
                task_id=second_task.id,
            ),
            content=content,
            title="Same known preference",
        )
    )
    assert second["created"] is True
    assert second["status"] == "merged"
    assert second["memory_id"] == memory_id

    text_turn = ConversationTurn(
        room_id=round_.room_id,
        round_id=round_.id,
        agent_id=owner.id,
        language="en",
        objective=content,
        messages=(),
        origin="text",
    )
    text_result = json.loads(
        await mcp.memory_remember(
            McpToolContext(
                agent_id=owner.id,
                runtime="internal",
                resources={"conversation_turn": text_turn},
            ),
            content=content,
            title="Same preference from a text round",
        )
    )
    assert text_result["created"] is True
    assert text_result["status"] == "merged"
    assert text_result["memory_id"] == memory_id
    assert text_result["source_kind"] == "conversation_round"

    audio_turn = ConversationTurn(
        room_id=audio_round.room_id,
        round_id=audio_round.id,
        agent_id=owner.id,
        language="en",
        objective=content,
        messages=(),
        origin="voice",
    )
    audio_result = json.loads(
        await mcp.memory_remember(
            McpToolContext(
                agent_id=owner.id,
                runtime="internal",
                resources={"conversation_turn": audio_turn},
            ),
            content=content,
            title="Same preference from an audio round",
        )
    )
    assert audio_result["created"] is True
    assert audio_result["status"] == "merged"
    assert audio_result["memory_id"] == memory_id
    assert audio_result["source_kind"] == "conversation_round"

    other_item, created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Another memory from the first task",
            payload=MemoryPayload(text="A separate durable fact."),
            source=MemorySourceCreate(
                source_kind="task",
                source_ref=f"task:{first_task.id}",
            ),
        )
    )
    assert created

    sources = list(
        (
            await db.scalars(
                select(MemorySource).where(MemorySource.item_id == memory_uuid)
            )
        ).all()
    )
    assert {source.task_id for source in sources if source.task_id is not None} == {
        first_task.id,
        second_task.id,
    }
    assert {
        source.conversation_round_id
        for source in sources
        if source.conversation_round_id is not None
    } == {round_.id, audio_round.id}
    assert set(
        (
            await db.scalars(
                select(MemorySource.item_id).where(
                    MemorySource.task_id == first_task.id
                )
            )
        ).all()
    ) == {other_item.id, memory_uuid}
