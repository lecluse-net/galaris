from __future__ import annotations

import asyncio
import gc
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.memory import service, topic_maintenance
from app.memory.embedding import EmbeddingModel
from app.memory.models import MemoryEmbeddingChunk, MemoryItem, MemoryLink
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.topic import TopicClassification, service as topic_service


@pytest.mark.asyncio
@pytest.mark.parametrize("dimensions", [3, 768])
async def test_topic_maintenance_suggests_without_mutating_canonical_membership(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    dimensions: int,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="topic-maintenance-model",
        code="topic-maintenance-vector",
        model_name="topic-maintenance-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    topics = [
        await topic_service.create_from_classification(
            TopicClassification(action="create", title=title)
        )
        for title in (
            "Software releases",
            "Release operations",
            "Team organisation",
        )
    ]
    assert all(topic.memory_item_id is not None for topic in topics)
    topic_items = [
        await db.get(MemoryItem, topic.memory_item_id)
        for topic in topics
        if topic.memory_item_id is not None
    ]
    assert all(item is not None for item in topic_items)
    resolved_topics = [item for item in topic_items if item is not None]

    async def memory(title: str) -> MemoryItem:
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=title,
                payload=MemoryPayload(text=f"Evidence for {title}."),
            )
        )
        return item

    orphan = await memory("Unattached release procedure")
    first_group = [
        await memory("Team cluster A1"),
        await memory("Team cluster A2"),
        await memory("Team cluster A3"),
        await memory("Team cluster A4"),
    ]
    second_group = [
        await memory("Team cluster B1"),
        await memory("Team cluster B2"),
    ]
    organisation_topic = resolved_topics[2]
    for item in [*first_group, *second_group]:
        await service.ensure_topic_memory_link(
            topic_item_id=organisation_topic.id,
            memory_item_id=item.id,
        )

    vectors = [
        (resolved_topics[0], [1.0, 0.0, 0.0]),
        (resolved_topics[1], [0.99, 0.1, 0.0]),
        (resolved_topics[2], [0.0, 1.0, 0.0]),
        (orphan, [1.0, 0.0, 0.0]),
        (first_group[0], [1.0, 0.0, 0.0]),
        # The endpoints are dissimilar, but the intermediate memories connect
        # them into one cluster. Redundant edges must not change that partition.
        (first_group[1], [0.8, 0.6, 0.0]),
        (first_group[2], [0.8, 0.6, 0.0]),
        (first_group[3], [0.28, 0.96, 0.0]),
        (second_group[0], [-1.0, 0.0, 0.0]),
        (second_group[1], [-0.99, -0.1, 0.0]),
    ]
    db.add_all(
        [
            MemoryEmbeddingChunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=dimensions,
                chunk_index=chunk_index,
                text=item.search_text,
                embedding=vector + [0.0] * (dimensions - len(vector)),
            )
            for item, vector in vectors
            for chunk_index in range(256 if dimensions == 768 else 1)
        ]
    )
    await db.commit()

    async def fake_model() -> EmbeddingModel:
        return model

    monkeypatch.setattr(
        topic_maintenance,
        "resolve_embedding_model",
        fake_model,
    )
    # Collect cycles from fixture preparation and preceding scenarios before
    # timing this operation; full-suite GC is not topic-planning CPU work.
    gc.collect()
    # A populated index must leave the loop available to concurrent HTTP/audio.
    loop = asyncio.get_running_loop()
    ticks: list[float] = []
    running = True

    async def heartbeat() -> None:
        while running:
            ticks.append(loop.time())
            await asyncio.sleep(0.01)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        plan = await topic_maintenance.build_topic_maintenance_plan()
    finally:
        ticks.append(loop.time())
        running = False
        await heartbeat_task
        topic_maintenance.stop_topic_maintenance()
    if dimensions == 768:
        assert len(ticks) > 2
        assert max(later - earlier for earlier, later in zip(ticks, ticks[1:])) < 0.25
    assert plan is not None
    relation_types = {item.relation_type for item in plan.suggestions}
    assert relation_types == {
        topic_maintenance.TOPIC_MEMBERSHIP_CANDIDATE,
        topic_maintenance.TOPIC_MEMBERSHIP_ANOMALY,
        topic_maintenance.TOPIC_MERGE_CANDIDATE,
        topic_maintenance.TOPIC_SPLIT_CANDIDATE,
    }
    orphan_suggestion = next(
        item
        for item in plan.suggestions
        if item.relation_type
        == topic_maintenance.TOPIC_MEMBERSHIP_CANDIDATE
        and item.target_item_id == orphan.id
    )
    assert orphan_suggestion.source_item_id == resolved_topics[0].id
    split_suggestion = next(
        item
        for item in plan.suggestions
        if item.relation_type == topic_maintenance.TOPIC_SPLIT_CANDIDATE
    )
    assert split_suggestion.metadata["topic_item_id"] == str(
        organisation_topic.id
    )
    assert {
        frozenset(split_suggestion.metadata["first_group"]),
        frozenset(split_suggestion.metadata["second_group"]),
    } == {
        frozenset(str(item.id) for item in first_group),
        frozenset(str(item.id) for item in second_group),
    }

    canonical_before = int(
        await db.scalar(
            select(func.count(MemoryLink.id)).where(
                MemoryLink.relation_type == "topic_contains",
                MemoryLink.suggested.is_(False),
            )
        )
        or 0
    )
    applied = await topic_maintenance.apply_topic_maintenance_plan(plan)
    assert applied.created == len(plan.suggestions)
    generated = list(
        (
            await db.scalars(
                select(MemoryLink).where(
                    MemoryLink.relation_type.in_(
                        topic_maintenance.SUGGESTED_RELATIONS
                    )
                )
            )
        ).all()
    )
    assert len(generated) == len(plan.suggestions)
    assert all(link.suggested for link in generated)
    assert all(
        link.metadata_["generated_by"] == topic_maintenance.GENERATED_BY
        for link in generated
    )
    assert int(
        await db.scalar(
            select(func.count(MemoryLink.id)).where(
                MemoryLink.relation_type == "topic_contains",
                MemoryLink.suggested.is_(False),
            )
        )
        or 0
    ) == canonical_before

    idempotent = await topic_maintenance.apply_topic_maintenance_plan(plan)
    assert (idempotent.created, idempotent.updated, idempotent.removed) == (
        0,
        0,
        0,
    )
    cleared = await topic_maintenance.apply_topic_maintenance_plan(
        replace(plan, suggestions=())
    )
    assert cleared.removed == len(plan.suggestions)
    assert int(
        await db.scalar(
            select(func.count(MemoryLink.id)).where(
                MemoryLink.relation_type.in_(
                    topic_maintenance.SUGGESTED_RELATIONS
                )
            )
        )
        or 0
    ) == 0
