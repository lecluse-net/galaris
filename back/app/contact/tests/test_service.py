from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.contact import service as contact_service
from app.contact.schemas import ContactUpdate
from app.conversation import ConversationRound
from app.memory import (
    MessengerContactObservation,
    observe_messenger_contact,
)
from app.memory import service as memory_service
from app.memory.tests.conftest import memory_storage as memory_storage
from app.memory.models import (
    MemoryContactIdentity,
    MemoryContactItem,
    MemoryItem,
    MemoryLink,
)
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.messenger import Message, Room
from app.task import Task, TaskStatus
from app.tools import ToolModel
from tests.sql_reads import measured_reads


async def seed_reachable_directory(db, count):
    from app.messenger import create_internal_room
    from app.memory import update_messenger_contact

    title = Title(label="Synthetic bounded directory", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, first_name="Synthetic", last_name=f"Directory {index}", code=uuid4().hex)
        for index in range(2)]
    db.add_all(agents)
    await db.flush()
    owner, other = agents
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    assert tool is not None
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.user_id, agent_id=owner.id)
    assert room is not None
    own_contact = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id="internal", user_id=f"user:{owner.user_id}", galaris_user_id=owner.user_id,
        display_name="Synthetic channel label"))
    foreign_contact = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=other.id,
        messaging_id="internal", user_id=f"user:{owner.user_id}", galaris_user_id=owner.user_id,
        display_name="Synthetic foreign label"))
    await update_messenger_contact(contact_item_id=own_contact, display_name="Synthetic canonical person")
    await update_messenger_contact(contact_item_id=foreign_contact, display_name="Synthetic foreign private name")
    content = "Synthetic unrelated contact."
    noise = "Synthetic unrelated private metadata. " * 220
    records = [MemoryItem(owner_agent_id=owner.id, memory_resource_id=f"synthetic-contact-{uuid4().hex}",
        memory_content=content, memory_content_hash=hashlib.sha256(content.encode()).hexdigest(),
        memory_size_bytes=len(content.encode()), search_title=f"Contact — Synthetic unrelated {index}",
        metadata_={"synthetic_details": noise}, source_managed=True, managed_source_kind="messenger_contact",
        managed_source_ref=f"synthetic-{uuid4().hex}", memory_read_only=True) for index in range(count)]
    db.add_all(records)
    await db.flush()
    db.add_all([MemoryContactIdentity(owner_agent_id=owner.id, contact_item_id=record.id,
        identity_kind="messenger", namespace="synthetic-unrelated", external_id=f"person-{index}",
        display_name=f"Synthetic unrelated {index}") for index, record in enumerate(records)])
    await db.commit()
    return owner.id, connection.id, own_contact, foreign_contact


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 501, 2001])
async def test_reachable_directory_bounds_canonical_reads_and_keeps_owner_names_and_routes(db, memory_storage, count):
    owner_id, connection_id, own_contact, foreign_contact = await seed_reachable_directory(db, count)
    db.expunge_all()
    connection = await db.connection()
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT") and re.search(r"\b(?:FROM|JOIN)\s+(?:public\.)?memory_", statement, re.IGNORECASE):
            captured.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        async with measured_reads(db, f"reachable-directory-{count}") as reads:
            people = await contact_service.list_reachable_humans(agent_id=owner_id)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert len(people) == 1 and people[0].contact_item_id == own_contact
    assert people[0].display_name == "Synthetic canonical person"
    assert people[0].contact_item_id != foreign_contact and people[0].connection_id == connection_id
    canonical_reads = [statement for statement in reads
        if re.search(r"\b(?:FROM|JOIN)\s+(?:public\.)?memory_", statement, re.IGNORECASE)]
    assert len(canonical_reads) <= 6, "Canonical lookup work must depend on reachable identities rather than the whole history"
    buffers = 0
    for statement, parameters in captured:
        result = await connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
        plan = result.scalar_one()[0]["Plan"]
        buffers += plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0)
    assert buffers <= 2000, f"Canonical lookup must not re-scan the owner's identities for every contact: {buffers} buffers"
    assert await db.scalar(select(func.count(MemoryItem.id)).where(MemoryItem.owner_agent_id == owner_id)) == count + 1
    await contact_service.update_contact(contact_item_id=own_contact,
        data=ContactUpdate(display_name="Synthetic renamed person"))
    reopened = await contact_service.list_reachable_humans(agent_id=owner_id)
    assert reopened[0].contact_item_id == own_contact and reopened[0].display_name == "Synthetic renamed person"


@pytest.mark.asyncio
async def test_contact_identity_filters_are_exact_owner_scoped_and_explicit_empty_is_empty(db, memory_storage):
    from app.memory import list_messenger_contacts

    owner_id, _connection, own_contact, foreign_contact = await seed_reachable_directory(db, 2)
    owner = await db.get(Agent, owner_id)
    db.add(MemoryContactIdentity(owner_agent_id=owner_id, contact_item_id=own_contact,
        identity_kind="messenger", namespace="matrix", external_id="Synthetic-Case",
        display_name="Synthetic alias"))
    await db.commit()
    for kwargs in (
        {"messenger_identities": [("matrix", "Synthetic-Case")]},
        {"galaris_user_ids": [owner.user_id]},
        {"messenger_identities": [("matrix", "Synthetic-Case")], "galaris_user_ids": [owner.user_id]},
    ):
        records, total = await list_messenger_contacts(owner_agent_id=owner_id, **kwargs)
        assert total == len(records) == 1 and records[0].memory_item_id == own_contact
        assert records[0].memory_item_id != foreign_contact
    for key in (("matrix", "synthetic-case"), ("telegram", "Synthetic-Case")):
        assert await list_messenger_contacts(owner_agent_id=owner_id, messenger_identities=[key]) == ((), 0)
    async with measured_reads(db, "explicit-empty-canonical-identities") as reads:
        assert await list_messenger_contacts(owner_agent_id=owner_id, messenger_identities=[]) == ((), 0)
    assert not reads
    records, total = await list_messenger_contacts(owner_agent_id=owner_id)
    assert total == len(records) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [501, 1001])
async def test_many_reachable_routes_keep_every_canonical_name_and_exact_route(monkeypatch, count):
    keys = [f"synthetic-{index:04}" for index in range(count)]
    records = {key: SimpleNamespace(memory_item_id=uuid4(), display_name=f"Canonical {index:04}",
        identities=(SimpleNamespace(kind="messenger", namespace="matrix", external_id=key, galaris_user_id=None),))
        for index, key in enumerate(keys)}
    users = [(11, 3, "matrix", SimpleNamespace(id=uuid4(), external_id=key,
        display_name="Synthetic channel name", is_ai=False, agent_id=None, galaris_user_id=None)) for key in keys]

    async def lookup(*, owner_agent_id, limit, offset, messenger_identities=None, galaris_user_ids=None):
        selected = [records[key] for key in keys if messenger_identities is None or ("matrix", key) in messenger_identities]
        return tuple(selected[offset:offset + limit]), len(selected)

    monkeypatch.setattr(contact_service, "search_agent_users", AsyncMock(return_value=users))
    monkeypatch.setattr(contact_service, "list_messenger_contacts", lookup)
    people = await contact_service.list_reachable_humans(agent_id=7)
    assert len(people) == count
    assert [(person.contact_item_id, person.display_name, person.connection_id, person.platform, person.user_id)
        for person in people] == [(records[key].memory_item_id, records[key].display_name, 11, "matrix", key) for key in keys]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 501])
async def test_empty_reachable_search_skips_canonical_history_and_reopens_with_a_human(db, count):
    from app.messenger import create_internal_room

    title = Title(label="Synthetic empty directory", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(title_id=title.id, first_name="Synthetic", last_name="Directory", code=uuid4().hex)
    db.add(owner)
    await db.flush()
    contacts = [MemoryItem(owner_agent_id=owner.id,
        memory_resource_id=f"synthetic-contact-{uuid4().hex}", memory_content="Synthetic contact information.",
        memory_content_hash=hashlib.sha256(b"Synthetic contact information.").hexdigest(),
        memory_size_bytes=len(b"Synthetic contact information."),
        search_title=f"Contact — Synthetic contact {index}", source_managed=True,
        managed_source_kind="messenger_contact", managed_source_ref=f"synthetic-{uuid4().hex}",
        memory_read_only=True) for index in range(count)]
    db.add_all(contacts)
    await db.flush()
    db.add_all([MemoryContactIdentity(owner_agent_id=owner.id, contact_item_id=item.id,
        identity_kind="messenger", namespace="synthetic", external_id=f"synthetic-{index}",
        display_name=f"Synthetic contact {index}") for index, item in enumerate(contacts)])
    await db.commit()
    async with measured_reads(db, f"empty-contact-directory-{count}") as reads:
        assert await contact_service.list_reachable_humans(agent_id=owner.id, query="unmatched synthetic search") == ()
    assert len(reads) <= 1, "An empty route search must not scan the canonical contact history"
    assert await db.scalar(select(func.count(MemoryItem.id)).where(MemoryItem.owner_agent_id == owner.id)) == count

    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    assert tool is not None
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.user_id, agent_id=owner.id)
    assert room is not None
    await db.commit()
    people = await contact_service.list_reachable_humans(agent_id=owner.id)
    assert len(people) == 1 and people[0].galaris_user_id == owner.user_id
    assert people[0].connection_id == connection.id and people[0].is_human
    assert await contact_service.list_reachable_humans(agent_id=owner.id, query="unmatched synthetic search") == ()


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
    search.assert_awaited_once_with(7, "ali", require_internal_room=True)
    contacts.assert_awaited_once()
    assert contacts.await_args.kwargs["owner_agent_id"] == 7
    assert set(contacts.await_args.kwargs["messenger_identities"]) == {
        ("matrix", "@alice:example.test"), ("telegram", "alice-42"), ("matrix", "bob"),
    }
    assert not contacts.await_args.kwargs["galaris_user_ids"]


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
        from app.messenger import project_agent_messages
        from app.agent.conversation_context import message_prompt

        raw = {"sender_contact_id": str(message.contact_memory_item_id),
            "sender_display_name": "Remote alias", "sender_external_id": "remote-account",
            "sender": {"id": "remote-account", "display_name": "Remote alias"},
            "text": "Bonjour", "requester_user_id": None}
        projected = (await project_agent_messages([raw], owner_agent_id=owner.id))[0]
        assert projected["sender_contact_id"] == str(target_id)
        assert projected["sender_contact_label"] == "Alice Telegram"
        assert projected["requester_user_id"] is None
        prompt = message_prompt(projected)
        assert "Alice Telegram" in prompt and str(target_id) in prompt
        assert "Remote alias" not in prompt and "remote-account" not in prompt
        assert raw["sender_display_name"] == "Remote alias"
        from app.agent.contracts import AgentContextRequest, AgentSnapshot
        from app.messenger.agent_identity import contact_identity_context_provider

        context = await contact_identity_context_provider(AgentContextRequest(
            task_id=None,
            agent=AgentSnapshot(id=owner.id, code=owner.code, first_name="Synthetic", last_name="Agent", driver_code="internal"),
            objective="Answer", contact_memory_item_id=target_id, include_historical_context=False,
        ))
        assert "Alice Telegram" in context.shared_context and str(target_id) in context.shared_context
        assert "Remote alias" not in context.shared_context
        for identity in [None, str(uuid4()), str(target_id)]:
            unresolved = (await project_agent_messages([{**raw, "sender_contact_id": identity}], owner_agent_id=owner.id + 1000000))[0]
            assert unresolved["sender_display_name"] == "Interlocutor"
            assert unresolved["sender_contact_id"] is None
            assert "Remote alias" not in message_prompt(unresolved)
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
        # Only the linked ordinary memory owns stored content; the contact is live.
        assert result.resources_deleted == 1
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
