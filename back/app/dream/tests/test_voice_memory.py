from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.dream.contracts import (
    DreamClaim,
    MemoryCreateOperation,
    MemoryExtractionDecision,
    MemoryExtractionPrepared,
)
from app.dream.mechanisms import conversation_memory
from app.dream.mechanisms.voice_memory import voice_memory_mechanism
from app.dream.models import DreamReceipt
from app.memory import MessengerContactObservation, observe_messenger_contact
from app.memory.models import (
    MemoryContextNode,
    MemoryItem,
    MemorySource,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.messenger import ConversationType, Message, Room
from app.topic import TopicClassification, service as topic_service
from app.tools import ToolModel
from app.voice.models import (
    VoiceConversationSession,
    VoiceConversationStatus,
    VoiceTurnStatus,
)
from core.database import get_db


async def _audio_round(
    db: AsyncSession,
    *,
    classified: bool,
) -> tuple[Agent, ConversationRound]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Audio memory {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Voice",
        code=f"audio-memory-{suffix}",
        agent_driver="internal",
    )
    tool = ToolModel(
        code=f"audio-memory-messenger-{suffix}",
        label="Audio memory Messenger",
        description="",
        connection_schema={},
    )
    db.add_all([owner, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"audio-room-{suffix}",
        label="Audio room",
        kind="direct",
        conversation_type=ConversationType.AUDIO.value,
    )
    db.add(room)
    await db.flush()
    contact_item_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id=f"@alice-{suffix}:example.test",
            display_name="Alice",
        )
    )
    topic = None
    if classified:
        topic = await topic_service.create_from_classification(
            TopicClassification(action="create", title=f"Préférences {suffix}")
        )
    now = datetime.now(timezone.utc)
    session = VoiceConversationSession(
        messenger_room_id=room.id,
        status=VoiceConversationStatus.COMPLETED.value,
        started_at=now,
        finished_at=now,
    )
    db.add(session)
    await db.flush()
    round_id = uuid4()
    round_ = ConversationRound(
        id=round_id,
        room_id=room.id,
        voice_session_id=session.id,
        sequence=1,
        language="fr",
        topic_id=topic.id if topic is not None else None,
        contact_memory_item_id=contact_item_id,
        effective_objective="Je préfère des réponses courtes.",
        status=VoiceTurnStatus.COMPLETED.value,
        created_at=now,
        finished_at=now,
    )
    db.add(round_)
    await db.flush()
    messages = (
        Message(
            connection_id=connection.id,
            tool_id=tool.id,
            platform="matrix",
            remote_message_id=f"audio-input-{suffix}",
            direction="inbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            text="Je préfère des réponses courtes.",
            created_at=now,
        ),
        Message(
            connection_id=connection.id,
            tool_id=tool.id,
            platform="matrix",
            remote_message_id=f"audio-output-{suffix}",
            direction="outbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            text="Compris.",
            created_at=now,
        ),
    )
    db.add_all(messages)
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=messages[0].id,
                role="input",
                response_sequence=None,
                sequence=1,
            ),
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=messages[1].id,
                role="output",
                response_sequence=1,
                sequence=1,
            ),
        ]
    )
    await db.commit()
    return owner, round_


@pytest.mark.asyncio
async def test_audio_memory_apply_refuses_an_unclassified_round(
    db: AsyncSession,
) -> None:
    _owner, round_ = await _audio_round(db, classified=False)
    claim = DreamClaim(
        receipt_id=uuid4(),
        lease_token=uuid4(),
        subject_kind="conversation_round",
        subject_id=str(round_.id),
        attempts=1,
        prepared_payload=None,
    )

    assert await voice_memory_mechanism.apply(
        claim,
        MemoryExtractionPrepared(
            decision=MemoryExtractionDecision()
        ).model_dump(mode="json"),
    ) == 0


@pytest.mark.asyncio
async def test_audio_round_waits_for_topic_classification(db: AsyncSession) -> None:
    _owner, _round = await _audio_round(db, classified=False)

    assert await voice_memory_mechanism.count_pending() == 0
    assert await voice_memory_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_audio_extraction_uses_canonical_round_and_messages(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        owner, round_ = await _audio_round(db, classified=True)

        async def fake_recall(*_args: Any, **_kwargs: Any) -> object:
            get_db()
            return type("RecallResult", (), {"hits": []})()

        async def fake_resolve(_model_field: str, agent_id: int | None) -> object:
            assert agent_id == owner.id
            get_db()
            return object()

        async def fake_extract(**kwargs: Any) -> tuple[MemoryExtractionPrepared, float]:
            get_db()
            assert "Required output language: French (fr)" in kwargs["language_instruction"]
            return MemoryExtractionPrepared(
                decision=MemoryExtractionDecision(
                    operations=[
                        MemoryCreateOperation(
                            title="Préférence vocale",
                            content="Alice préfère des réponses courtes.",
                            memory_type="core",
                            keywords=["préférence", "courtes"],
                            retention_reason="explicit_user_preference",
                        )
                    ]
                )
            ), 0.01

        monkeypatch.setattr(conversation_memory, "search_memory_detailed", fake_recall)
        monkeypatch.setattr(
            conversation_memory.llm_service,
            "get_profile_llm_for_agent_id",
            fake_resolve,
        )
        monkeypatch.setattr(conversation_memory, "run_memory_extraction", fake_extract)
        claim = DreamClaim(
            receipt_id=uuid4(),
            lease_token=uuid4(),
            subject_kind="conversation_round",
            subject_id=str(round_.id),
            attempts=1,
            prepared_payload=None,
        )
        prepared = await voice_memory_mechanism.prepare(claim)
        assert prepared.cost == 0.01
        db.add(
            DreamReceipt(
                id=claim.receipt_id,
                mechanism_key=voice_memory_mechanism.key,
                subject_kind=claim.subject_kind,
                subject_id=claim.subject_id,
                status="running",
                attempts=claim.attempts,
                lease_token=claim.lease_token,
                lease_owner="test",
                prepared_payload=prepared.payload,
            )
        )
        await db.commit()
        assert await voice_memory_mechanism.apply(claim, prepared.payload) == 1

        item = await db.scalar(
            select(MemoryItem)
            .join(MemorySource, MemorySource.item_id == MemoryItem.id)
            .where(
                MemorySource.source_kind == "conversation_round",
                MemorySource.source_ref == f"conversation_round:{round_.id}",
            )
        )
        assert item is not None
        assert item.metadata_["language"] == "fr"
        scope_item = await db.scalar(
            select(MemoryTopicContactItem)
            .join(
                MemoryTopicContactScope,
                MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
            )
            .where(MemoryTopicContactItem.item_id == item.id)
        )
        assert scope_item is not None
        assert await db.scalar(select(MemoryContextNode)) is None
    finally:
        reset_storage_registry()
