"""Vector ranking of public Topic projections without thematic side effects."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

from loguru import logger
from sqlalchemy import Float, cast as sql_cast, exists, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db

from .contracts import TopicProjectionMatch, TopicProjectionRanking
from .embedding import (
    EmbeddingModel,
    MemoryEmbeddingError,
    MemoryEmbeddingNotConfiguredError,
    embed_query,
    resolve_embedding_model,
)
from .models import MemoryEmbeddingChunk, MemoryItem, MemoryItemGrant, MemoryLink


async def rank_topic_projection_embeddings(
    query_embedding: Sequence[float],
    *,
    model: EmbeddingModel,
    limit: int = 100,
    agent_id: int | None = None,
) -> TopicProjectionRanking:
    """Rank Topic anchors from an existing query vector.

    When an agent is supplied, ignore Topics that do not contain any memory the
    agent can read. This prevents a global public Topic catalogue from steering
    a private recall towards an inaccessible neighbourhood.
    """

    dimensions = len(query_embedding)
    if dimensions == 0:
        return TopicProjectionRanking(matches=(), model_key=model.key)
    bounded_limit = max(1, min(limit, 500))
    distance = cast(
        ColumnElement[float],
        sql_cast(
            MemoryEmbeddingChunk.embedding.op("<=>")(list(query_embedding)),
            Float,
        ),
    )
    query = (
        select(
            MemoryItem.id,
            distance.label("distance"),
        )
        .join(
            MemoryEmbeddingChunk,
            MemoryEmbeddingChunk.item_id == MemoryItem.id,
        )
        .where(
            MemoryItem.source_managed.is_(True),
            MemoryItem.managed_source_kind == "topic",
            MemoryItem.visibility == "public",
            MemoryItem.owner_agent_id.is_(None),
            MemoryItem.metadata_["memory_role"].as_string() == "topic",
            MemoryEmbeddingChunk.model_key == model.key,
            MemoryEmbeddingChunk.dimensions == dimensions,
            MemoryEmbeddingChunk.source_fingerprint
            == MemoryItem.semantic_fingerprint,
        )
    )
    if agent_id is not None:
        related_item = aliased(MemoryItem)
        direct_grant = exists(
            select(MemoryItemGrant.id).where(
                MemoryItemGrant.item_id == related_item.id,
                MemoryItemGrant.agent_id == agent_id,
            )
        )
        query = query.where(
            exists(
                select(MemoryLink.id)
                .join(
                    related_item,
                    related_item.id == MemoryLink.target_item_id,
                )
                .where(
                    MemoryLink.source_item_id == MemoryItem.id,
                    MemoryLink.relation_type == "topic_contains",
                    MemoryLink.suggested.is_(False),
                    or_(
                        related_item.owner_agent_id == agent_id,
                        related_item.visibility == "public",
                        direct_grant,
                    ),
                )
            )
        )
    rows = list(
        (
            await get_db().execute(
                query.order_by(distance, MemoryItem.id).limit(bounded_limit)
            )
        ).all()
    )
    matches: list[TopicProjectionMatch] = []
    seen: set[object] = set()
    for item_id, raw_distance in rows:
        if item_id in seen:
            continue
        numeric_distance = float(raw_distance)
        if not math.isfinite(numeric_distance):
            continue
        seen.add(item_id)
        matches.append(
            TopicProjectionMatch(
                memory_item_id=item_id,
                similarity=max(-1.0, min(1.0, 1.0 - numeric_distance)),
            )
        )
    return TopicProjectionRanking(
        matches=tuple(matches),
        model_key=model.key,
    )


async def rank_topic_projections(
    query: str, *, limit: int = 100
) -> TopicProjectionRanking:
    """Rank only public Topic anchors, preserving lexical fallback on failure."""

    normalized = query.strip()
    if not normalized:
        return TopicProjectionRanking(matches=())
    bounded_limit = max(1, min(limit, 500))
    try:
        model = await resolve_embedding_model()
        query_embedding = await embed_query(normalized, model=model)
        return await rank_topic_projection_embeddings(
            query_embedding,
            model=model,
            limit=bounded_limit,
        )
    except MemoryEmbeddingNotConfiguredError:
        return TopicProjectionRanking(
            matches=(),
            degraded=True,
            degradation_reason="embedding_not_configured",
        )
    except MemoryEmbeddingError:
        logger.warning("Topic vector preselection is unavailable")
        return TopicProjectionRanking(
            matches=(),
            degraded=True,
            degradation_reason="embedding_unavailable",
        )
    except Exception:
        logger.exception("Topic vector preselection failed")
        await get_db().rollback()
        return TopicProjectionRanking(
            matches=(),
            degraded=True,
            degradation_reason="semantic_search_failed",
        )


__all__ = ["rank_topic_projection_embeddings", "rank_topic_projections"]
