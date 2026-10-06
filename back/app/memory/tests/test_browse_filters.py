from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.agent.models import Agent
from app.memory import MessengerContactObservation, observe_messenger_contact
from app.memory import retrieval, service
from app.memory.embedding import EmbeddingModel, MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryItem
from app.memory.schemas import (
    MemoryGraphRootsRequest,
    MemoryItemCreate,
    MemoryPayload,
    MemorySearchRequest,
)
from app.topic import TopicClassification, service as topic_service
from app.memory.temporal import MemoryTemporalAnchor, MemoryTemporalFilter


@pytest.mark.asyncio
@pytest.mark.parametrize('hybrid', [False, True])
@pytest.mark.parametrize('temporal', [None, MemoryTemporalFilter(target_at='2027-09-27T12:00Z', lookahead_hours=0)])
async def test_list_and_graph_filter_by_topic_and_interlocutor(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    temporal: MemoryTemporalFilter | None,
    hybrid: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, peer = agents
    async def missing_model() -> EmbeddingModel:
        raise MemoryEmbeddingNotConfiguredError("not configured")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
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
        page = await retrieval.browse_items(
            MemorySearchRequest(
                agent_id=owner.id,
                hybrid=hybrid,
                query="Durable" if hybrid else "",
                limit=50,
                filter_topic_item_id=topic_item_id,
                filter_contact_item_id=contact_item_id,
                temporal=temporal,
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


@pytest.mark.asyncio
@pytest.mark.parametrize('global_zone', ['UTC', 'Europe/Paris', 'America/Toronto'])
async def test_hybrid_list_unites_semantic_matches_with_calendar_and_paginated_sort(
    db, agents, memory_storage, monkeypatch, global_zone,
) -> None:
    from datetime import datetime
    from app.memory.tests.embedding_fixtures import published_chunk
    from app.memory.temporal import next_match

    monkeypatch.setenv('TZ', global_zone)
    owner, peer = agents
    model = EmbeddingModel(key="calendar-model", code="calendar-model", model_name="calendar-model",
                           base_url="http://embedding.invalid/v1", api_key=None)
    async def fake_model():
        return model
    async def fake_query(*args, **kwargs):
        return [1.0, 0.0, 0.0]
    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)
    anchors = [
        None,
        MemoryTemporalAnchor(month=9, day=27),
        MemoryTemporalAnchor(year=2027, month=9, day=27, hour=9, minute=30),
        MemoryTemporalAnchor(weekday=1, hour=15, minute=30),
        MemoryTemporalAnchor(month=9, day=28),
        MemoryTemporalAnchor(month=2, day=29),
        MemoryTemporalAnchor(hour=1, minute=30),
        MemoryTemporalAnchor(hour=2, minute=30),
    ]
    items = []
    for index, anchor in enumerate(anchors):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Appointment {index}", temporal=anchor,
            payload=MemoryPayload(text=f"Synthetic annual gathering number {index}."),
        ))
        items.append(item)
    hidden, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=peer.id, title="Private gathering", temporal=anchors[1],
        payload=MemoryPayload(text="Confidential annual gathering."),
    ))
    for item in [*items, hidden]:
        db.add(published_chunk(item_id=item.id, source_fingerprint=item.semantic_fingerprint,
            model_key=model.key, model_code=model.code, dimensions=3, chunk_index=0,
            text=item.search_text, embedding=[1.0, 0.0, 0.0]))
    await db.commit()
    # Ordinary content needs semantic recall; calendar matches ignore relevance.
    for instant in ["2027-09-27T13:30:45Z", "2028-02-29T12:00Z",
                    "2026-11-01T05:30Z", "2026-11-01T06:30Z", "2026-03-08T07:30Z"]:
        target = datetime.fromisoformat(instant)
        expected = [item.id for item, anchor in zip(items, anchors)
                    if anchor is None or next_match(anchor, target, target) is not None]
        request = MemorySearchRequest(agent_id=owner.id, hybrid=True, query="celebration rendezvous",
            temporal=MemoryTemporalFilter(target_at=target, lookahead_hours=0),
            sort_by="title", sort_desc=False, limit=1)
        result = await retrieval.browse_items(request)
        if expected:
            assert result.degradation_reason is None, instant
        assert result.total == len(expected), instant
        assert result.has_more == (len(expected) > 1)
        assert [hit.item.id for hit in result.hits] == expected[:1]
        if result.hits:
            assert result.hits[0].temporal_match_at is None
        for offset in range(1, len(expected)):
            page = await retrieval.browse_items(request.model_copy(update={"offset": offset}))
            assert [hit.item.id for hit in page.hits] == expected[offset:offset+1]
            assert page.total == len(expected)
            assert page.hits[0].temporal_match_at == target

    # Empty queries keep the ordinary exhaustive browse path and do not use embeddings.
    async def forbidden_provider():
        raise AssertionError("Empty browsing must not request embeddings")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", forbidden_provider)
    result = await retrieval.browse_items(request.model_copy(update={"query": ""}))
    assert result.total == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize('hybrid', [False, True])
async def test_calendar_browse_unites_ordinary_search_and_forced_matches(agents, memory_storage, monkeypatch, hybrid):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    owner, peer = agents
    async def missing_model():
        raise MemoryEmbeddingNotConfiguredError('not configured')
    monkeypatch.setattr(retrieval, 'resolve_embedding_model', missing_model)
    definitions = [
        ('A ordinary', owner.id, 'semantic', None),
        ('B scheduled', owner.id, 'working', MemoryTemporalAnchor(month=9, day=27)),
        ('C future', owner.id, 'semantic', MemoryTemporalAnchor(year=2028, month=9, day=27)),
        ('D other words', owner.id, 'working', None),
        ('E private', peer.id, 'semantic', MemoryTemporalAnchor(month=9, day=27)),
        ('F expired', owner.id, 'semantic', MemoryTemporalAnchor(month=9, day=27)),
    ]
    for title, agent_id, memory_type, anchor in definitions:
        await service.create_item(MemoryItemCreate(owner_agent_id=agent_id, title=title,
            memory_type=memory_type, temporal=anchor,
            payload=MemoryPayload(text='needle' if title[0] in 'ACEF' else 'unrelated birthday'),
            valid_until=datetime.now(timezone.utc)-timedelta(days=1) if title.startswith('F') else None))
    target = MemoryTemporalFilter(target_at='2027-09-27T12:00Z', lookahead_hours=0)
    request = MemorySearchRequest(agent_id=owner.id, hybrid=hybrid, query='needle',
        memory_types=['semantic'], temporal=target, sort_by='title', sort_desc=False, limit=1)
    first = await retrieval.browse_items(request)
    second = await retrieval.browse_items(request.model_copy(update={'offset': 1}))
    assert first.total == second.total == 2
    assert first.has_more and not second.has_more
    assert [hit.item.title for hit in first.hits + second.hits] == ['A ordinary', 'B scheduled']
    assert first.hits[0].temporal_match_at is None
    assert second.hits[0].temporal_match_at == target.target_at
    # Ordinary text/type/topic/contact criteria never veto a scheduled match.
    forced = await retrieval.browse_items(request.model_copy(update={
        'query': 'nomatch', 'filter_topic_item_id': uuid4(), 'filter_contact_item_id': uuid4()}))
    assert [hit.item.title for hit in forced.hits] == ['B scheduled']
    other_day = await retrieval.browse_items(request.model_copy(update={
        'temporal': MemoryTemporalFilter(target_at='2027-09-28T12:00Z', lookahead_hours=0)}))
    assert [hit.item.title for hit in other_day.hits] == ['A ordinary']
    unqueried = await retrieval.browse_items(request.model_copy(update={
        'query': '', 'memory_types': [], 'limit': 50}))
    assert [hit.item.title for hit in unqueried.hits] == ['A ordinary', 'B scheduled', 'D other words']
