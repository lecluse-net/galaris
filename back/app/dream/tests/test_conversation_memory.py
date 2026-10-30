from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import json

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
from app.messenger import Attachment, File, Message, MessengerUser, Room
from app.tools.models import Tool
from app.topic import Topic
from tests.test_inference_lifecycle import runtime
from tests.conftest import responses_sse
from app.dream.tests.test_memory_extraction import memory_extraction_storage


async def _scope(
    db: AsyncSession,
) -> tuple[Agent, Connection, Room, Topic, UUID]:
    suffix = uuid4().hex[:10]
    from core.user.models import User
    owner = User(email=f"memory-{suffix}@example.test", hashed_password="synthetic")
    db.add(owner)
    await db.flush()
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
        user_id=owner.id,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("written", ["", "Voici ma préférence."])
async def test_transcribed_attachment_is_an_eligible_attributed_memory_source(db, written):
    agent, connection, room, topic, contact = await _scope(db)
    audio = File(connection_id=connection.id, name="preference.ogg", mime_type="audio/ogg", kind="audio")
    db.add(audio)
    await db.flush()
    message = Message(connection_id=connection.id, tool_id=connection.tool_id, platform="telegram",
        remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id,
        room_id=room.external_id, text=written,
        metadata_={"sender_display_name": "Camille", "conversation_audio_transcripts": {
            str(audio.id): "Je préfère des comptes rendus en français.",
            str(uuid4()): "Un résultat orphelin ne doit jamais devenir un souvenir.",
        }})
    db.add(message)
    await db.flush()
    db.add(Attachment(message_id=message.id, file_id=audio.id, position=0))
    round_ = ConversationRound(room_id=room.id, topic_id=topic.id,
        contact_memory_item_id=contact, status="SUCCEEDED")
    db.add(round_)
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()

    assert await conversation_memory_mechanism.count_pending() == 1
    extraction = await build_conversation_extraction_input(round_, topic)
    assert len(extraction.current) == 1
    current = extraction.current[0]
    assert current.speaker_name == "Camille" and current.speaker_kind == "human"
    assert "comptes rendus en français" in current.text
    assert "orphelin" not in current.text
    assert current.evidence[-1].kind == "transcription"
    tool = await db.get(Tool, connection.tool_id)
    assert current.evidence[-1].uri == f"{tool.code}://{room.external_id}/{audio.id}"
    assert current.evidence[-1].message_id == message.id
    assert written in current.text


@pytest.mark.asyncio
async def test_each_supporting_audio_file_must_remain_available(db, memory_extraction_storage):
    from sqlalchemy import select
    from app.memory import service
    from app.memory.models import MemoryItem
    from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemorySourceCreate
    from app.memory.access import readable_item_clause

    agent, connection, room, topic, contact = await _scope(db)
    files = [File(connection_id=connection.id, name=f"part-{index}.ogg", mime_type="audio/ogg", kind="audio")
        for index in range(2)]
    db.add_all(files)
    await db.flush()
    message = Message(connection_id=connection.id, tool_id=connection.tool_id, platform="telegram",
        remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id, room_id=room.external_id,
        text="", metadata_={"conversation_audio_transcripts": {str(file.id): "Je préfère des rapports courts." for file in files}})
    db.add(message)
    await db.flush()
    db.add_all([Attachment(message_id=message.id, file_id=file.id, position=index) for index, file in enumerate(files)])
    round_ = ConversationRound(room_id=room.id, topic_id=topic.id, contact_memory_item_id=contact, status="SUCCEEDED")
    db.add(round_)
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()
    extraction = await build_conversation_extraction_input(round_, topic)
    item, _created = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, title="Synthetic combined evidence",
        payload=MemoryPayload(text="Camille prefers short reports."), metadata={"evidence_validator": "conversation"},
        source=MemorySourceCreate(source_kind="conversation_round",
        source_ref=f"conversation_round:{round_.id}", metadata={"evidence_validator": "conversation",
            "source_evidence": [part.model_dump(mode="json") for part in extraction.current[0].evidence]})))
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, readable_item_clause(agent.id))) == item.id
    files[0].soft_delete()
    await db.commit()
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, readable_item_clause(agent.id))) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidation", ["removed", "corrected", "revoked"])
async def test_late_transcription_has_a_new_receipt_and_preserves_existing_memory(runtime, memory_extraction_storage, invalidation):
    from sqlalchemy import select, func
    from app.llm.profile_models import LlmProfile
    from app.dream.service import store_prepared, mark_success
    from app.memory.models import MemoryItem, MemorySource

    db, llm, requests, mode = runtime
    agent, connection, room, topic, contact = await _scope(db)
    profile = LlmProfile(label="Synthetic memory reader", text_ultra_low_llm_id=llm.id)
    db.add(profile)
    await db.flush()
    agent.profile_id = profile.id
    from app.llm.profile_service import set_current_profile_id
    await set_current_profile_id(profile.id)
    audio = File(connection_id=connection.id, name="preference.ogg", mime_type="audio/ogg", kind="audio")
    db.add(audio)
    await db.flush()
    message = Message(connection_id=connection.id, tool_id=connection.tool_id, platform="telegram",
        remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id,
        room_id=room.external_id, text="Je préfère les réponses courtes.",
        metadata_={"sender_display_name": "Camille"})
    db.add(message)
    await db.flush()
    db.add(Attachment(message_id=message.id, file_id=audio.id, position=0))
    round_ = ConversationRound(room_id=room.id, topic_id=topic.id, contact_memory_item_id=contact, status="SUCCEEDED")
    db.add(round_)
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()

    async def capture(content, ref):
        mode["outputs"] = [json.dumps({"operations": [{"action": "CREATE", "title": "Préférence de Camille",
            "fact": {"predicate": "preferred_response_style", "value": content}, "retention_reason": "explicit_user_preference", "future_utility": "high",
            "evidence_refs": [ref]}]})] * 20
        claim = await conversation_memory_mechanism.claim_one()
        assert claim is not None
        prepared = await conversation_memory_mechanism.prepare(claim)
        await store_prepared(claim, prepared.payload, cost=prepared.cost)
        assert await conversation_memory_mechanism.apply(claim, prepared.payload) == 1
        assert await conversation_memory_mechanism.apply(claim, prepared.payload) == 1
        await mark_success(claim, result_count=1)
        return claim

    first = await capture("Camille préfère des réponses courtes.", f"{message.id}:written")
    assert first.subject_id == str(round_.id)
    assert await conversation_memory_mechanism.count_pending() == 0
    message.metadata_ = {**message.metadata_, "conversation_audio_transcripts": {
        str(audio.id): "\n Je préfère des comptes rendus en français.\t\n"}}
    await db.commit()
    assert await conversation_memory_mechanism.count_pending() == 1
    second = await capture("Camille préfère des comptes rendus en français.", f"{message.id}:{audio.id}")
    assert second.subject_id != first.subject_id
    assert await conversation_memory_mechanism.claim_one() is None
    assert await db.scalar(select(func.count()).select_from(MemorySource).where(
        MemorySource.conversation_round_id == round_.id)) == 2
    sources = list(await db.scalars(select(MemorySource).where(MemorySource.conversation_round_id == round_.id)))
    assert {source.metadata_["source_evidence"][0]["kind"] for source in sources} == {"written", "transcription"}
    assert len(requests) == 2

    from app.memory import service as memory_service
    from app.memory.access import readable_item_clause
    from app.memory.schemas import MemorySourceCreate
    from app.memory.source_access import readable_source_ids
    from app.memory.admission import admit_search_hits
    from app.memory.schemas import MemorySearchHit
    audio_source = next(source for source in sources if source.metadata_["source_evidence"][0]["kind"] == "transcription")
    audio_item = await db.get(MemoryItem, audio_source.item_id)
    identities = {source.item_id for source in sources}
    assert await readable_source_ids(identities, agent.id) == identities
    loaded, _content, access, _kind, _media = await memory_service.get_item(audio_item.id, agent_id=agent.id)
    assert loaded.id == audio_item.id
    hit = MemorySearchHit(item=memory_service.item_to_public(loaded, access), excerpt="French reports", score=1)
    assert len(await admit_search_hits(agent.id, [hit])) == 1
    if invalidation == "removed":
        audio.soft_delete()
    elif invalidation == "corrected":
        message.metadata_ = {**message.metadata_, "conversation_audio_transcripts": {str(audio.id): "Correction : comptes rendus en anglais."}}
    else:
        connection.active = False
    await db.commit()
    assert audio_item.id not in await readable_source_ids(identities, agent.id)
    assert audio_item.id not in set(await db.scalars(select(MemoryItem.id).where(
        MemoryItem.id.in_(identities), readable_item_clause(agent.id))))
    assert await admit_search_hits(agent.id, [hit]) == []
    with pytest.raises(memory_service.MemoryPermissionError):
        await memory_service.get_item(audio_item.id, agent_id=agent.id)
    # An independently acquired fact remains available when this media proof is lost.
    await memory_service.add_item_source(audio_item.id, MemorySourceCreate(source_kind="manual",
        source_ref="synthetic-independent-preference", excerpt="Explicitly confirmed elsewhere."), actor_agent_id=None, administrative=True)
    assert audio_item.id in await readable_source_ids(identities, agent.id)
    assert len(await admit_search_hits(agent.id, [hit])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["removed", "revoked", "corrected", "none"])
async def test_audio_only_capture_rechecks_evidence_after_preparation(runtime, memory_extraction_storage, change):
    from sqlalchemy import select, func
    from app.llm.profile_models import LlmProfile
    from app.llm.profile_service import set_current_profile_id
    from app.memory.models import MemorySource
    from app.dream.mechanisms.memory_extraction import MemoryExtractionApplicationError

    db, llm, requests, mode = runtime
    agent, connection, room, topic, contact = await _scope(db)
    profile = LlmProfile(label="Synthetic audio reader", text_ultra_low_llm_id=llm.id)
    db.add(profile)
    await db.flush()
    agent.profile_id = profile.id
    await set_current_profile_id(profile.id)
    audio = File(connection_id=connection.id, name="preference.ogg", mime_type="audio/ogg", kind="audio")
    db.add(audio)
    await db.flush()
    message = Message(connection_id=connection.id, tool_id=connection.tool_id, platform="telegram",
        remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id,
        room_id=room.external_id, text="", metadata_={"sender_display_name": "Camille",
            "conversation_audio_transcripts": {str(audio.id): "Je préfère des comptes rendus en français."}})
    db.add(message)
    await db.flush()
    db.add(Attachment(message_id=message.id, file_id=audio.id, position=0))
    round_ = ConversationRound(room_id=room.id, topic_id=topic.id, contact_memory_item_id=contact,
        language="fr", status="SUCCEEDED")
    db.add(round_)
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()
    mode["outputs"] = [json.dumps({"operations": [{"action": "CREATE", "title": "Préférence de Camille",
        "fact": {"predicate": "preferred_report_language", "value": "fr"}, "retention_reason": "explicit_user_preference",
        "future_utility": "high", "evidence_refs": [f"{message.id}:{audio.id}"]}]})] * 20
    claim = await conversation_memory_mechanism.claim_one()
    assert claim is not None
    prepared = await conversation_memory_mechanism.prepare(claim)
    if change == "removed":
        message.soft_delete()
    elif change == "revoked":
        connection.active = False
    elif change == "corrected":
        message.metadata_ = {**message.metadata_, "conversation_audio_transcripts": {str(audio.id): "Correction : en anglais."}}
    await db.commit()
    if change != "none":
        with pytest.raises(MemoryExtractionApplicationError, match="(changed|available)"):
            await conversation_memory_mechanism.apply(claim, prepared.payload)
        assert await db.scalar(select(func.count()).select_from(MemorySource).where(
            MemorySource.conversation_round_id == round_.id)) == 0
    else:
        assert await conversation_memory_mechanism.apply(claim, prepared.payload) == 1
        source = await db.scalar(select(MemorySource).where(MemorySource.conversation_round_id == round_.id))
        assert source.metadata_["language"] == "fr"
        assert source.metadata_["source_evidence"][0]["message_id"] == str(message.id)
        assert "preferred_report_language" in source.excerpt and f"memory://{contact}" in source.excerpt
        assert source.metadata_["source_evidence"][0]["uri"].endswith(str(audio.id))
    assert len(requests) == 1
