from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, AgentGroup, AgentTeam, Title
from app.connection.models import Connection
from app.conversation.models import (
    ConversationProcessLink,
    ConversationRound,
)
from app.llm import LLMCall
from app.memory import (
    MessengerContactObservation,
    TopicProjectionMatch,
    TopicProjectionRanking,
    ensure_topic_memory_link,
    observe_messenger_contact,
)
from app.memory import service as memory_service
from app.memory.models import MemoryItem, MemoryLink
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.process import ProcessDefinition, ProcessRun
from app.memory.storage import (
    NativeFileStorage,
    register_storage,
    reset_storage_registry,
)
from app.task.models import Task, TaskStatus
from app.messenger.models import Message, Room
from app.topic import service
from app.topic.models import Topic
from app.topic.schemas import (
    TopicClassification,
    TopicCreate,
    TopicItemSelector,
    TopicSelectionSplitRequest,
    TopicSplitRequest,
    TopicUpdate,
)
from app.tools.models import Tool
from app.voice.models import (
    VoiceConversationSession,
    VoiceConversationStatus,
)


def _ondelete(model: type[object], column_name: str) -> str | None:
    column = model.__table__.c[column_name]  # pyright: ignore[reportAttributeAccessIssue]
    foreign_keys = list(column.foreign_keys)
    assert len(foreign_keys) == 1
    return foreign_keys[0].ondelete


def test_topic_foreign_key_delete_policies_are_explicit() -> None:
    for model in (
        Task,
        Message,
        ConversationRound,
    ):
        assert _ondelete(model, "topic_id") == "SET NULL"

    assert _ondelete(MemoryItem, "topic_id") == "CASCADE"
    assert _ondelete(Topic, "memory_item_id") == "SET NULL"
    assert _ondelete(MemoryLink, "source_item_id") == "CASCADE"
    assert _ondelete(MemoryLink, "target_item_id") == "CASCADE"


@pytest.mark.asyncio
async def test_manual_crud_split_and_merge_preserve_memory_items(
    db: AsyncSession, tmp_path: Path
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        title = Title(label=f"Topic admin {uuid4().hex[:8]}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Topics",
            code=f"topic-admin-{uuid4().hex[:10]}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()

        source = await service.create(TopicCreate(title="Maison"))
        updated = await service.update_topic(
            source.id,
            TopicUpdate(
                revision=source.revision,
                title="Maison et jardin",
                description="Entretien durable.",
                keywords=["maison", "jardin"],
            ),
        )
        assert updated.title == "Maison et jardin"
        assert updated.memory_item_id is not None
        topic_projection = await db.get(MemoryItem, updated.memory_item_id)
        assert topic_projection is not None
        assert topic_projection.topic_id == updated.id

        memories = []
        for index in range(2):
            item, _ = await memory_service.create_item(
                MemoryItemCreate(
                    owner_agent_id=owner.id,
                    title=f"Souvenir {index}",
                    payload=MemoryPayload(text=f"Contenu durable {index}"),
                )
            )
            memories.append(item)
            assert updated.memory_item_id is not None
            await ensure_topic_memory_link(
                topic_item_id=updated.memory_item_id,
                memory_item_id=item.id,
            )

        task = Task(
            label="Tâche classée",
            status=TaskStatus.SUCCESS,
            agent_id=owner.id,
            topic_id=updated.id,
        )
        tool = Tool(
            code=f"topic-admin-messenger-{uuid4().hex[:10]}",
            label="Topic admin messenger",
            description="",
            connection_schema={},
        )
        db.add_all([task, tool])
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(
            connection_id=connection.id,
            external_id=f"topic-admin-room-{uuid4()}",
            label="Topic admin room",
            kind="direct",
            conversation_type="text",
        )
        db.add(room)
        await db.flush()
        audio_round = ConversationRound(
            room_id=room.id,
            topic_id=updated.id,
            status="COMPLETED",
        )
        message = Message(
            connection_id=connection.id,
            platform="internal",
            remote_message_id=f"topic-admin-message-{uuid4()}",
            direction="inbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            topic_id=updated.id,
            text="Message à reclasser",
        )
        db.add_all([audio_round, message])
        await db.commit()

        linked = await service.list_linked_memories(updated.id)
        assert {item.id for item in linked} == {memory.id for memory in memories}
        linked_items = await service.list_items(updated.id, limit=50)
        assert linked_items.total == 5
        assert {item.item_type for item in linked_items.items} == {
            "task",
            "message",
            "conversation_round",
            "memory",
        }

        split = await service.split(
            updated.id,
            TopicSplitRequest(
                title="Jardin",
                memory_item_ids=[memories[1].id],
            ),
        )
        assert split.moved_memory_links == 1
        assert split.topic.memory_item_id is not None
        assert await db.scalar(
            select(MemoryLink).where(
                MemoryLink.source_item_id == split.topic.memory_item_id,
                MemoryLink.target_item_id == memories[1].id,
                MemoryLink.relation_type == "topic_contains",
            )
        ) is not None
        assert await db.scalar(
            select(MemoryLink).where(
                MemoryLink.source_item_id == updated.memory_item_id,
                MemoryLink.target_item_id == memories[0].id,
                MemoryLink.relation_type == "topic_contains",
            )
        ) is not None

        moved_message = await service.reassign_item(
            updated.id,
            split.topic.id,
            TopicItemSelector(item_type="message", item_id=message.id),
        )
        assert moved_message.item.topic_id == split.topic.id
        await db.refresh(message)
        assert message.topic_id == split.topic.id

        selected_split = await service.split_selection(
            updated.id,
            TopicSelectionSplitRequest(
                title="Travaux maison",
                items=[
                    TopicItemSelector(item_type="task", item_id=task.id),
                    TopicItemSelector(
                        item_type="conversation_round",
                        item_id=audio_round.id,
                    ),
                ],
            ),
        )
        assert selected_split.reassigned_tasks == 1
        assert selected_split.reassigned_conversation_rounds == 1
        selected_merged = await service.merge(
            selected_split.topic.id,
            split.topic.id,
        )
        assert selected_merged.reassigned_tasks == 1
        assert selected_merged.reassigned_conversation_rounds == 1

        merged = await service.merge(updated.id, split.topic.id)
        assert merged.moved_memory_links == 1
        assert merged.reassigned_tasks == 0
        assert merged.reassigned_messages == 0
        assert merged.reassigned_conversation_rounds == 0
        await db.refresh(task)
        await db.refresh(audio_round)
        assert task.topic_id == split.topic.id
        assert audio_round.topic_id == split.topic.id
        source_record = await db.get(
            Topic,
            updated.id,
            execution_options={"include_historized": True},
        )
        assert source_record is not None and source_record.deleted_at is not None

        deleted_projection_id = split.topic.memory_item_id
        assert deleted_projection_id is not None
        assert await service.delete_topic(split.topic.id)
        await db.refresh(task)
        await db.refresh(audio_round)
        await db.refresh(message)
        assert task.topic_id is None
        assert audio_round.topic_id is None
        assert message.topic_id is None
        assert (
            await db.get(
                MemoryItem,
                deleted_projection_id,
                execution_options={"include_historized": True},
            )
            is None
        )
        assert await db.scalar(
            select(MemoryLink.id).where(
                (MemoryLink.source_item_id == deleted_projection_id)
                | (MemoryLink.target_item_id == deleted_projection_id)
            )
        ) is None
        assert await db.get(MemoryItem, memories[0].id) is not None
        assert await db.get(MemoryItem, memories[1].id) is not None
        assert await service.get(split.topic.id) is None
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_physical_topic_delete_cascades_only_its_memory_projection(
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        title = Title(label=f"Topic FK {uuid4().hex[:8]}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Topic",
            last_name="Owner",
            code=f"topic-fk-{uuid4().hex[:10]}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()
        topic = await service.create(TopicCreate(title="Disposable Topic"))
        assert topic.memory_item_id is not None
        linked_memory, _ = await memory_service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Independent memory",
                payload=MemoryPayload(text="This node must survive Topic deletion."),
            )
        )
        await ensure_topic_memory_link(
            topic_item_id=topic.memory_item_id,
            memory_item_id=linked_memory.id,
        )
        task = Task(
            label="Topic FK task",
            status=TaskStatus.SUCCESS,
            agent_id=owner.id,
            topic_id=topic.id,
        )
        db.add(task)
        await db.commit()
        task_id = task.id
        projection_id = topic.memory_item_id
        linked_memory_id = linked_memory.id
        db.expunge_all()

        topic_record = await db.get(Topic, topic.id)
        assert topic_record is not None
        await db.delete(topic_record)
        await db.commit()
        db.expire_all()

        persisted_task = await db.get(Task, task_id)
        assert persisted_task is not None and persisted_task.topic_id is None
        assert await db.get(MemoryItem, projection_id) is None
        assert await db.get(MemoryItem, linked_memory_id) is not None
        assert await db.scalar(
            select(MemoryLink.id).where(
                (MemoryLink.source_item_id == projection_id)
                | (MemoryLink.target_item_id == projection_id)
            )
        ) is None
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_update_rejects_stale_revision(db: AsyncSession, tmp_path: Path) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        topic = await service.create(TopicCreate(title="Concurrent"))
        with pytest.raises(service.TopicConflictError):
            await service.update_topic(
                topic.id,
                TopicUpdate(revision=topic.revision + 1, title="Stale"),
            )
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_dream_topic_projection_keeps_source_language(
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        topic = await service.create_from_classification(
            TopicClassification(
                action="create",
                title="Potager urbain",
                keywords=["potager", "balcon"],
            ),
            language="fr",
        )

        assert topic.metadata_["language"] == "fr"
        assert topic.memory_item_id is not None
        item, content, _access, _content_type, _media_type = (
            await memory_service.get_item(
                topic.memory_item_id,
                agent_id=None,
                administrative=True,
            )
        )
        assert item.metadata_["language"] == "fr"
        assert b"Mots-cl\xc3\xa9s: potager, balcon" in content
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_dream_topic_creation_reuses_an_equivalent_normalized_title(
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        original = await service.create_from_classification(
            TopicClassification(
                action="create",
                title="Énergie solaire",
                description="Production domestique d'électricité.",
            ),
            language="fr",
        )
        duplicate = await service.create_from_classification(
            TopicClassification(
                action="create",
                title="  energie-solaire!  ",
                description="Une formulation redondante.",
            ),
            language="fr",
        )

        assert duplicate.id == original.id
        assert len((await db.execute(select(Topic))).scalars().all()) == 1
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_list_keywords_returns_unique_sorted_active_values(
    db: AsyncSession, tmp_path: Path
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        archived = await service.create(
            TopicCreate(title="Archived", keywords=["obsolete"])
        )
        await service.create(
            TopicCreate(title="Garden", keywords=["potager", "Balcon"])
        )
        await service.create(
            TopicCreate(title="Home", keywords=["maison", "potager"])
        )
        assert await service.delete_topic(archived.id)

        assert await service.list_keywords() == ["Balcon", "maison", "potager"]
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_topic_content_recaps_tasks_rooms_and_round_kinds(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Topic recap {suffix}", gender="X")
    tool = Tool(
        code=f"topic-recap-{suffix}",
        label="Topic recap",
        description="",
        connection_schema={},
    )
    topic = Topic(title="Garden recap")
    db.add_all([title, tool, topic])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Recap",
        code=f"topic-recap-agent-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"topic-recap-room-{suffix}",
        label="Garden room",
        kind="direct",
        conversation_type="audio",
    )
    db.add(room)
    await db.flush()
    session = VoiceConversationSession(
        messenger_room_id=room.id,
        status=VoiceConversationStatus.COMPLETED.value,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()
    task = Task(
        label="Water tomatoes",
        objective="Check soil moisture",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        topic_id=topic.id,
        messenger_connection_id=connection.id,
        message_group_id=room.external_id,
    )
    text_round = ConversationRound(
        room_id=room.id,
        topic_id=topic.id,
        status="SUCCEEDED",
        effective_objective="How is the garden?",
    )
    voice_round = ConversationRound(
        room_id=room.id,
        voice_session_id=session.id,
        topic_id=topic.id,
        sequence=1,
        status="COMPLETED",
        effective_objective="Water the tomatoes",
    )
    db.add_all([task, text_round, voice_round])
    await db.commit()

    content = await service.get_content(topic.id)

    assert content.summary.rooms == 1
    assert content.summary.tasks == 1
    assert content.summary.conversation_rounds == 1
    assert content.summary.voice_turns == 1
    assert content.tasks[0].agent_name == "Alice Recap"
    assert content.conversation_rounds[0].preview == "How is the garden?"
    assert content.voice_turns[0].session_id == session.id


@pytest.mark.asyncio
async def test_list_page_aggregates_monthly_llm_costs_from_topic_activities(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    suffix = uuid4().hex[:8]
    title = Title(label=f"Topic costs {suffix}", gender="X")
    tool = Tool(
        code=f"topic-costs-{suffix}",
        label="Topic costs",
        description="",
        connection_schema={},
    )
    first_topic = Topic(title="Home energy")
    second_topic = Topic(title="Gardening")
    db.add_all([title, tool, first_topic, second_topic])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Costs",
        code=f"topic-costs-agent-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    task = Task(
        label="Compare solar quotes",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        topic_id=first_topic.id,
    )
    db.add_all([connection, task])
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id="topic-cost-room",
        label="Topic cost room",
        kind="direct",
        conversation_type="audio",
    )
    db.add(room)
    await db.flush()
    voice_session = VoiceConversationSession(
        messenger_room_id=room.id,
        status=VoiceConversationStatus.COMPLETED.value,
        started_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
    )
    db.add(voice_session)
    await db.flush()
    round_ = ConversationRound(
        room_id=room.id,
        topic_id=first_topic.id,
        status="SUCCEEDED",
    )
    audio_round_id = uuid4()
    audio_round = ConversationRound(
        id=audio_round_id,
        room_id=room.id,
        voice_session_id=voice_session.id,
        topic_id=first_topic.id,
        sequence=1,
        status="COMPLETED",
        created_at=datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc),
    )
    second_task = Task(
        label="Plant tomatoes",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        topic_id=second_topic.id,
    )
    db.add_all([round_, audio_round, second_task])
    await db.flush()
    process = ProcessDefinition(
        agent_id=agent.id,
        tool_id=tool.id,
        engine_process_id=f"topic-cost-process-{suffix}",
        label="Topic cost process",
    )
    db.add(process)
    await db.flush()
    process_run = ProcessRun(
        process_id=process.id,
        launcher_agent_id=agent.id,
        task_id=task.id,
        engine_code="n8n",
        correlation_id=f"topic-cost-correlation-{suffix}",
        callback_token=f"topic-cost-token-{suffix}",
    )
    db.add(process_run)
    await db.flush()
    conversation_process_run = ProcessRun(
        process_id=process.id,
        launcher_agent_id=agent.id,
        engine_code="n8n",
        correlation_id=f"topic-cost-conversation-{suffix}",
        callback_token=f"topic-cost-conversation-token-{suffix}",
    )
    db.add(conversation_process_run)
    await db.flush()
    db.add(
        ConversationProcessLink(
            round_id=round_.id,
            process_run_id=conversation_process_run.id,
            action_key="topic-cost-process",
        )
    )
    await db.flush()
    db.add_all(
        [
            LLMCall(
                task_id=task.id,
                cost=0.10,
                inference_cost=0.10,
                started_at=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                conversation_round_id=round_.id,
                cost=0.20,
                inference_cost=0.20,
                started_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                conversation_round_id=audio_round.id,
                cost=0.30,
                inference_cost=0.30,
                started_at=datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                process_run_id=process_run.id,
                cost=0.07,
                inference_cost=0.07,
                started_at=datetime(2026, 7, 4, 11, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                process_run_id=conversation_process_run.id,
                cost=0.08,
                inference_cost=0.08,
                started_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                task_id=second_task.id,
                cost=0.05,
                inference_cost=0.05,
                started_at=datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc),
            ),
            LLMCall(
                cost=9.0,
                inference_cost=9.0,
                started_at=datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc),
            ),
            # This is August 1st in Europe/Paris.
            LLMCall(
                task_id=task.id,
                cost=0.40,
                inference_cost=0.40,
                started_at=datetime(2026, 7, 31, 22, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    await db.commit()

    july = await service.list_page(
        skip=0,
        limit=50,
        search=None,
        month="2026-07",
    )
    july_by_id = {item.id: item for item in july.items}

    assert july.month == "2026-07"
    assert july_by_id[first_topic.id].llm_calls == 5
    assert july_by_id[first_topic.id].inference_cost == pytest.approx(0.75)
    assert july_by_id[second_topic.id].llm_calls == 1
    assert july_by_id[second_topic.id].inference_cost == pytest.approx(0.05)
    assert "2026-07" in july.available_months
    assert "2026-08" in july.available_months

    august = await service.list_page(
        skip=0,
        limit=50,
        search=None,
        month="2026-08",
    )
    august_by_id = {item.id: item for item in august.items}
    assert august_by_id[first_topic.id].llm_calls == 1
    assert august_by_id[first_topic.id].inference_cost == pytest.approx(0.40)
    assert august_by_id[second_topic.id].inference_cost == 0.0


@pytest.mark.asyncio
async def test_list_page_includes_related_participants_teams_and_documents(
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        suffix = uuid4().hex[:8]
        title = Title(label=f"Topic relations {suffix}", gender="X")
        shared_team = AgentGroup(name=f"Planning {suffix}", order=2)
        second_team = AgentGroup(name=f"Design {suffix}", order=1)
        deleted_team = AgentGroup(name=f"Archived {suffix}")
        deleted_team.soft_delete()
        db.add_all([title, shared_team, second_team, deleted_team])
        await db.flush()
        agent = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Relations",
            code=f"topic-relations-{suffix}",
            agent_driver="internal",
            group_id=shared_team.id,
        )
        db.add(agent)
        await db.flush()

        db.add_all([
            AgentTeam(agent_id=agent.id, team_id=team.id)
            for team in (shared_team, second_team, deleted_team)
        ])

        topic = await service.create(TopicCreate(title="Renovation planning"))
        empty_topic = await service.create(TopicCreate(title="Unrelated topic"))
        assert topic.memory_item_id is not None
        contact_item_id = await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=agent.id,
                messaging_id="matrix",
                user_id="@nicolas:example.test",
                display_name="Nicolas",
            )
        )
        document, _created = await memory_service.create_item(
            MemoryItemCreate(
                owner_agent_id=agent.id,
                title="Renovation brief",
                payload=MemoryPayload(text="# Renovation brief"),
                memory_type="working",
                node_kind="document",
                filename="renovation-brief.md",
            )
        )
        await ensure_topic_memory_link(
            topic_item_id=topic.memory_item_id,
            memory_item_id=document.id,
        )
        db.add(
            Task(
                label="Prepare renovation",
                status=TaskStatus.SUCCESS,
                agent_id=agent.id,
                topic_id=topic.id,
                contact_memory_item_id=contact_item_id,
            )
        )
        await db.commit()

        page = await service.list_page(
            skip=0,
            limit=50,
            search=None,
        )
        by_id = {item.id: item for item in page.items}

        assert [item.model_dump() for item in by_id[topic.id].agents] == [
            {"id": agent.id, "name": "Alice Relations"}
        ]
        assert [item.model_dump() for item in by_id[topic.id].users] == [
            {
                "id": contact_item_id,
                "display_name": "Nicolas",
                "user_id": "@nicolas:example.test",
            }
        ]
        assert [item.model_dump() for item in by_id[topic.id].documents] == [
            {
                "id": document.id,
                "title": "Renovation brief",
                "filename": "renovation-brief.md",
            }
        ]
        assert by_id[empty_topic.id].agents == []
        assert by_id[empty_topic.id].users == []
        assert by_id[empty_topic.id].documents == []
        assert [item.model_dump() for item in by_id[topic.id].teams] == [
            {"id": second_team.id, "name": second_team.name},
            {"id": shared_team.id, "name": shared_team.name},
        ]
        assert by_id[empty_topic.id].teams == []

        other_team = AgentGroup(name=f"Private {suffix}")
        db.add(other_team)
        await db.flush()
        other_agent = Agent(
            title_id=title.id,
            first_name="Bob",
            last_name="Relations",
            code=f"topic-other-{suffix}",
            group_id=other_team.id,
        )
        db.add(other_agent)
        await db.flush()
        db.add_all([
            AgentTeam(agent_id=other_agent.id, team_id=shared_team.id),
            Task(label="Other work", agent_id=other_agent.id, topic_id=topic.id),
        ])
        await db.commit()
        for scope, expected_teams in (
            (None, {shared_team.id, second_team.id, other_team.id}),
            ([agent.id], {shared_team.id, second_team.id}),
            ([], set()),
        ):
            scoped_page = await service.list_page(
                skip=0, limit=50, search=None, agent_ids=scope,
            )
            related_teams = next(item.teams for item in scoped_page.items if item.id == topic.id)
            assert {team.id for team in related_teams} == expected_teams
            assert len(related_teams) == len(expected_teams)
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_candidate_preselection_fuses_vector_rank_and_falls_back_to_lexical(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        lexical = await service.create(
            TopicCreate(title="Database releases", keywords=["database", "release"])
        )
        vector = await service.create(
            TopicCreate(title="Operational procedures", keywords=["operations"])
        )
        anchor = await service.create(TopicCreate(title="General reference"))
        assert vector.memory_item_id is not None

        async def vector_ranking(
            query: str, *, limit: int = 100
        ) -> TopicProjectionRanking:
            assert query == "database release"
            assert limit >= 100
            return TopicProjectionRanking(
                matches=(
                    TopicProjectionMatch(
                        memory_item_id=vector.memory_item_id,
                        similarity=0.98,
                    ),
                ),
                model_key="test-vector",
            )

        monkeypatch.setattr(service, "rank_topic_projections", vector_ranking)
        ranked = await service.list_candidates(activity="database release")
        assert ranked[0].id == vector.id
        assert {candidate.id for candidate in ranked} == {
            lexical.id,
            vector.id,
            anchor.id,
        }

        async def degraded_ranking(
            query: str, *, limit: int = 100
        ) -> TopicProjectionRanking:
            del query, limit
            return TopicProjectionRanking(
                matches=(),
                degraded=True,
                degradation_reason="embedding_not_configured",
            )

        monkeypatch.setattr(service, "rank_topic_projections", degraded_ranking)
        fallback = await service.list_candidates(activity="database release")
        assert fallback[0].id == lexical.id
    finally:
        reset_storage_registry()
