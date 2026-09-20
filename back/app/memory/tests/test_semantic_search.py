from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent
from app.memory import (
    deduplication,
    file_facade,
    retrieval,
    semantic_index,
    service,
    topic_ranking,
)
from app.memory.embedding import (
    EmbeddingModel,
    MemoryEmbeddingError,
    MemoryEmbeddingNotConfiguredError,
)
from app.memory.models import (
    MemoryAutomationJob,
    MemoryEmbeddingChunk,
    MemoryItem,
    MemoryLink,
)
from app.memory.schemas import (
    MemoryGrantUpdate,
    MemoryItemCreate,
    MemoryLinkCreate,
    MemoryPayload,
    MemoryRecallRequest,
)
from core.authorize import Privileges
from core.params import runtime_settings
from app.topic import TopicClassification, service as topic_service
from app.memory.tests.embedding_fixtures import published_chunk


def test_recall_parameters_use_global_memory_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 8)
    monkeypatch.setattr(
        retrieval.runtime_settings,
        "MEMORY_RECALL_CANDIDATE_LIMIT",
        48,
    )
    monkeypatch.setattr(
        retrieval.runtime_settings,
        "MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS",
        240,
    )
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_SEMANTIC_WEIGHT", 1.0)
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_LEXICAL_WEIGHT", 0.0)
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_TOPIC_WEIGHT", 0.0)
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_GRAPH_WEIGHT", 0.0)
    monkeypatch.setattr(
        retrieval.runtime_settings,
        "MEMORY_RECALL_SUGGESTED_LINK_WEIGHT",
        0.25,
    )
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_AUTHORITY_WEIGHT", 0.0)
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_FRESHNESS_WEIGHT", 0.0)
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_CENTRALITY_WEIGHT", 0.0)

    defaults = retrieval._resolve_parameters(  # pyright: ignore[reportPrivateUsage]
        MemoryRecallRequest(agent_id=7, query="release")
    )
    limited = retrieval._resolve_parameters(  # pyright: ignore[reportPrivateUsage]
        MemoryRecallRequest(
            agent_id=7,
            query="release",
            semantic_query="release with complete validation constraints",
            limit=3,
        )
    )

    assert defaults.limit == 8
    assert defaults.candidate_limit == 48
    assert defaults.semantic_query_max_chars == 240
    assert limited.limit == 3
    assert limited.candidate_limit == 48
    assert limited.semantic_query_max_chars == 240
    assert limited.semantic_weight == pytest.approx(1.0)
    assert limited.lexical_weight == pytest.approx(0.0)
    assert limited.topic_weight == pytest.approx(0.0)
    assert limited.suggested_link_weight == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_topic_ranking_embedding_outage_does_not_expire_outer_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = EmbeddingModel(
        key="unreachable-model",
        code="unreachable-model",
        model_name="unreachable-model",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )

    async def fake_model() -> EmbeddingModel:
        return model

    async def unavailable_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del query, model, timeout_seconds
        raise MemoryEmbeddingError("provider unavailable")

    rollback = AsyncMock()
    monkeypatch.setattr(topic_ranking, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(topic_ranking, "embed_query", unavailable_query)
    monkeypatch.setattr(
        topic_ranking,
        "get_db",
        lambda: type("Session", (), {"rollback": rollback})(),
    )

    ranking = await topic_ranking.rank_topic_projections("topic query")

    assert ranking.degraded is True
    assert ranking.degradation_reason == "embedding_unavailable"
    rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_deduplication_embedding_outage_does_not_expire_outer_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = EmbeddingModel(
        key="unreachable-model",
        code="unreachable-model",
        model_name="unreachable-model",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )

    async def fake_model() -> EmbeddingModel:
        return model

    async def unavailable_embeddings(
        texts: list[str],
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[list[float]]:
        del texts, model, timeout_seconds
        raise MemoryEmbeddingError("provider unavailable")

    rollback = AsyncMock()
    monkeypatch.setattr(deduplication, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(deduplication, "embed_many", unavailable_embeddings)
    monkeypatch.setattr(
        deduplication,
        "get_db",
        lambda: type("Session", (), {"rollback": rollback})(),
    )

    candidates = await deduplication.find_similar_memory_candidates(
        agent_id=7,
        texts=["A durable fact"],
    )

    assert candidates == [[]]
    rollback.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("full_search", False),
        ("candidate_limit", 16),
        ("semantic_query_max_chars", 240),
        ("semantic_weight", 1.0),
        ("lexical_weight", 0.0),
        ("topic_weight", 0.0),
        ("graph_weight", 0.0),
        ("suggested_link_weight", 0.25),
        ("authority_weight", 0.0),
        ("freshness_weight", 0.0),
        ("centrality_weight", 0.0),
        ("diversity_lambda", 0.0),
    ),
)
def test_recall_request_rejects_removed_local_strategy_overrides(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=field):
        MemoryRecallRequest.model_validate(
            {
                "agent_id": 7,
                "query": "Atlas deployment",
                field: value,
            }
        )


def test_memory_item_create_rejects_removed_deduplication_choice() -> None:
    with pytest.raises(ValidationError, match="deduplicate"):
        MemoryItemCreate.model_validate(
            {
                "owner_agent_id": 7,
                "title": "Preference",
                "payload": {"text": "Always answer in French."},
                "deduplicate": False,
            }
        )


@pytest.mark.asyncio
async def test_memory_file_search_cannot_downgrade_canonical_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def canonical_recall(query: str, **kwargs: object) -> SimpleNamespace:
        calls.append({"query": query, **kwargs})
        return SimpleNamespace(hits=[], has_more=False)

    async def forbidden_browse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("A non-empty memory search must use canonical recall.")

    monkeypatch.setattr(file_facade.facade, "search_memory_detailed", canonical_recall)
    monkeypatch.setattr(file_facade.service, "search_items", forbidden_browse)

    result = await file_facade.search_file_resources(
        agent_id=7,
        task_id=None,
        expected_kind="memory",
        query="deployment decisions",
        mode="text",
        limit=None,
        offset=0,
    )

    assert result["hits"] == []
    assert calls[0]["query"] == "deployment decisions"


@pytest.mark.asyncio
async def test_default_recall_reports_lexical_fallback_when_model_is_missing(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="PostgreSQL convention",
            payload=MemoryPayload(text="Use declarative schemas."),
        )
    )

    async def missing_model() -> EmbeddingModel:
        raise MemoryEmbeddingNotConfiguredError("not configured")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="PostgreSQL",
        )
    )

    assert [hit.item.id for hit in result.hits] == [item.id]
    assert result.mode == "lexical"
    assert result.degraded is True
    assert result.degradation_reason == "embedding_not_configured"


@pytest.mark.asyncio
async def test_lexical_fallback_ranks_partial_query_matches(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    best, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="PostgreSQL deployment checklist",
            payload=MemoryPayload(text="Validate PostgreSQL before deployment."),
        )
    )
    partial, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Deployment notification",
            payload=MemoryPayload(text="Notify operators after deployment."),
        )
    )

    async def missing_model() -> EmbeddingModel:
        raise MemoryEmbeddingNotConfiguredError("not configured")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="PostgreSQL deployment safety",
        )
    )

    assert result.mode == "lexical"
    assert result.degraded is True
    # Partial evidence remains available, after the stronger match.
    assert [hit.item.id for hit in result.hits] == [best.id, partial.id]


@pytest.mark.asyncio
async def test_lexical_fallback_returns_available_conversational_match(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Old conversational acknowledgement",
            payload=MemoryPayload(text="Oui, la réponse précédente était correcte."),
        )
    )

    async def missing_model() -> EmbeddingModel:
        raise MemoryEmbeddingNotConfiguredError("not configured")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="Oui, ça va ?",
        )
    )

    assert result.mode == "lexical"
    assert [hit.item.id for hit in result.hits] == [item.id]


@pytest.mark.asyncio
async def test_explicit_topic_does_not_override_precise_lexical_evidence(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Release engineering")
    )
    assert topic.memory_item_id is not None
    thematic, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Deployment note",
            payload=MemoryPayload(text="A deployment detail from this release Topic."),
        )
    )
    global_match, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release deployment exact match",
            payload=MemoryPayload(text="Release deployment release deployment."),
        )
    )
    await service.ensure_topic_memory_link(
        topic_item_id=topic.memory_item_id,
        memory_item_id=thematic.id,
    )

    async def missing_model() -> EmbeddingModel:
        raise MemoryEmbeddingNotConfiguredError("not configured")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release deployment",
            topic_item_id=topic.memory_item_id,
        )
    )

    assert result.mode == "lexical"
    assert [hit.item.id for hit in result.hits[:2]] == [
        global_match.id,
        thematic.id,
    ]
    assert "thematic_lexical" in result.hits[1].retrieval_sources


@pytest.mark.asyncio
async def test_lexical_fallback_does_not_admit_graph_only_neighbors(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    anchor, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Jacques est à la plage",
            payload=MemoryPayload(text="Jacques a donné sa localisation actuelle."),
        )
    )
    strong_neighbor, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Contexte associé",
            payload=MemoryPayload(text="Il a emporté le parasol bleu."),
        )
    )
    weak_neighbor, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Contexte incertain",
            payload=MemoryPayload(text="Un détail sans relation suffisamment fiable."),
        )
    )
    await service.create_link(
        MemoryLinkCreate(
            source_item_id=anchor.id,
            target_item_id=strong_neighbor.id,
            relation_type="related_to",
            confidence=0.95,
        ),
        actor_agent_id=owner.id,
    )
    await service.create_link(
        MemoryLinkCreate(
            source_item_id=anchor.id,
            target_item_id=weak_neighbor.id,
            relation_type="related_to",
            confidence=0.50,
        ),
        actor_agent_id=owner.id,
    )

    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="Jacques plage",
        )
    )

    hits = {hit.item.id: hit for hit in result.hits}
    assert anchor.id in hits
    assert strong_neighbor.id not in hits
    assert weak_neighbor.id not in hits
    assert result.ranking_version == "memory-query-evidence/v10"


@pytest.mark.asyncio
async def test_recall_infers_topic_and_fuses_thematic_with_global_ranks(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="topic-recall-model",
        code="topic-recall-vector",
        model_name="topic-recall-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Release engineering")
    )
    assert topic.memory_item_id is not None
    topic_item = await db.get(MemoryItem, topic.memory_item_id)
    assert topic_item is not None
    thematic, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release checklist",
            payload=MemoryPayload(text="Validate the release schema before deployment."),
        )
    )
    transverse, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release notification",
            payload=MemoryPayload(text="Notify operators after deployment."),
        )
    )
    await service.ensure_topic_memory_link(
        topic_item_id=topic.memory_item_id,
        memory_item_id=thematic.id,
    )
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=embedding,
            )
            for item, embedding in (
                (topic_item, [1.0, 0.0, 0.0]),
                (thematic, [1.0, 0.0, 0.0]),
                (transverse, [0.9, 0.1, 0.0]),
            )
        ]
    )
    await db.commit()

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del timeout_seconds
        assert query == "release deployment"
        assert model.key == "topic-recall-model"
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release deployment",
        )
    )

    assert result.mode == "hybrid"
    assert result.ranking_version == "memory-query-evidence/v10"
    assert [hit.item.id for hit in result.hits[:2]] == [
        thematic.id,
        transverse.id,
    ]
    assert topic.memory_item_id not in {hit.item.id for hit in result.hits}
    assert {
        "thematic_lexical",
        "thematic_vector",
        "global_lexical",
        "global_vector",
    }.issubset(set(result.hits[0].retrieval_sources))
    assert result.hits[0].semantic_similarity == pytest.approx(1.0)
    assert result.hits[1].semantic_similarity is not None
    assert result.hits[1].semantic_similarity > 0.9
    assert result.thematic_candidate_count == 1
    assert result.global_candidate_count == 2
    assert result.thematic_result_count == 1
    assert result.global_result_count == 2

    async def weak_topic_ranking(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            matches=[
                SimpleNamespace(
                    memory_item_id=topic.memory_item_id,
                    similarity=0.40,
                )
            ]
        )

    monkeypatch.setattr(
        retrieval,
        "rank_topic_projection_embeddings",
        weak_topic_ranking,
    )
    weak_topic_result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release deployment",
        )
    )

    assert weak_topic_result.thematic_candidate_count == 0
    assert weak_topic_result.thematic_result_count == 0
    assert not any(
        source.startswith("thematic_")
        for hit in weak_topic_result.hits
        for source in hit.retrieval_sources
    )


@pytest.mark.asyncio
async def test_recall_embeds_broad_objective_and_keeps_one_near_duplicate(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="broad-recall-model",
        code="broad-recall-vector",
        model_name="broad-recall-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    duplicates: list[MemoryItem] = []
    for _index in range(3):
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title="Release deployment checklist",
                payload=MemoryPayload(
                    text="Validate the schema and notify operators before release."
                ),
            ),
            deduplicate=False,
        )
        duplicates.append(item)
    distinct, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Rollback recovery plan",
            payload=MemoryPayload(
                text="Restore the previous backup if production validation fails."
            ),
        )
    )
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=embedding,
            )
            for item, embedding in (
                *((item, [1.0, 0.0, 0.0]) for item in duplicates),
                (distinct, [0.8, 0.6, 0.0]),
            )
        ]
    )
    await db.commit()
    broad_objective = (
        "Deploy the new governed-memory ranking while preserving ACL isolation, "
        "checking the generated database schema, notifying operators, and keeping "
        "a tested rollback path if production validation fails."
    )

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del timeout_seconds
        assert query == broad_objective
        assert model.key == "broad-recall-model"
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)

    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release deployment",
            semantic_query=broad_objective,
            limit=4,
        )
    )

    returned_ids = {hit.item.id for hit in result.hits}
    assert result.mode == "hybrid"
    assert len(returned_ids & {item.id for item in duplicates}) == 1
    assert distinct.id in returned_ids


@pytest.mark.asyncio
async def test_hybrid_recall_ranks_weak_candidates_after_stronger_evidence(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="evidence-recall-model",
        code="evidence-recall-vector",
        model_name="evidence-recall-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    lexical, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Quasar pagination convention",
            payload=MemoryPayload(text="Use fifty rows per page."),
        )
    )
    semantic, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Frontend list defaults",
            payload=MemoryPayload(text="A directly relevant interface preference."),
        )
    )
    weak, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Family holiday",
            payload=MemoryPayload(text="An unrelated personal recollection."),
        )
    )
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=embedding,
            )
            for item, embedding in (
                (lexical, [0.0, 1.0, 0.0]),
                (semantic, [1.0, 0.0, 0.0]),
                (weak, [0.2, 0.9797959, 0.0]),
            )
        ]
    )
    await db.commit()

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_query(
        _query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del timeout_seconds
        assert model.key == "evidence-recall-model"
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)
    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="Quasar pagination",
            limit=8,
        )
    )

    assert [hit.item.id for hit in result.hits] == [lexical.id, semantic.id, weak.id]


@pytest.mark.asyncio
async def test_hybrid_recall_applies_node_kind_and_source_managed_filters(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="filtered-recall-model",
        code="filtered-recall-vector",
        model_name="filtered-recall-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    allowed, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release validation",
            payload=MemoryPayload(text="Validate the release before deployment."),
        )
    )
    wrong_kind, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release validation document",
            payload=MemoryPayload(text="A source document about release validation."),
            memory_type="working",
            node_kind="document",
        )
    )
    managed, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Managed release validation",
            payload=MemoryPayload(text="A managed projection about release validation."),
        )
    )
    managed.source_managed = True
    managed.managed_source_kind = "test_projection"
    managed.managed_source_ref = f"test:{managed.id}"
    managed.read_only = True
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=[1.0, 0.0, 0.0],
            )
            for item in (allowed, wrong_kind, managed)
        ]
    )
    await db.commit()

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del query, model, timeout_seconds
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)

    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release validation",
            node_kinds=["memory"],
            exclude_source_managed=True,
        )
    )

    assert [hit.item.id for hit in result.hits] == [allowed.id]


@pytest.mark.asyncio
async def test_link_centrality_can_drive_ranking(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    items: list[MemoryItem] = []
    for label in ("Hub", "Procedure", "Decision", "Incident"):
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                title=f"Release knowledge {label}",
                payload=MemoryPayload(text=f"Distinct operational note {label}."),
            )
        )
        items.append(item)
    hub, *neighbors = items
    for neighbor in neighbors:
        await service.create_link(
            MemoryLinkCreate(
                source_item_id=hub.id,
                target_item_id=neighbor.id,
                relation_type="related_to",
                confidence=1.0,
            ),
            actor_agent_id=owner.id,
        )

    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_SEMANTIC_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_LEXICAL_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_GRAPH_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_AUTHORITY_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_FRESHNESS_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_CENTRALITY_WEIGHT", 1.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_DIVERSITY_LAMBDA", 0.0)

    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release knowledge",
            limit=4,
        )
    )

    assert result.hits[0].item.id == hub.id


@pytest.mark.asyncio
async def test_suggested_topic_membership_weakly_reranks_existing_candidates(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Release engineering")
    )
    assert topic.memory_item_id is not None
    proposed, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release knowledge proposed",
            payload=MemoryPayload(text="Distinct release operations proposal."),
        )
    )
    ordinary, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release knowledge ordinary",
            payload=MemoryPayload(text="Distinct release operations reference."),
        )
    )
    unrelated, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Garden watering",
            payload=MemoryPayload(text="Keep the vegetable seedlings hydrated."),
        )
    )
    db.add_all(
        [
            MemoryLink(
                source_item_id=topic.memory_item_id,
                target_item_id=proposed.id,
                relation_type="topic_membership_candidate",
                confidence=0.8,
                suggested=True,
                projection_key="memory.topic_maintenance",
                projection_version=1,
                metadata_={"generated_by": "topic_maintenance"},
            ),
            MemoryLink(
                source_item_id=topic.memory_item_id,
                target_item_id=ordinary.id,
                relation_type="topic_membership_anomaly",
                confidence=1.0,
                suggested=True,
                projection_key="memory.topic_maintenance",
                projection_version=1,
                metadata_={"generated_by": "topic_maintenance"},
            ),
            MemoryLink(
                source_item_id=topic.memory_item_id,
                target_item_id=unrelated.id,
                relation_type="topic_membership_candidate",
                confidence=1.0,
                suggested=True,
                projection_key="memory.topic_maintenance",
                projection_version=1,
                metadata_={"generated_by": "topic_maintenance"},
            ),
        ]
    )
    await db.commit()

    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_SEMANTIC_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_LEXICAL_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_TOPIC_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_GRAPH_WEIGHT", 1.0)
    monkeypatch.setattr(
        runtime_settings,
        "MEMORY_RECALL_SUGGESTED_LINK_WEIGHT",
        0.25,
    )
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_AUTHORITY_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_FRESHNESS_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_CENTRALITY_WEIGHT", 0.0)
    monkeypatch.setattr(runtime_settings, "MEMORY_RECALL_DIVERSITY_LAMBDA", 0.0)

    result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="release knowledge operations",
            limit=2,
        )
    )

    hits = {hit.item.id: hit for hit in result.hits}
    assert set(hits) == {proposed.id, ordinary.id}
    assert result.hits[0].item.id == proposed.id
    # The suggestion remains a bounded tie-break, not the relevance score.
    assert 0 < hits[proposed.id].score - hits[ordinary.id].score <= 0.03
    assert hits[proposed.id].retrieval_sources == [
        "global_lexical",
        "suggested_topic_link",
    ]
    assert "suggested_topic_link" not in hits[ordinary.id].retrieval_sources
    assert unrelated.id not in hits


@pytest.mark.asyncio
async def test_topic_vector_ranking_uses_only_current_public_topic_projections(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, _peer = agents
    model = EmbeddingModel(
        key="topic-ranking-model",
        code="topic-ranking-vector",
        model_name="topic-ranking-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    first = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Vegetable gardening")
    )
    second = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Release engineering")
    )
    assert first.memory_item_id is not None
    assert second.memory_item_id is not None
    first_item = await db.get(MemoryItem, first.memory_item_id)
    second_item = await db.get(MemoryItem, second.memory_item_id)
    assert first_item is not None and second_item is not None
    private, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Private release note",
            payload=MemoryPayload(text="This private item is not a Topic anchor."),
        )
    )
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=embedding,
            )
            for item, embedding in (
                (first_item, [0.0, 1.0, 0.0]),
                (second_item, [1.0, 0.0, 0.0]),
                (private, [1.0, 0.0, 0.0]),
            )
        ]
    )
    await db.commit()

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del timeout_seconds
        assert query == "safe software release"
        assert model.key == "topic-ranking-model"
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(topic_ranking, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(topic_ranking, "embed_query", fake_query)
    ranking = await topic_ranking.rank_topic_projections("safe software release")

    assert ranking.degraded is False
    assert [match.memory_item_id for match in ranking.matches] == [
        second.memory_item_id,
        first.memory_item_id,
    ]
    assert private.id not in {match.memory_item_id for match in ranking.matches}


@pytest.mark.asyncio
async def test_recall_topic_inference_excludes_inaccessible_neighbourhoods(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    model = EmbeddingModel(
        key="scoped-topic-ranking-model",
        code="scoped-topic-ranking-vector",
        model_name="scoped-topic-ranking-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )
    accessible_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Accessible operations")
    )
    inaccessible_topic = await topic_service.create_from_classification(
        TopicClassification(action="create", title="Private peer operations")
    )
    assert accessible_topic.memory_item_id is not None
    assert inaccessible_topic.memory_item_id is not None
    accessible_memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Owner operations",
            payload=MemoryPayload(text="An operation visible to the owner."),
        )
    )
    inaccessible_memory, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Peer operations",
            payload=MemoryPayload(text="An operation private to the peer."),
        )
    )
    await service.ensure_topic_memory_link(
        topic_item_id=accessible_topic.memory_item_id,
        memory_item_id=accessible_memory.id,
    )
    await service.ensure_topic_memory_link(
        topic_item_id=inaccessible_topic.memory_item_id,
        memory_item_id=inaccessible_memory.id,
    )
    topic_items = [
        await db.get(MemoryItem, accessible_topic.memory_item_id),
        await db.get(MemoryItem, inaccessible_topic.memory_item_id),
    ]
    assert all(item is not None for item in topic_items)
    resolved_topic_items = [cast(MemoryItem, item) for item in topic_items]
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=[1.0, 0.0, 0.0],
            )
            for item in resolved_topic_items
        ]
    )
    await db.commit()

    ranking = await topic_ranking.rank_topic_projection_embeddings(
        [1.0, 0.0, 0.0],
        model=model,
        agent_id=owner.id,
    )

    assert [match.memory_item_id for match in ranking.matches] == [
        accessible_topic.memory_item_id
    ]


@pytest.mark.asyncio
async def test_index_job_hybrid_recall_acl_and_forget(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, peer = agents
    model = EmbeddingModel(
        key="model-key",
        code="test-vector",
        model_name="test-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_embed_many(
        texts: list[str],
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 60.0,
    ) -> list[list[float]]:
        del timeout_seconds
        assert model.key == "model-key"
        return [[1.0, 0.0, 0.0] for _text in texts]

    monkeypatch.setattr(semantic_index, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(semantic_index, "embed_many", fake_embed_many)
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Release safety",
            payload=MemoryPayload(
                text="Verify the generated schema before releasing."
            ),
        )
    )
    await semantic_index.process_embedding_job({"item_id": str(item.id)})

    chunks = list(
        (
            await db.scalars(
                select(MemoryEmbeddingChunk).where(
                    MemoryEmbeddingChunk.item_id == item.id
                )
            )
        ).all()
    )
    assert len(chunks) == 1
    assert chunks[0].dimensions == 3
    assert chunks[0].source_fingerprint == item.semantic_fingerprint
    index_job = await db.scalar(
        select(MemoryAutomationJob).where(
            MemoryAutomationJob.kind == "semantic_index"
        )
    )
    assert index_job is not None
    index_job.status = "success"
    await db.commit()
    current = await semantic_index.reconcile_embedding_index(missing_only=True)
    assert (current.current, current.queued) == (1, 0)
    forced = await semantic_index.reconcile_embedding_index(missing_only=False)
    assert (forced.current, forced.queued) == (1, 1)
    assert await db.scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.kind == "semantic_index", MemoryAutomationJob.status == "pending",
    )) is not None

    async def fake_query(
        query: str,
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 5.0,
    ) -> list[float]:
        del timeout_seconds
        assert query == "How do we make releases safer?"
        assert model.key == "model-key"
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(retrieval, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(retrieval, "embed_query", fake_query)
    owner_result = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=owner.id,
            query="How do we make releases safer?",
        )
    )
    assert owner_result.mode == "hybrid"
    assert owner_result.degraded is False
    assert [hit.item.id for hit in owner_result.hits] == [item.id]
    assert "generated schema" in owner_result.hits[0].excerpt

    peer_private = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=peer.id,
            query="How do we make releases safer?",
        )
    )
    assert peer_private.hits == []
    assert peer_private.mode == "lexical"
    assert peer_private.degradation_reason == "embedding_index_empty"

    await service.set_item_grant(
        item.id,
        peer.id,
        MemoryGrantUpdate(can_write=False),
    )
    peer_shared = await retrieval.recall_items(
        MemoryRecallRequest(
            agent_id=peer.id,
            query="How do we make releases safer?",
        )
    )
    assert peer_shared.mode == "hybrid"
    assert [hit.item.id for hit in peer_shared.hits] == [item.id]

    await service.forget_item(item.id, actor_agent_id=owner.id)
    # A durable job claimed before the forget must never recreate the projection.
    await semantic_index.process_embedding_job({"item_id": str(item.id)})
    assert await db.scalar(
        select(MemoryEmbeddingChunk.id).where(
            MemoryEmbeddingChunk.item_id == item.id
        )
    ) is None


@pytest.mark.asyncio
async def test_semantic_duplicate_candidates_and_preview_are_owner_local(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del memory_storage
    owner, peer = agents
    model = EmbeddingModel(
        key="duplicate-model",
        code="duplicate-vector",
        model_name="duplicate-vector",
        base_url="http://embedding.invalid/v1",
        api_key=None,
    )

    async def fake_model() -> EmbeddingModel:
        return model

    async def fake_embed_many(
        texts: list[str],
        *,
        model: EmbeddingModel,
        timeout_seconds: float = 60.0,
    ) -> list[list[float]]:
        del timeout_seconds
        assert model.key == "duplicate-model"
        return [[1.0, 0.0, 0.0] for _text in texts]

    first, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Monthly reports",
            payload=MemoryPayload(text="Send reports every month."),
        )
    )
    second, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Monthly reporting",
            payload=MemoryPayload(text="The reporting cadence is monthly."),
        )
    )
    peer_item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Peer monthly reports",
            payload=MemoryPayload(text="The peer also uses monthly reports."),
        )
    )
    db.add_all(
        [
            published_chunk(
                item_id=item.id,
                source_fingerprint=item.semantic_fingerprint,
                model_key=model.key,
                model_code=model.code,
                dimensions=3,
                chunk_index=0,
                text=item.search_text,
                embedding=[1.0, 0.0, 0.0],
            )
            for item in (first, second, peer_item)
        ]
    )
    await db.commit()
    monkeypatch.setattr(deduplication, "resolve_embedding_model", fake_model)
    monkeypatch.setattr(deduplication, "embed_many", fake_embed_many)

    candidates = await deduplication.find_similar_memory_candidates(
        agent_id=owner.id,
        texts=["A report is expected every month."],
    )

    assert len(candidates) == 1
    assert {candidate.memory_id for candidate in candidates[0]} == {
        first.id,
        second.id,
    }
    preview = await deduplication.preview_duplicate_pairs(
        threshold=0.92,
        limit=100,
        agent_id=owner.id,
    )
    assert preview.degraded is False
    assert preview.total_pairs == 1
    assert len(preview.pairs) == 1
    assert {
        preview.pairs[0].first_memory_id,
        preview.pairs[0].second_memory_id,
    } == {first.id, second.id}


def test_duplicate_preview_route_requires_memory_access() -> None:
    from app.memory.router import estimate_memory_duplicates

    assert estimate_memory_duplicates._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]


@pytest.mark.asyncio
async def test_duplicate_preview_uses_the_global_merge_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import router
    from app.memory.schemas import MemoryDuplicatePreview
    from app.agent import AgentManagementScope

    monkeypatch.setattr(
        runtime_settings,
        "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD",
        0.99,
    )
    captured: dict[str, object] = {}

    async def preview(**kwargs: object) -> MemoryDuplicatePreview:
        captured.update(kwargs)
        return MemoryDuplicatePreview(
            threshold=cast(float, kwargs["threshold"]),
            total_pairs=0,
        )

    monkeypatch.setattr(router.deduplication, "preview_duplicate_pairs", preview)
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, None)),
    )

    result = await router.estimate_memory_duplicates(limit=100, agent_id=None)

    assert result.threshold == pytest.approx(0.99)
    assert captured["threshold"] == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_duplicate_preview_rejects_unauthenticated_request(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/memory/duplicates/preview")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rebuild_bounded_pages_resume_after_interrupted_commit(db, agents, monkeypatch):
    from sqlalchemy import func
    owner, _ = agents
    prefix = __import__("uuid").uuid4().hex
    db.add_all([MemoryItem(owner_agent_id=owner.id, resource_id=f"{prefix}/{i}",
        title=f"Memory {i}", content_hash=f"{i:064x}") for i in range(601)])
    await db.commit()
    model = EmbeddingModel(key=prefix, code="test", model_name="test", base_url="http://embedding.invalid", api_key=None)
    monkeypatch.setattr(semantic_index, "resolve_embedding_model", AsyncMock(return_value=model))
    original_commit = db.commit
    commits = 0
    async def interrupted_commit():
        nonlocal commits
        await original_commit()
        commits += 1
        if commits == 1:
            raise RuntimeError("simulated process loss after durable page")
    monkeypatch.setattr(db, "commit", interrupted_commit)
    with pytest.raises(RuntimeError, match="process loss"):
        await semantic_index.reconcile_embedding_index()
    statement = select(func.count(MemoryAutomationJob.id)).where(MemoryAutomationJob.payload["model_key"].astext == prefix)
    assert await db.scalar(statement) == 250
    monkeypatch.setattr(db, "commit", original_commit)
    result = await semantic_index.reconcile_embedding_index()
    assert result.scanned >= 601
    assert await db.scalar(statement) == result.scanned
    again = await semantic_index.reconcile_embedding_index()
    assert await db.scalar(statement) == again.scanned
