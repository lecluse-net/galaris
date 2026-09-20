from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.dream import monitoring_service
from app.dream.mechanisms.memory_maintenance import memory_maintenance_mechanism
from app.dream.models import DreamReceipt
from app.memory import maintenance, service
from app.memory.models import (
    MemoryEmbeddingChunk,
    MemoryFinding,
    MemoryItem,
    MemorySource,
)
from app.memory.schemas import (
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryPayload,
    MemorySearchRequest,
    MemorySourceCreate,
)
from core.params.runtime_settings import runtime_settings


@pytest.mark.asyncio
async def test_dream_claims_memory_detection_without_exposing_it_in_gauges(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Souvenir ancien",
            payload=MemoryPayload(text="Ce souvenir doit seulement être signalé."),
            source=MemorySourceCreate(source_kind="test", source_ref="test:dream-aging"),
        )
    )
    await db.execute(
        update(MemoryItem)
        .where(MemoryItem.id == item.id)
        .values(updated_at=datetime.now(timezone.utc) - timedelta(days=60))
    )
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_AFTER_DAYS", 30)

    claim = await memory_maintenance_mechanism.claim_one()

    assert claim is not None
    assert claim.subject_kind == "memory_item"
    prepared = await memory_maintenance_mechanism.prepare(claim)
    assert await memory_maintenance_mechanism.apply(claim, prepared.payload) == 1
    finding = await db.scalar(
        select(MemoryFinding).where(
            MemoryFinding.primary_item_id == item.id,
            MemoryFinding.kind == "aging",
        )
    )
    assert finding is not None
    assert finding.status == "pending"
    assert await memory_maintenance_mechanism.claim_one() is None

    monkeypatch.setattr(
        monitoring_service,
        "registered_mechanisms",
        lambda: (memory_maintenance_mechanism,),
    )
    overview = await monitoring_service.get_overview()
    assert overview.mechanisms == []


@pytest.mark.asyncio
async def test_dream_memory_receipt_identity_keeps_embedding_state_correlated(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    unindexed, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Unindexed memory",
            payload=MemoryPayload(text="This memory has no embedding projection."),
        )
    )
    indexed, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Indexed memory",
            payload=MemoryPayload(text="This memory has an embedding projection."),
        )
    )
    db.add(
        MemoryEmbeddingChunk(
            item_id=indexed.id,
            source_fingerprint=indexed.semantic_fingerprint,
            model_key="test-embedding",
            model_code="test-embedding",
            dimensions=2,
            chunk_index=0,
            text=indexed.search_text,
            embedding=[1.0, 0.0],
        )
    )
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    policy_token = (
        memory_maintenance_mechanism._policy_token()  # pyright: ignore[reportPrivateUsage]
    )
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    db.add_all(
        [
            DreamReceipt(
                mechanism_key=memory_maintenance_mechanism.key,
                subject_kind="memory_item",
                subject_id=(
                    f"{unindexed.id}:{unindexed.revision}:"
                    f"{policy_token}:{day}:i0"
                ),
                status="success",
                attempts=1,
            ),
            DreamReceipt(
                mechanism_key=memory_maintenance_mechanism.key,
                subject_kind="memory_item",
                subject_id=(
                    f"{indexed.id}:{indexed.revision}:"
                    f"{policy_token}:{day}:i1"
                ),
                status="success",
                attempts=1,
            ),
        ]
    )
    await db.commit()

    assert await memory_maintenance_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_manual_duplicate_finding_compares_revisions_and_merges_sources(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    first, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Règle Atlas",
            payload=MemoryPayload(text="Toujours appliquer Atlas avant le déploiement."),
            source=MemorySourceCreate(source_kind="test", source_ref="test:first"),
        )
    )
    second, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Règle Atlas du déploiement",
            payload=MemoryPayload(text="Appliquer Atlas avant chaque déploiement."),
            source=MemorySourceCreate(source_kind="test", source_ref="test:second"),
        )
    )
    primary, related = sorted((first, second), key=lambda item: str(item.id))

    async def candidates(
        item: MemoryItem, *, minimum_similarity: float, limit: int = 10
    ) -> list[tuple[MemoryItem, float]]:
        del item, minimum_similarity, limit
        return [(related, 0.97)]

    monkeypatch.setattr(maintenance, "_indexed_candidates", candidates)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")

    created_ids = await maintenance.detect_for_item(primary.id)

    assert len(created_ids) == 1
    finding = await db.get(MemoryFinding, created_ids[0])
    assert finding is not None
    assert finding.kind == "duplicate"
    assert finding.primary_revision == primary.revision
    assert finding.related_revision == related.revision
    primary_id = primary.id
    related_id = related.id

    # A real HTTP request starts with a cold identity map. Keeping the objects
    # returned by create_item here used to hide an async lazy-load failure while
    # forgetting the duplicate's revisions.
    db.expunge_all()

    result = await maintenance.apply_finding(
        finding.id,
        canonical_item_id=primary_id,
    )

    assert result.status == "applied"
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == related_id)) is None
    source_refs = set(
        (
            await db.scalars(
                select(MemorySource.source_ref).where(MemorySource.item_id == primary_id)
            )
        ).all()
    )
    assert source_refs == {"test:first", "test:second"}


@pytest.mark.asyncio
async def test_automatic_duplicate_mode_applies_an_existing_pending_finding(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    first, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence de thé",
            payload=MemoryPayload(text="La personne préfère le thé vert le matin."),
            source=MemorySourceCreate(source_kind="test", source_ref="test:tea:first"),
        )
    )
    second, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence pour le thé",
            payload=MemoryPayload(text="Le matin, la personne préfère boire du thé vert."),
            source=MemorySourceCreate(source_kind="test", source_ref="test:tea:second"),
        )
    )
    primary, related = sorted((first, second), key=lambda item: str(item.id))

    async def candidates(
        item: MemoryItem, *, minimum_similarity: float, limit: int = 10
    ) -> list[tuple[MemoryItem, float]]:
        del item, minimum_similarity, limit
        return [(related, 0.99)]

    monkeypatch.setattr(maintenance, "_indexed_candidates", candidates)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")

    finding_ids = await maintenance.detect_for_item(primary.id)
    finding = await db.get(MemoryFinding, finding_ids[0])
    assert finding is not None
    assert finding.status == "pending"

    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "automatic")
    claim = await memory_maintenance_mechanism.claim_one()
    assert claim is not None
    assert claim.prepared_payload == {"item_id": str(primary.id)}
    processed_count = await memory_maintenance_mechanism.apply(
        claim, claim.prepared_payload
    )

    await db.refresh(finding)
    assert processed_count == 1
    assert finding.status == "applied"
    assert (
        await db.scalar(select(MemoryItem.id).where(MemoryItem.id == related.id))
        is None
    )


@pytest.mark.asyncio
async def test_automatic_aging_marks_without_removing_from_rag_and_edit_clears_it(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Ancienne règle PostgreSQL",
            payload=MemoryPayload(text="Cette règle doit rester disponible dans le RAG."),
        )
    )
    old = datetime.now(timezone.utc) - timedelta(days=500)
    await db.execute(
        update(MemoryItem)
        .where(MemoryItem.id == item.id)
        .values(created_at=old, updated_at=old)
    )
    await db.commit()
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "automatic")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_AFTER_DAYS", 365)

    await maintenance.detect_for_item(item.id)

    aged = await db.get(MemoryItem, item.id)
    assert aged is not None
    assert aged.old_at is not None
    assert aged.old_reason == "age:365d"
    page = await service.search_items(
        MemorySearchRequest(agent_id=owner.id, query="PostgreSQL")
    )
    assert [hit.item.id for hit in page.hits] == [item.id]

    updated = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=item.revision,
            title="Règle PostgreSQL confirmée récemment",
        ),
        actor_agent_id=owner.id,
    )
    assert updated.old_at is None
    assert updated.old_reason is None


@pytest.mark.asyncio
async def test_dismissed_finding_is_not_recreated_for_the_same_revision_pair(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    memories = []
    for title in ("Préférence café", "Préférence pour le café"):
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=title,
                payload=MemoryPayload(text="La personne préfère un café sans sucre."),
            )
        )
        memories.append(item)
    primary, related = sorted(memories, key=lambda item: str(item.id))

    async def candidates(
        item: MemoryItem, *, minimum_similarity: float, limit: int = 10
    ) -> list[tuple[MemoryItem, float]]:
        del item, minimum_similarity, limit
        return [(related, 0.99)]

    monkeypatch.setattr(maintenance, "_indexed_candidates", candidates)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    first_scan = await maintenance.detect_for_item(primary.id)
    await maintenance.dismiss_finding(first_scan[0])

    second_scan = await maintenance.detect_for_item(primary.id)

    assert second_scan == []
    findings = (
        await db.scalars(select(MemoryFinding).where(MemoryFinding.kind == "duplicate"))
    ).all()
    assert len(findings) == 1
    assert findings[0].status == "dismissed"


@pytest.mark.asyncio
async def test_threshold_change_obsoletes_and_can_reactivate_pending_finding(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    memories = []
    for title in ("Préférence thé", "Préférence pour le thé"):
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=title,
                payload=MemoryPayload(text="La personne préfère le thé vert."),
            )
        )
        memories.append(item)
    primary, related = sorted(memories, key=lambda item: str(item.id))

    async def candidates(
        item: MemoryItem, *, minimum_similarity: float, limit: int = 10
    ) -> list[tuple[MemoryItem, float]]:
        del item, minimum_similarity, limit
        return [(related, 0.93)]

    monkeypatch.setattr(maintenance, "_indexed_candidates", candidates)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 0.92)
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    finding_ids = await maintenance.detect_for_item(primary.id)
    finding = await db.get(MemoryFinding, finding_ids[0])
    assert finding is not None

    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 0.95)
    await maintenance.reconcile_policy_findings()

    assert finding.status == "obsolete"
    assert finding.threshold == 0.95
    assert finding.details["obsolete_reason"] == "policy_threshold"

    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 0.90)
    await maintenance.reconcile_policy_findings()

    assert finding.status == "pending"
    assert finding.threshold == 0.90
    assert finding.resolved_at is None
    assert "obsolete_reason" not in finding.details


@pytest.mark.asyncio
async def test_contradiction_requires_an_explainable_textual_signal(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    old_fact, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Préférence de transport",
            payload=MemoryPayload(text="La personne utilise toujours le train pour Lyon."),
        )
    )
    correction, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Correction de la préférence de transport",
            payload=MemoryPayload(
                text="Correction : la personne n'utilise plus le train pour Lyon."
            ),
        )
    )
    primary, related = sorted((old_fact, correction), key=lambda item: str(item.id))

    async def candidates(
        item: MemoryItem, *, minimum_similarity: float, limit: int = 10
    ) -> list[tuple[MemoryItem, float]]:
        del item, minimum_similarity, limit
        return [(related, 0.91)]

    monkeypatch.setattr(maintenance, "_indexed_candidates", candidates)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")

    finding_ids = await maintenance.detect_for_item(primary.id)
    findings = await maintenance.list_findings(agent_id=owner.id)

    assert finding_ids == [findings[0].id]
    assert findings[0].kind == "contradiction"
    assert str(findings[0].details["signal"]).startswith("explicit_marker:")
    assert findings[0].details["proposed_canonical_item_id"] == str(correction.id)
