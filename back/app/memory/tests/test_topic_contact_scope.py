from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.memory import (
    MessengerContactObservation,
    acquire_memory,
    observe_messenger_contact,
)
from app.memory import retrieval, service
from app.memory.models import (
    MemoryContactItem,
    MemoryItem,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)
from app.memory.schemas import (
    MemoryAcquisitionCreate,
    MemoryAcquisitionResult,
    MemoryGrantUpdate,
    MemoryItemCreate,
    MemoryLinkCreate,
    MemoryPayload,
    MemoryRecallRequest,
)
from app.topic import TopicClassification, service as topic_service


@pytest.mark.asyncio
@pytest.mark.parametrize("access_mode", ["public", "grant", "denied"])
async def test_contact_acquisition_checks_unloaded_target_grants(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    access_mode: str,
) -> None:
    del memory_storage
    owner, peer = agents
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@recovery:example.test",
            display_name="Recovery contact",
        )
    )
    target, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Shared operational fact",
            payload=MemoryPayload(text="A fact confirmed by another contact."),
            visibility="public" if access_mode == "public" else "private",
        )
    )
    if access_mode == "grant":
        await service.set_item_grant(target.id, owner.id, MemoryGrantUpdate(can_write=False))
    target_id = target.id
    original_revision = target.revision
    # Recovery starts without relationships previously loaded by the creation path.
    db.expire(target, ["grants"])
    data = MemoryAcquisitionCreate(
        agent_id=owner.id,
        target_item_id=target_id,
        title="Confirming source",
        content="The contact confirms this fact.",
        source_kind="task",
        source_ref="task:unloaded-target",
        metadata={
            "deduplication_decision": "merge",
            "scope_mode": "contact",
            "contact_item_id": str(contact_id),
        },
    )
    if access_mode == "denied":
        with pytest.raises(service.MemoryPermissionError):
            await acquire_memory(data)
        return

    result = await acquire_memory(data)
    assert result.status == "merged"
    assert result.memory_id == target_id
    assert await service.source_refs(target_id) == ["task:unloaded-target"]
    assert target.revision == original_revision
    assert await db.scalar(
        select(MemoryContactItem).where(MemoryContactItem.item_id == target_id)
    ) is None


@pytest.mark.asyncio
async def test_conversation_memories_are_isolated_by_topic_and_exact_contact(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Organisation familiale")
    )
    assert topic.memory_item_id is not None
    alice_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice:example.test",
            display_name="Alice",
        )
    )
    bob_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@bob:example.test",
            display_name="Bob",
        )
    )
    alice_memory, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence d'Alice",
            payload=MemoryPayload(text="Alice préfère recevoir les comptes-rendus le matin."),
        )
    )
    bob_memory, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence de Bob",
            payload=MemoryPayload(text="Bob préfère recevoir les comptes-rendus le soir."),
        )
    )
    await service.ensure_topic_contact_memory_scope(
        owner_agent_id=owner.id,
        topic_item_id=topic.memory_item_id,
        contact_item_id=alice_contact,
        memory_item_id=alice_memory.id,
        source_kind="task",
        source_ref="task:00000000-0000-0000-0000-000000000001",
    )
    await service.ensure_topic_contact_memory_scope(
        owner_agent_id=owner.id,
        topic_item_id=topic.memory_item_id,
        contact_item_id=bob_contact,
        memory_item_id=bob_memory.id,
        source_kind="task",
        source_ref="task:00000000-0000-0000-0000-000000000002",
    )
    await service.create_link(
        MemoryLinkCreate(
            source_item_id=alice_memory.id,
            target_item_id=bob_memory.id,
            relation_type="related_to",
            confidence=1.0,
        ),
        actor_agent_id=owner.id,
    )

    alice_recall = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="",
            topic_item_id=topic.memory_item_id,
            contact_item_id=alice_contact,
        )
    )
    bob_recall = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="",
            topic_item_id=topic.memory_item_id,
            contact_item_id=bob_contact,
        )
    )

    assert [hit.item.id for hit in alice_recall.hits] == [alice_memory.id]
    assert [hit.item.id for hit in bob_recall.hits] == [bob_memory.id]
    scopes = list((await db.scalars(select(MemoryTopicContactScope))).all())
    assert {(scope.topic_item_id, scope.contact_item_id) for scope in scopes} == {
        (topic.memory_item_id, alice_contact),
        (topic.memory_item_id, bob_contact),
    }
    assert len(list((await db.scalars(select(MemoryTopicContactItem))).all())) == 2
    topic_item = await db.get(MemoryItem, topic.memory_item_id)
    assert topic_item is not None and topic_item.visibility == "public"

    with pytest.raises(
        service.MemoryConflictError,
        match="cannot be shared between distinct contacts",
    ):
        await service.ensure_topic_contact_memory_scope(
            owner_agent_id=owner.id,
            topic_item_id=topic.memory_item_id,
            contact_item_id=bob_contact,
            memory_item_id=alice_memory.id,
            source_kind="task",
            source_ref="task:00000000-0000-0000-0000-000000000003",
        )

    target = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Organisation du foyer")
    )
    assert target.memory_item_id is not None
    await topic_service.merge(topic.id, target.id)
    moved_scopes = list(
        (await db.scalars(select(MemoryTopicContactScope))).all()
    )
    assert {scope.topic_item_id for scope in moved_scopes} == {
        target.memory_item_id
    }


def test_conversation_scope_accepts_contact_before_topic() -> None:
    request = MemoryRecallRequest(
        agent_id=1,
        contact_item_id=uuid4(),
    )
    assert request.topic_item_id is None

    topic_request = MemoryRecallRequest(
        agent_id=1,
        topic_item_id=uuid4(),
    )
    assert topic_request.contact_item_id is None


@pytest.mark.asyncio
async def test_contact_scope_is_effective_before_topic_classification(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    alice_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice-pending-topic:example.test",
        )
    )
    bob_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@bob-pending-topic:example.test",
        )
    )
    alice_memory, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence non classée d'Alice",
            payload=MemoryPayload(text="Alice préfère les réponses courtes."),
        )
    )
    bob_memory, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence non classée de Bob",
            payload=MemoryPayload(text="Bob préfère les réponses détaillées."),
        )
    )
    global_memory, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Note globale non conversationnelle",
            payload=MemoryPayload(text="Préférence générique de l'agent."),
        )
    )
    await service.ensure_contact_memory_scope(
        owner_agent_id=owner.id,
        contact_item_id=alice_contact,
        memory_item_id=alice_memory.id,
        source_kind="task",
        source_ref=f"task:{uuid4()}",
    )
    await service.ensure_contact_memory_scope(
        owner_agent_id=owner.id,
        contact_item_id=bob_contact,
        memory_item_id=bob_memory.id,
        source_kind="conversation_round",
        source_ref=f"conversation_round:{uuid4()}",
    )

    recalled = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="préférence",
            contact_item_id=alice_contact,
        )
    )

    recalled_ids = {hit.item.id for hit in recalled.hits}
    assert alice_memory.id in recalled_ids
    assert bob_memory.id not in recalled_ids
    assert global_memory.id in recalled_ids

    strict_recall = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="préférence",
            contact_item_id=alice_contact,
            strict_contact_scope=True,
        )
    )
    strict_ids = {hit.item.id for hit in strict_recall.hits}
    assert alice_memory.id in strict_ids
    assert bob_memory.id not in strict_ids
    assert global_memory.id not in strict_ids
    scopes = list((await db.scalars(select(MemoryContactItem))).all())
    assert {(scope.contact_item_id, scope.item_id) for scope in scopes} >= {
        (alice_contact, alice_memory.id),
        (bob_contact, bob_memory.id),
    }


@pytest.mark.asyncio
async def test_identical_content_is_not_deduplicated_across_contacts(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Préférences de livraison")
    )
    assert topic.memory_item_id is not None
    alice_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice-delivery:example.test",
            display_name="Alice",
        )
    )
    bob_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@bob-delivery:example.test",
            display_name="Bob",
        )
    )

    async def acquire_for(
        contact_id: UUID, source_ref: str
    ) -> MemoryAcquisitionResult:
        return await acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=owner.id,
                title="Préférence de livraison",
                content="La livraison doit avoir lieu le mardi matin.",
                source_kind="task",
                source_ref=source_ref,
                metadata={
                    "scope_mode": "topic_contact",
                    "topic_item_id": str(topic.memory_item_id),
                    "contact_item_id": str(contact_id),
                },
                idempotency_key=uuid4().hex,
            )
        )

    alice_result = await acquire_for(alice_contact, f"task:{uuid4()}")
    assert alice_result.memory_id is not None
    await service.ensure_topic_contact_memory_scope(
        owner_agent_id=owner.id,
        topic_item_id=topic.memory_item_id,
        contact_item_id=alice_contact,
        memory_item_id=alice_result.memory_id,
        source_kind="task",
        source_ref=f"task:{uuid4()}",
    )
    bob_result = await acquire_for(bob_contact, f"task:{uuid4()}")
    assert bob_result.memory_id is not None
    assert bob_result.memory_id != alice_result.memory_id
    await service.ensure_topic_contact_memory_scope(
        owner_agent_id=owner.id,
        topic_item_id=topic.memory_item_id,
        contact_item_id=bob_contact,
        memory_item_id=bob_result.memory_id,
        source_kind="task",
        source_ref=f"task:{uuid4()}",
    )

    with pytest.raises(
        service.MemoryConflictError,
        match="outside its contact scope",
    ):
        await acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=owner.id,
                action="update",
                target_item_id=alice_result.memory_id,
                title="Préférence de livraison modifiée",
                content="La livraison doit avoir lieu le vendredi.",
                source_kind="task",
                source_ref=f"task:{uuid4()}",
                metadata={
                    "scope_mode": "topic_contact",
                    "topic_item_id": str(topic.memory_item_id),
                    "contact_item_id": str(bob_contact),
                },
                idempotency_key=uuid4().hex,
            )
        )


@pytest.mark.asyncio
async def test_link_can_add_current_contact_and_topic_to_agent_owned_memory(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Décisions techniques")
    )
    assert topic.memory_item_id is not None
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@nicolas-link:example.test",
            display_name="Nicolas",
        )
    )
    existing, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Décision durable",
            payload=MemoryPayload(text="Le gel intégral reste en vigueur."),
        )
    )

    result = await acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=owner.id,
            action="create",
            target_item_id=existing.id,
            title="Source liée",
            content="Le gel intégral reste en vigueur.",
            source_kind="task",
            source_ref=f"task:{uuid4()}",
            metadata={
                "deduplication_decision": "merge",
                "scope_mode": "topic_contact",
                "topic_item_id": str(topic.memory_item_id),
                "contact_item_id": str(contact_id),
            },
        )
    )

    assert result.status == "merged"
    assert result.memory_id == existing.id
    direct_scope = await db.scalar(
        select(MemoryContactItem).where(MemoryContactItem.item_id == existing.id)
    )
    assert direct_scope is not None
    assert direct_scope.contact_item_id == contact_id
    exact_scope = await db.scalar(
        select(MemoryTopicContactScope)
        .join(
            MemoryTopicContactItem,
            MemoryTopicContactItem.scope_id == MemoryTopicContactScope.id,
        )
        .where(
            MemoryTopicContactItem.item_id == existing.id,
            MemoryTopicContactScope.topic_item_id == topic.memory_item_id,
            MemoryTopicContactScope.contact_item_id == contact_id,
        )
    )
    assert exact_scope is not None
