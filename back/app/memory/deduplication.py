"""Semantic novelty checks and read-only duplicate previews."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from loguru import logger
from sqlalchemy import Float, and_, cast as sql_cast, exists, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.params import runtime_settings

from .embedding import (
    EmbeddingModel,
    MemoryEmbeddingError,
    MemoryEmbeddingNotConfiguredError,
    embed_many,
    resolve_embedding_model,
)
from .models import (
    MemoryContactItem,
    MemoryEmbeddingChunk,
    MemoryItem,
    MemoryItemGrant,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)
from .schemas import (
    MemoryDuplicatePreview,
    MemoryDuplicatePreviewPair,
    MemorySimilarityCandidate,
    MemoryType,
)


MAX_SIMILARITY_CANDIDATES = 4


def _valid_item_filters() -> tuple[ColumnElement[bool], ...]:
    now = datetime.now(timezone.utc)
    return (
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
    )


async def _candidates_for_embedding(
    *,
    agent_id: int,
    embedding: list[float],
    model: EmbeddingModel,
    memory_types: Sequence[MemoryType],
    limit: int,
    minimum_similarity: float,
    memory_role: str | None,
    topic_item_id: UUID | None,
    contact_item_id: UUID | None,
    strict_contact_scope: bool,
) -> list[MemorySimilarityCandidate]:
    dimensions = len(embedding)
    distance = cast(
        ColumnElement[float],
        sql_cast(
            MemoryEmbeddingChunk.embedding.op("<=>")(embedding),
            Float,
        ),
    )
    filters: list[ColumnElement[bool]] = [
        *_valid_item_filters(),
        or_(
            MemoryItem.owner_agent_id == agent_id,
            MemoryItem.visibility == "public",
            exists(
                select(MemoryItemGrant.id).where(
                    MemoryItemGrant.item_id == MemoryItem.id,
                    MemoryItemGrant.agent_id == agent_id,
                )
            ),
        ),
        MemoryEmbeddingChunk.model_key == model.key,
        MemoryEmbeddingChunk.dimensions == dimensions,
        MemoryEmbeddingChunk.source_fingerprint
        == MemoryItem.semantic_fingerprint,
    ]
    if memory_types:
        filters.append(MemoryItem.memory_type.in_(memory_types))
    if topic_item_id is not None and contact_item_id is not None:
        filters.append(
            exists(
                select(MemoryTopicContactItem.id)
                .join(
                    MemoryTopicContactScope,
                    MemoryTopicContactScope.id
                    == MemoryTopicContactItem.scope_id,
                )
                .where(
                    MemoryTopicContactItem.item_id == MemoryItem.id,
                    MemoryTopicContactScope.owner_agent_id == agent_id,
                    MemoryTopicContactScope.topic_item_id == topic_item_id,
                    MemoryTopicContactScope.contact_item_id == contact_item_id,
                )
            )
        )
    elif contact_item_id is not None:
        direct_scope = exists(
            select(MemoryContactItem.id).where(
                MemoryContactItem.item_id == MemoryItem.id,
                MemoryContactItem.owner_agent_id == agent_id,
                MemoryContactItem.contact_item_id == contact_item_id,
            )
        )
        legacy_scope = exists(
            select(MemoryTopicContactItem.id)
            .join(
                MemoryTopicContactScope,
                MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
            )
            .where(
                MemoryTopicContactItem.item_id == MemoryItem.id,
                MemoryTopicContactScope.owner_agent_id == agent_id,
                MemoryTopicContactScope.contact_item_id == contact_item_id,
            )
        )
        if strict_contact_scope:
            any_direct_scope = exists(
                select(MemoryContactItem.id).where(
                    MemoryContactItem.item_id == MemoryItem.id
                )
            )
            any_legacy_scope = exists(
                select(MemoryTopicContactItem.id).where(
                    MemoryTopicContactItem.item_id == MemoryItem.id
                )
            )
            filters.append(
                or_(
                    direct_scope,
                    legacy_scope,
                    and_(~any_direct_scope, ~any_legacy_scope),
                )
            )
        else:
            filters.append(or_(direct_scope, legacy_scope))
    elif strict_contact_scope:
        filters.extend(
            (
                ~exists(
                    select(MemoryContactItem.id).where(
                        MemoryContactItem.item_id == MemoryItem.id
                    )
                ),
                ~exists(
                    select(MemoryTopicContactItem.id).where(
                        MemoryTopicContactItem.item_id == MemoryItem.id
                    )
                ),
            )
        )
    if memory_role == "experience":
        filters.append(
            MemoryItem.metadata_["memory_role"].as_string() == "experience"
        )
    elif memory_role == "ordinary":
        filters.append(
            or_(
                MemoryItem.metadata_["memory_role"].as_string().is_(None),
                MemoryItem.metadata_["memory_role"].as_string() != "experience",
            )
        )
    per_item = (
        select(
            MemoryEmbeddingChunk.item_id.label("item_id"),
            MemoryEmbeddingChunk.text.label("chunk_text"),
            distance.label("distance"),
            func.row_number()
            .over(
                partition_by=MemoryEmbeddingChunk.item_id,
                order_by=distance,
            )
            .label("item_row"),
        )
        .join(MemoryItem, MemoryItem.id == MemoryEmbeddingChunk.item_id)
        .where(*filters)
        .subquery()
    )
    rows = list(
        (
            await get_db().execute(
                select(
                    MemoryItem,
                    per_item.c.chunk_text,
                    per_item.c.distance,
                )
                .join(per_item, per_item.c.item_id == MemoryItem.id)
                .where(
                    per_item.c.item_row == 1,
                    per_item.c.distance <= 1.0 - minimum_similarity,
                )
                .order_by(per_item.c.distance, MemoryItem.id)
                .limit(limit)
            )
        ).all()
    )
    candidates: list[MemorySimilarityCandidate] = []
    for item, raw_text, raw_distance in rows:
        distance_value = float(raw_distance)
        if not math.isfinite(distance_value):
            continue
        candidates.append(
            MemorySimilarityCandidate(
                memory_id=item.id,
                revision=item.revision,
                title=item.title,
                memory_type=cast(MemoryType, item.memory_type),
                excerpt=" ".join(str(raw_text).split())[:800],
                similarity=max(-1.0, min(1.0, 1.0 - distance_value)),
            )
        )
    return candidates


async def find_similar_memory_candidates(
    *,
    agent_id: int,
    texts: Sequence[str],
    memory_types: Sequence[MemoryType] = (),
    limit: int = MAX_SIMILARITY_CANDIDATES,
    minimum_similarity: float | None = None,
    memory_role: str | None = None,
    topic_item_id: UUID | None = None,
    contact_item_id: UUID | None = None,
    strict_contact_scope: bool = False,
) -> list[list[MemorySimilarityCandidate]]:
    """Search every accessible indexed node for each proposed fact, failing open."""

    if not texts:
        return []
    if topic_item_id is not None and contact_item_id is None:
        raise ValueError(
            "A topic_item_id requires contact_item_id."
        )
    resolved_minimum_similarity = (
        runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
        if minimum_similarity is None
        else minimum_similarity
    )
    try:
        model = await resolve_embedding_model()
        embeddings = await embed_many(
            [text.strip() for text in texts],
            model=model,
            timeout_seconds=5.0,
        )
        if len(embeddings) != len(texts):
            raise MemoryEmbeddingError(
                "Embedding provider returned an unexpected vector count."
            )
        return [
            await _candidates_for_embedding(
                agent_id=agent_id,
                embedding=embedding,
                model=model,
                memory_types=memory_types,
                limit=limit,
                minimum_similarity=resolved_minimum_similarity,
                memory_role=memory_role,
                topic_item_id=topic_item_id,
                contact_item_id=contact_item_id,
                strict_contact_scope=strict_contact_scope,
            )
            for embedding in embeddings
        ]
    except MemoryEmbeddingNotConfiguredError:
        return [[] for _text in texts]
    except MemoryEmbeddingError:
        logger.warning("Dream semantic novelty check is unavailable")
        return [[] for _text in texts]
    except Exception:
        logger.exception("Dream semantic novelty check failed")
        await get_db().rollback()
        return [[] for _text in texts]


async def preview_duplicate_pairs(
    *,
    threshold: float,
    limit: int,
    agent_id: int | None = None,
) -> MemoryDuplicatePreview:
    """List current ordinary-memory pairs above a cosine threshold."""

    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return MemoryDuplicatePreview(
            threshold=threshold,
            total_pairs=0,
            degraded=True,
            degradation_reason="embedding_not_configured",
        )
    except Exception:
        logger.exception("Memory duplicate preview model resolution failed")
        await get_db().rollback()
        return MemoryDuplicatePreview(
            threshold=threshold,
            total_pairs=0,
            degraded=True,
            degradation_reason="embedding_unavailable",
        )

    first_chunk = aliased(MemoryEmbeddingChunk)
    second_chunk = aliased(MemoryEmbeddingChunk)
    first_item = aliased(MemoryItem)
    second_item = aliased(MemoryItem)
    distance = cast(
        ColumnElement[float],
        sql_cast(
            first_chunk.embedding.op("<=>")(second_chunk.embedding),
            Float,
        ),
    )
    now = datetime.now(timezone.utc)
    filters: list[ColumnElement[bool]] = [
        first_item.node_kind == "memory",
        second_item.node_kind == "memory",
        first_item.source_managed.is_(False),
        second_item.source_managed.is_(False),
        or_(
            first_item.valid_from.is_(None),
            first_item.valid_from <= now,
        ),
        or_(
            second_item.valid_from.is_(None),
            second_item.valid_from <= now,
        ),
        or_(
            first_item.valid_until.is_(None),
            first_item.valid_until > now,
        ),
        or_(
            second_item.valid_until.is_(None),
            second_item.valid_until > now,
        ),
        first_item.owner_agent_id == second_item.owner_agent_id,
        first_chunk.item_id < second_chunk.item_id,
        first_chunk.model_key == model.key,
        second_chunk.model_key == model.key,
        first_chunk.model_key == second_chunk.model_key,
        first_chunk.dimensions == second_chunk.dimensions,
        first_chunk.source_fingerprint == first_item.semantic_fingerprint,
        second_chunk.source_fingerprint == second_item.semantic_fingerprint,
    ]
    if agent_id is not None:
        filters.append(first_item.owner_agent_id == agent_id)
    chunk_pairs = (
        select(
            first_item.owner_agent_id.label("owner_agent_id"),
            first_chunk.item_id.label("first_memory_id"),
            second_chunk.item_id.label("second_memory_id"),
            (1.0 - distance).label("similarity"),
        )
        .join(first_item, first_item.id == first_chunk.item_id)
        .join(
            second_chunk,
            and_(
                first_chunk.item_id < second_chunk.item_id,
                first_chunk.model_key == second_chunk.model_key,
                first_chunk.dimensions == second_chunk.dimensions,
            ),
        )
        .join(second_item, second_item.id == second_chunk.item_id)
        .where(*filters)
        .subquery()
    )
    item_pairs = (
        select(
            chunk_pairs.c.owner_agent_id,
            chunk_pairs.c.first_memory_id,
            chunk_pairs.c.second_memory_id,
            func.max(chunk_pairs.c.similarity).label("similarity"),
        )
        .group_by(
            chunk_pairs.c.owner_agent_id,
            chunk_pairs.c.first_memory_id,
            chunk_pairs.c.second_memory_id,
        )
        .subquery()
    )
    matching = (
        select(item_pairs)
        .where(item_pairs.c.similarity >= threshold)
        .subquery()
    )
    total_pairs = int(
        await get_db().scalar(select(func.count()).select_from(matching)) or 0
    )
    pair_rows = list(
        (
            await get_db().execute(
                select(matching)
                .order_by(
                    matching.c.similarity.desc(),
                    matching.c.first_memory_id,
                    matching.c.second_memory_id,
                )
                .limit(limit)
            )
        ).all()
    )
    item_ids = {
        memory_id
        for row in pair_rows
        for memory_id in (row.first_memory_id, row.second_memory_id)
    }
    items = {
        item.id: item
        for item in (
            await get_db().scalars(
                select(MemoryItem).where(MemoryItem.id.in_(item_ids))
            )
        ).all()
    }
    pairs: list[MemoryDuplicatePreviewPair] = []
    for row in pair_rows:
        first = items.get(row.first_memory_id)
        second = items.get(row.second_memory_id)
        similarity = float(row.similarity)
        if (
            first is None
            or second is None
            or not math.isfinite(similarity)
        ):
            continue
        pairs.append(
            MemoryDuplicatePreviewPair(
                owner_agent_id=int(row.owner_agent_id),
                first_memory_id=first.id,
                first_title=first.title,
                second_memory_id=second.id,
                second_title=second.title,
                similarity=max(-1.0, min(1.0, similarity)),
            )
        )
    return MemoryDuplicatePreview(
        threshold=threshold,
        total_pairs=total_pairs,
        pairs=pairs,
        has_more=total_pairs > len(pairs),
    )


__all__ = [
    "MAX_SIMILARITY_CANDIDATES",
    "find_similar_memory_candidates",
    "preview_duplicate_pairs",
]
