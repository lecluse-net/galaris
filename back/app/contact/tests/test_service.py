from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.contact import service as contact_service
from app.conversation import ConversationRound
from app.memory import (
    MessengerContactObservation,
    observe_messenger_contact,
)
from app.memory import service as memory_service
from app.memory.models import (
    MemoryContactIdentity,
    MemoryContactItem,
    MemoryItem,
    MemoryLink,
)
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.messenger import Message, Room
from app.task import Task, TaskStatus
from app.tools import ToolModel


@pytest.mark.asyncio
async def test_reachable_humans_filters_ai_and_deduplicates_canonical_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice_contact_id = uuid4()
    alice_matrix_id = uuid4()
    alice_telegram_id = uuid4()
    bob_id = uuid4()
    canonical_alice = SimpleNamespace(
        memory_item_id=alice_contact_id,
        display_name="Alice",
        identities=(
            SimpleNamespace(
                kind="messenger",
                namespace="matrix",
                external_id="@alice:example.test",
                galaris_user_id=None,
            ),
            SimpleNamespace(
                kind="messenger",
                namespace="telegram",
                external_id="alice-42",
                galaris_user_id=None,
            ),
        ),
    )

    def human(**values: object) -> SimpleNamespace:
        attributes: dict[str, object] = {
            "is_ai": False,
            "agent_id": None,
            "galaris_user_id": None,
        }
        attributes.update(values)
        return SimpleNamespace(**attributes)
    search = AsyncMock(
        return_value=[
            (
                11,
                3,
                "matrix",
                human(
                    id=alice_matrix_id,
                    external_id="@alice:example.test",
                    display_name="Alice Matrix",
                ),
            ),
            (
                12,
                4,
                "telegram",
                human(
                    id=alice_telegram_id,
                    external_id="alice-42",
                    display_name="Alice Telegram",
                ),
            ),
            (
                13,
                5,
                "matrix",
                human(id=bob_id, external_id="bob", display_name="Bob"),
            ),
            (
                14,
                5,
                "matrix",
                human(id=bob_id, external_id="bob", display_name="Bob duplicate"),
            ),
            (
                15,
                6,
                "matrix",
                human(
                    id=uuid4(),
                    external_id="agent-linked",
                    display_name="Agent linked",
                    agent_id=99,
                ),
            ),
            (
                16,
                7,
                "telegram",
                human(
                    id=uuid4(),
                    external_id="declared-bot",
                    display_name="Declared bot",
                    is_ai=True,
                ),
            ),
        ]
    )
    contacts = AsyncMock(return_value=((canonical_alice,), 1))
    monkeypatch.setattr(contact_service, "search_agent_users", search)
    monkeypatch.setattr(contact_service, "list_messenger_contacts", contacts)

    results = await contact_service.list_reachable_humans(
        agent_id=7,
        query="ali",
    )

    assert [(item.display_name, item.connection_id) for item in results] == [
        ("Alice", 11),
        ("Bob", 13),
    ]
    assert all(item.is_human for item in results)
    assert results[0].contact_item_id == alice_contact_id
    search.assert_awaited_once_with(7, "ali")
    contacts.assert_awaited_once_with(owner_agent_id=7, limit=500, offset=0)


@pytest.mark.asyncio
async def test_merge_repoints_identities_memory_and_conversation_lineage(
    db: AsyncSession, tmp_path: Path
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        suffix = uuid4().hex[:10]
        title = Title(label=f"Contact merge {suffix}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Contacts",
            code=f"contact-merge-{suffix}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()

        source_id = await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=owner.id,
                messaging_id="matrix",
                user_id="@alice:example.test",
                display_name="Alice Matrix",
            )
        )
        target_id = await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=owner.id,
                messaging_id="telegram",
                user_id="123456",
                display_name="Alice Telegram",
            )
        )
        source_memory, _ = await memory_service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Préférence observée sur Matrix",
                payload=MemoryPayload(text="Alice préfère le matin."),
            )
        )
        target_memory, _ = await memory_service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Préférence observée sur Telegram",
                payload=MemoryPayload(text="Alice préfère les messages courts."),
            )
        )
        await memory_service.ensure_contact_memory_scope(
            owner_agent_id=owner.id,
            contact_item_id=source_id,
            memory_item_id=source_memory.id,
            source_kind="task",
            source_ref=f"task:{uuid4()}",
        )
        await memory_service.ensure_contact_memory_scope(
            owner_agent_id=owner.id,
            contact_item_id=target_id,
            memory_item_id=target_memory.id,
            source_kind="task",
            source_ref=f"task:{uuid4()}",
        )
        db.add_all(
            [
                MemoryLink(
                    source_item_id=source_id,
                    target_item_id=source_memory.id,
                    relation_type="contact_contains",
                ),
                MemoryLink(
                    source_item_id=target_id,
                    target_item_id=source_memory.id,
                    relation_type="contact_contains",
                ),
                MemoryLink(
                    source_item_id=source_id,
                    target_item_id=target_memory.id,
                    relation_type="mentions",
                    confidence=0.8,
                    metadata_={"evidence": "source contact"},
                ),
                MemoryLink(
                    source_item_id=target_memory.id,
                    target_item_id=source_id,
                    relation_type="about",
                ),
                MemoryLink(
                    source_item_id=source_id,
                    target_item_id=target_id,
                    relation_type="related_to",
                ),
            ]
        )

        tool = ToolModel(
            code=f"contact-test-{suffix}",
            label="Contact test",
            description="",
            connection_schema={},
        )
        db.add(tool)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(
            connection_id=connection.id,
            external_id="room-1",
            label="Alice",
            kind="direct",
            conversation_type="text",
        )
        db.add(room)
        await db.flush()
        message = Message(
            connection_id=connection.id,
            platform="matrix",
            remote_message_id="message-1",
            direction="inbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            user_id="@alice:example.test",
            contact_memory_item_id=source_id,
            text="Bonjour",
        )
        round_ = ConversationRound(
            room_id=room.id,
            contact_memory_item_id=source_id,
            language="fr",
            status="FINISHED",
        )
        task = Task(
            label="Répondre à Alice",
            objective="Répondre à Alice",
            status=TaskStatus.CREATE,
            paused=False,
            ai=False,
            cost=0.0,
            effort="standard",
            auto_approve=False,
            agent_id=owner.id,
            contact_memory_item_id=source_id,
        )
        db.add_all([message, round_, task])
        await db.commit()

        result = await contact_service.merge_contacts(
            source_contact_item_id=source_id,
            target_contact_item_id=target_id,
        )

        assert result.contact.memory_item_id == target_id
        assert result.contact.linked_memory_count == 2
        assert result.rewired["messages"] == 1
        assert result.rewired["conversation_rounds"] == 1
        assert result.rewired["tasks"] == 1
        assert await db.get(MemoryItem, source_id) is None
        await db.refresh(message)
        await db.refresh(round_)
        await db.refresh(task)
        assert message.contact_memory_item_id == target_id
        assert round_.contact_memory_item_id == target_id
        assert task.contact_memory_item_id == target_id
        assert await db.scalar(
            select(func.count(MemoryContactIdentity.id)).where(
                MemoryContactIdentity.contact_item_id == target_id
            )
        ) == 2
        assert set(
            (
                await db.scalars(
                    select(MemoryContactItem.item_id).where(
                        MemoryContactItem.contact_item_id == target_id
                    )
                )
            ).all()
        ) == {source_memory.id, target_memory.id}
        assert await db.scalar(
            select(func.count(MemoryLink.id)).where(
                MemoryLink.source_item_id == target_id,
                MemoryLink.target_item_id == source_memory.id,
                MemoryLink.relation_type == "contact_contains",
            )
        ) == 1
        links = list((await db.scalars(select(MemoryLink))).all())
        assert {
            (link.source_item_id, link.target_item_id, link.relation_type)
            for link in links
        } == {
            (target_id, source_memory.id, "contact_contains"),
            (target_id, target_memory.id, "mentions"),
            (target_memory.id, target_id, "about"),
        }
        moved_link = next(link for link in links if link.relation_type == "mentions")
        assert moved_link.confidence == 0.8
        assert moved_link.metadata_ == {"evidence": "source contact"}
        assert result.rewired["memory_links"] == 2
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_forget_erases_contact_memories_and_clears_conversation_lineage(
    db: AsyncSession, tmp_path: Path
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        suffix = uuid4().hex[:10]
        title = Title(label=f"Contact forget {suffix}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Forget",
            code=f"contact-forget-{suffix}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()
        contact_id = await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=owner.id,
                messaging_id="matrix",
                user_id=f"@old-{suffix}:example.test",
                display_name="Ancien contact",
            )
        )
        memory, _ = await memory_service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Ancienne préférence",
                payload=MemoryPayload(text="Information à effacer définitivement."),
            )
        )
        await memory_service.ensure_contact_memory_scope(
            owner_agent_id=owner.id,
            contact_item_id=contact_id,
            memory_item_id=memory.id,
            source_kind="task",
            source_ref=f"task:{uuid4()}",
        )

        tool = ToolModel(
            code=f"contact-forget-test-{suffix}",
            label="Contact forget test",
            description="",
            connection_schema={},
        )
        db.add(tool)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(
            connection_id=connection.id,
            external_id=f"room-{suffix}",
            label="Ancien contact",
            kind="direct",
            conversation_type="text",
        )
        db.add(room)
        await db.flush()
        message = Message(
            connection_id=connection.id,
            platform="matrix",
            remote_message_id=f"message-{suffix}",
            direction="inbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            user_id=f"@old-{suffix}:example.test",
            contact_memory_item_id=contact_id,
            text="Bonjour",
        )
        round_ = ConversationRound(
            room_id=room.id,
            contact_memory_item_id=contact_id,
            language="fr",
            status="FINISHED",
        )
        task = Task(
            label="Ancienne tâche",
            objective="Ancienne tâche",
            status=TaskStatus.CREATE,
            paused=False,
            ai=False,
            cost=0.0,
            effort="standard",
            auto_approve=False,
            agent_id=owner.id,
            contact_memory_item_id=contact_id,
        )
        db.add_all([message, round_, task])
        await db.commit()

        result = await contact_service.forget_contact(contact_item_id=contact_id)

        assert result.forgotten_contact_item_id == contact_id
        assert result.forgotten_memories == 1
        assert result.resources_deleted == 2
        assert result.cleared == {
            "messages": 1,
            "conversation_rounds": 1,
            "tasks": 1,
        }
        assert await db.get(
            MemoryItem,
            contact_id,
            execution_options={"include_historized": True},
        ) is None
        forgotten_memory = (
            await db.execute(
                select(
                    MemoryItem.deleted_at,
                    MemoryItem.title,
                    MemoryItem.search_text,
                )
                .where(MemoryItem.id == memory.id)
                .execution_options(include_historized=True)
            )
        ).one()
        assert forgotten_memory.deleted_at is not None
        assert forgotten_memory.title == "Forgotten memory"
        assert forgotten_memory.search_text == ""
        assert await db.scalar(
            select(func.count(MemoryContactIdentity.id)).where(
                MemoryContactIdentity.contact_item_id == contact_id
            )
        ) == 0
        assert await db.scalar(
            select(func.count(MemoryContactItem.id)).where(
                MemoryContactItem.contact_item_id == contact_id
            )
        ) == 0
        await db.refresh(message)
        await db.refresh(round_)
        await db.refresh(task)
        assert message.contact_memory_item_id is None
        assert round_.contact_memory_item_id is None
        assert task.contact_memory_item_id is None
    finally:
        reset_storage_registry()
