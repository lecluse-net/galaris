from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.dream.mechanisms.conversation_memory import (
    build_conversation_extraction_input,
    conversation_memory_mechanism,
)
from app.memory import MessengerContactObservation, observe_messenger_contact
from app.messenger import Message, MessengerUser, Room
from app.tools.models import Tool
from app.topic import Topic


async def _scope(
    db: AsyncSession,
) -> tuple[Agent, Connection, Room, Topic, UUID]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Conversation memory {suffix}", gender="X")
    tool = Tool(
        code=f"conversation-memory-{suffix}",
        label="Conversation memory",
        description="",
        connection_schema={},
    )
    topic = Topic(title="Préférences de réponse")
    db.add_all([title, tool, topic])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Memory",
        code=f"conversation-memory-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    contact_item_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="telegram",
            user_id=f"human-{suffix}",
        )
    )
    room = Room(
        connection_id=connection.id,
        external_id=f"room-{suffix}",
        label="Conversation memory",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    return agent, connection, room, topic, contact_item_id


@pytest.mark.asyncio
async def test_conversation_memory_waits_for_a_non_null_topic(
    db: AsyncSession,
) -> None:
    _agent, connection, room, _topic, contact_item_id = await _scope(db)
    message = Message(
        connection_id=connection.id,
        tool_id=connection.tool_id,
        platform="telegram",
        remote_message_id=f"message-{uuid4()}",
        direction="inbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        text="Je préfère les réponses courtes.",
    )
    db.add(message)
    await db.flush()
    round_ = ConversationRound(
        room_id=room.id,
        contact_memory_item_id=contact_item_id,
        status="SUCCEEDED",
    )
    db.add(round_)
    await db.flush()
    db.add(
        ConversationRoundMessage(
            round_id=round_.id,
            message_id=message.id,
            role="input",
            response_sequence=None,
            sequence=1,
        )
    )
    await db.commit()

    assert await conversation_memory_mechanism.count_pending() == 0
    assert await conversation_memory_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_conversation_projection_keeps_five_prior_messages_plus_current_round(
    db: AsyncSession,
) -> None:
    _agent, connection, room, topic, contact_item_id = await _scope(db)
    baseline = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
    person = MessengerUser(
        tool_id=connection.tool_id,
        external_id="nicolas",
        display_name="Nicolas",
        is_ai=False,
    )
    db.add(person)
    await db.flush()
    previous = [
        Message(
            connection_id=connection.id,
            platform="telegram",
            remote_message_id=f"previous-{index}-{uuid4()}",
            direction="inbound" if index % 2 == 0 else "outbound",
            messenger_user_id=person.id if index % 2 == 0 else None,
            messenger_room_id=room.id,
            room_id=room.external_id,
            user_id="human" if index % 2 == 0 else None,
            metadata_=(
                {"sender_display_name": "Alice Memory", "sender_is_ai": True}
                if index % 2 != 0
                else {}
            ),
            text=f"previous {index}",
            created_at=baseline + timedelta(minutes=index),
        )
        for index in range(7)
    ]
    current_record = Message(
        connection_id=connection.id,
        platform="telegram",
        remote_message_id=f"current-{uuid4()}",
        direction="inbound",
        messenger_user_id=person.id,
        messenger_room_id=room.id,
        room_id=room.external_id,
        user_id="human",
        text="Je préfère les réponses très courtes.",
        created_at=baseline + timedelta(minutes=10),
    )
    response_record = Message(
        connection_id=connection.id,
        platform="telegram",
        remote_message_id=f"response-{uuid4()}",
        direction="outbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        metadata_={"sender_display_name": "Alice Memory", "sender_is_ai": True},
        text="Je serai concise.",
        created_at=baseline + timedelta(minutes=11),
    )
    db.add_all([*previous, current_record, response_record])
    await db.flush()
    round_ = ConversationRound(
        room_id=room.id,
        topic_id=topic.id,
        contact_memory_item_id=contact_item_id,
        status="SUCCEEDED",
    )
    db.add(round_)
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=current_record.id,
                role="input",
                response_sequence=None,
                sequence=1,
            ),
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=response_record.id,
                role="output",
                response_sequence=1,
                sequence=1,
            ),
        ]
    )
    await db.commit()

    extraction_input = await build_conversation_extraction_input(round_, topic)

    assert [message.text for message in extraction_input.history] == [
        "previous 2",
        "previous 3",
        "previous 4",
        "previous 5",
        "previous 6",
    ]
    assert [
        (message.speaker_name, message.speaker_kind, message.text)
        for message in extraction_input.current
    ] == [
        ("Nicolas", "human", "Je préfère les réponses très courtes."),
        ("Alice Memory", "AI", "Je serai concise."),
    ]
