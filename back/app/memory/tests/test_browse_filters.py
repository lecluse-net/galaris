from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.agent.models import Agent
from app.memory import MessengerContactObservation, observe_messenger_contact
from app.memory import service
from app.memory.models import MemoryItem
from app.memory.schemas import (
    MemoryGraphRootsRequest,
    MemoryItemCreate,
    MemoryPayload,
    MemorySearchRequest,
)
from app.topic import TopicClassification, service as topic_service


@pytest.mark.asyncio
async def test_list_and_graph_filter_by_topic_and_interlocutor(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    first_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Organisation")
    )
    second_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Voyages")
    )
    peer_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Dossier du pair")
    )
    assert first_topic.memory_item_id is not None
    assert second_topic.memory_item_id is not None
    assert peer_topic.memory_item_id is not None

    alice_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice-filter:example.test",
            display_name="Alice",
        )
    )
    bob_contact = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@bob-filter:example.test",
            display_name="Bob",
        )
    )
    await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=peer.id,
            messaging_id="matrix",
            user_id="@hidden-filter:example.test",
            display_name="Hidden peer contact",
        )
    )

    async def scoped_memory(
        title: str,
        *,
        topic_item_id: UUID,
        contact_item_id: UUID,
    ) -> MemoryItem:
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=title,
                payload=MemoryPayload(text=f"Durable fact for {title}."),
            )
        )
        await service.ensure_topic_contact_memory_scope(
            owner_agent_id=owner.id,
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
            memory_item_id=item.id,
            source_kind="task",
            source_ref=f"task:{item.id}",
        )
        return item

    organisation_alice = await scoped_memory(
        "Organisation avec Alice",
        topic_item_id=first_topic.memory_item_id,
        contact_item_id=alice_contact,
    )
    organisation_bob = await scoped_memory(
        "Organisation avec Bob",
        topic_item_id=first_topic.memory_item_id,
        contact_item_id=bob_contact,
    )
    voyages_alice = await scoped_memory(
        "Voyages avec Alice",
        topic_item_id=second_topic.memory_item_id,
        contact_item_id=alice_contact,
    )
    peer_memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Souvenir privé du pair",
            payload=MemoryPayload(text="Ce souvenir appartient uniquement au pair."),
        )
    )
    await service.ensure_topic_memory_link(
        topic_item_id=peer_topic.memory_item_id,
        memory_item_id=peer_memory.id,
    )

    async def search_ids(
        *,
        topic_item_id: UUID | None = None,
        contact_item_id: UUID | None = None,
    ) -> set[UUID]:
        page = await service.search_items(
            MemorySearchRequest(
                agent_id=owner.id,
                limit=50,
                filter_topic_item_id=topic_item_id,
                filter_contact_item_id=contact_item_id,
            )
        )
        return {hit.item.id for hit in page.hits}

    assert await search_ids(
        topic_item_id=first_topic.memory_item_id
    ) == {organisation_alice.id, organisation_bob.id}
    assert await search_ids(contact_item_id=alice_contact) == {
        organisation_alice.id,
        voyages_alice.id,
    }
    assert await search_ids(
        topic_item_id=first_topic.memory_item_id,
        contact_item_id=alice_contact,
    ) == {organisation_alice.id}

    graph = await service.list_graph_roots(
        MemoryGraphRootsRequest(
            agent_id=owner.id,
            topic_item_id=first_topic.memory_item_id,
            contact_item_id=alice_contact,
            limit=50,
        )
    )
    assert {node.id for node in graph.nodes} == {organisation_alice.id}

    options = await service.list_filter_options(owner.id)
    assert {option.id for option in options.topics} == {
        first_topic.memory_item_id,
        second_topic.memory_item_id,
    }
    assert {option.id for option in options.contacts} == {
        alice_contact,
        bob_contact,
    }

    unfiltered_graph = await service.list_graph_roots(
        MemoryGraphRootsRequest(agent_id=owner.id, limit=50)
    )
    graph_ids = {node.id for node in unfiltered_graph.nodes}
    assert first_topic.memory_item_id in graph_ids
    assert second_topic.memory_item_id in graph_ids
    assert peer_topic.memory_item_id not in graph_ids
