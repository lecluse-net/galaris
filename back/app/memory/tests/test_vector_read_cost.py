"""Exact vector reads keep owner isolation, ranking and complete projections."""

import math
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.memory import deduplication, retrieval
from app.memory.embedding import EmbeddingModel
from app.memory.models import MemoryEmbeddingChunk, MemoryEmbeddingManifest, MemoryItem
from app.memory.schemas import MemorySearchRequest
from app.memory.semantic_index import SEMANTIC_INDEX_VERSION
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_exact_vector_page_and_duplicate_count_on_many_passages(db, agents, monkeypatch):
    owner, peer = agents
    model = EmbeddingModel(key="synthetic-cost", code="synthetic-cost", model_name="synthetic-cost",
        base_url="http://unused.invalid", api_key=None)
    identities = [uuid4() for _ in range(81)]
    await db.execute(MemoryItem.__table__.insert(), [dict(id=identity,
        owner_agent_id=owner.id if index < 80 else peer.id, title=f"Synthetic vector {index}",
        resource_id=f"synthetic:{identity}", content_hash=str(index), semantic_fingerprint=str(index))
        for index, identity in enumerate(identities)])
    await db.execute(MemoryEmbeddingManifest.__table__.insert(), [dict(item_id=identity,
        source_fingerprint=str(index), model_key=model.key, dimensions=3,
        index_version=SEMANTIC_INDEX_VERSION, chunk_count=12, source_word_count=12, indexed_word_count=12)
        for index, identity in enumerate(identities)])
    await db.execute(MemoryEmbeddingChunk.__table__.insert(), [dict(item_id=identity,
        source_fingerprint=str(index), model_key=model.key, model_code=model.code, dimensions=3,
        chunk_index=chunk, text="Synthetic vector passage", embedding=[1.0, index / 100, 0.0])
        for index, identity in enumerate(identities) for chunk in range(12)])
    await db.execute(text("ANALYZE memory_items"))
    await db.execute(text("ANALYZE memory_embedding_chunks"))
    await db.execute(text("SET LOCAL jit = off"))
    async with measured_reads(db, "exact-vector-972-passages"):
        candidates = await retrieval._semantic_candidates(MemorySearchRequest(agent_id=owner.id),
            model=model, query_embedding=[1.0, 0.0, 0.0], limit=8)
    assert [item.id for item, *_ in candidates] == identities[:8]

    async def resolve():
        return model

    monkeypatch.setattr(deduplication, "resolve_embedding_model", resolve)
    threshold = 0.9999
    expected_pairs = sum(1 for first in range(80) for second in range(first + 1, 80)
        if (1 + first * second / 10000) / math.sqrt((1 + first ** 2 / 10000) * (1 + second ** 2 / 10000)) >= threshold)
    async with measured_reads(db, "exact-duplicate-960-passages"):
        preview = await deduplication.preview_duplicate_pairs(threshold=threshold, limit=5, agent_id=owner.id)
    assert preview.total_pairs == expected_pairs
    assert len(preview.pairs) == 5 and preview.has_more
    assert [(pair.similarity, pair.first_memory_id, pair.second_memory_id) for pair in preview.pairs] == sorted(
        [(pair.similarity, pair.first_memory_id, pair.second_memory_id) for pair in preview.pairs],
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    assert all(pair.first_memory_id in identities[:80] and pair.second_memory_id in identities[:80] for pair in preview.pairs)
