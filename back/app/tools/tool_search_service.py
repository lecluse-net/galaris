"""Hybrid, rights-first retrieval over effective MCP tool definitions."""

from __future__ import annotations

from app.llm import model_usages

import hashlib
import json
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, cast

from loguru import logger
from sqlalchemy import Float, cast as sql_cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.elements import ColumnElement

from app.llm import LLM, llm_provider_service, llm_service
from app.llm import embedding_service as llm_embedding
from app.llm.provider_facade import openai_protocol_base_url
from app.llm.resource_discovery import provider_connection
from core.database import get_db, get_db_session

from . import metrics
from .catalog import AgentToolCatalog, AgentToolCatalogEntry
from .models import ToolSearchDocument


ToolSearchMode = Literal["hybrid", "lexical", "catalog_only"]
RRF_RANK_CONSTANT = 60
MAX_CANDIDATES = 60
MAX_RESULTS = 12
INDEX_EMBEDDING_TIMEOUT_SECONDS = 30.0
QUERY_EMBEDDING_TIMEOUT_SECONDS = 5.0
EMBEDDING_BATCH_SIZE = 64
_SEARCH_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+")


@dataclass(frozen=True)
class ToolEmbeddingModel:
    key: str
    code: str
    model_name: str
    base_url: str
    api_key: str | None = field(repr=False)


@dataclass(frozen=True)
class ToolSearchHit:
    entry: AgentToolCatalogEntry
    score: float
    lexical_rank: int | None = None
    semantic_rank: int | None = None


@dataclass(frozen=True)
class ToolSearchResult:
    query: str
    catalog_version: str
    mode: ToolSearchMode
    hits: tuple[ToolSearchHit, ...]
    degraded: bool = False
    degradation_reason: str | None = None


@dataclass(frozen=True)
class ToolIndexRefreshResult:
    documents_indexed: int
    embeddings_refreshed: int
    documents_pruned: int
    semantic_available: bool
    degradation_reason: str | None = None


def _embedding_model_key(llm: LLM, *, base_url: str) -> str:
    payload = json.dumps(
        {
            "contract": 1,
            "provider_id": llm.llm_provider_id,
            "provider_type": llm.provider.provider_type,
            "base_url": base_url,
            "model_code": llm.code,
            "model_name": llm.llm_name,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _resolve_embedding_model() -> ToolEmbeddingModel | None:
    llm = await llm_service.get_profile_llm(model_usages.VECTOR)
    if llm is None or not llm.provider.is_active:
        return None
    base_url = openai_protocol_base_url(
        provider_connection(llm.provider, None)
    ).strip()
    if not base_url:
        return None
    return ToolEmbeddingModel(
        key=_embedding_model_key(llm, base_url=base_url),
        code=llm.code,
        model_name=llm.llm_name,
        base_url=base_url,
        api_key=llm_provider_service.decrypt_api_key(llm.provider.api_key),
    )


async def _embed_many(
    texts: list[str],
    *,
    model: ToolEmbeddingModel,
    timeout_seconds: float,
) -> list[list[float]]:
    return await llm_embedding.embed_many(
        texts,
        endpoint=llm_embedding.EmbeddingEndpoint(
            model_name=model.model_name,
            base_url=model.base_url,
            api_key=model.api_key,
        ),
        timeout_seconds=timeout_seconds,
    )


async def _sync_documents(
    catalog: AgentToolCatalog,
) -> dict[str, ToolSearchDocument]:
    """Upsert public metadata while keeping authorization outside the index."""

    if not catalog.entries:
        return {}
    now = datetime.now(timezone.utc)
    values = [
        {
            "definition_fingerprint": entry.definition_fingerprint,
            "runtime": entry.runtime,
            "name": entry.name,
            "description": entry.description,
            "parameters_json_schema": entry.parameters_json_schema,
            "search_text": entry.input_summary,
            "last_seen_at": now,
        }
        for entry in catalog.entries
    ]
    statement = pg_insert(ToolSearchDocument).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[ToolSearchDocument.definition_fingerprint],
        set_={
            "runtime": statement.excluded.runtime,
            "name": statement.excluded.name,
            "description": statement.excluded.description,
            "parameters_json_schema": statement.excluded.parameters_json_schema,
            "search_text": statement.excluded.search_text,
            "last_seen_at": now,
            "updated_at": now,
        },
    )
    await get_db().execute(statement)
    await get_db().flush()
    result = await get_db().scalars(
        select(ToolSearchDocument).where(
            ToolSearchDocument.definition_fingerprint.in_(
                [entry.definition_fingerprint for entry in catalog.entries]
            )
        )
    )
    return {document.definition_fingerprint: document for document in result.all()}


async def _ensure_embeddings(
    catalog: AgentToolCatalog,
    documents: dict[str, ToolSearchDocument],
    *,
    model: ToolEmbeddingModel,
    expected_dimensions: int,
    force: bool = False,
) -> tuple[int | None, int]:
    missing = [
        entry
        for entry in catalog.entries
        if (
            force
            or (document := documents.get(entry.definition_fingerprint)) is None
            or document.embedding is None
            or document.model_key != model.key
            or document.dimensions != expected_dimensions
        )
    ]
    if missing:
        for offset in range(0, len(missing), EMBEDDING_BATCH_SIZE):
            batch = missing[offset : offset + EMBEDDING_BATCH_SIZE]
            embeddings = await _embed_many(
                [entry.embedding_text for entry in batch],
                model=model,
                timeout_seconds=INDEX_EMBEDDING_TIMEOUT_SECONDS,
            )
            dimensions = len(embeddings[0])
            if dimensions != expected_dimensions:
                raise llm_embedding.EmbeddingError(
                    "The tool embedding dimension changed during index refresh."
                )
            for entry, embedding in zip(batch, embeddings, strict=True):
                document = documents.get(entry.definition_fingerprint)
                if document is None:
                    continue
                document.model_key = model.key
                document.model_code = model.code
                document.dimensions = dimensions
                document.embedding = embedding
        await get_db().flush()

    dimensions = {
        document.dimensions
        for document in documents.values()
        if document.model_key == model.key
        and document.embedding is not None
        and document.dimensions is not None
    }
    resolved_dimensions = next(iter(dimensions)) if len(dimensions) == 1 else None
    return resolved_dimensions, len(missing)


def _merge_catalogs(
    catalogs: Sequence[AgentToolCatalog],
) -> AgentToolCatalog:
    entries = {
        entry.definition_fingerprint: entry
        for catalog in catalogs
        for entry in catalog.entries
    }
    ordered = tuple(
        sorted(
            entries.values(),
            key=lambda entry: (
                entry.name,
                entry.runtime,
                entry.definition_fingerprint,
            ),
        )
    )
    payload = "\n".join(entry.definition_fingerprint for entry in ordered)
    return AgentToolCatalog(
        agent_id=0,
        runtime="mixed",
        entries=ordered,
        version=hashlib.sha256(payload.encode("ascii")).hexdigest(),
    )


async def refresh_catalog_index(
    catalogs: Sequence[AgentToolCatalog],
    *,
    force_embeddings: bool,
    prune_stale: bool,
) -> ToolIndexRefreshResult:
    """Rebuild the shared projection from complete rights-filtered snapshots."""

    projection = _merge_catalogs(catalogs)
    fingerprints = [
        entry.definition_fingerprint for entry in projection.entries
    ]
    documents: dict[str, ToolSearchDocument] = {}
    pruned = 0
    async with get_db().begin_nested():
        documents = await _sync_documents(projection)
        if prune_stale:
            statement = delete(ToolSearchDocument)
            if fingerprints:
                statement = statement.where(
                    ToolSearchDocument.definition_fingerprint.not_in(fingerprints)
                )
            deleted = await get_db().execute(
                statement.returning(ToolSearchDocument.id)
            )
            pruned = len(deleted.all())

    if not projection.entries:
        return ToolIndexRefreshResult(
            documents_indexed=0,
            embeddings_refreshed=0,
            documents_pruned=pruned,
            semantic_available=False,
            degradation_reason="empty_catalog",
        )

    try:
        async with get_db().begin_nested():
            model = await _resolve_embedding_model()
    except Exception:
        logger.exception("Tool index refresh embedding model resolution failed")
        model = None
    if model is None:
        return ToolIndexRefreshResult(
            documents_indexed=len(documents),
            embeddings_refreshed=0,
            documents_pruned=pruned,
            semantic_available=False,
            degradation_reason="embedding_not_configured",
        )

    try:
        cached_dimensions = {
            document.dimensions
            for document in documents.values()
            if document.model_key == model.key
            and document.embedding is not None
            and document.dimensions is not None
        }
        if not force_embeddings and len(cached_dimensions) == 1:
            expected_dimensions = next(iter(cached_dimensions))
        else:
            probe = await _embed_many(
                [projection.entries[0].embedding_text],
                model=model,
                timeout_seconds=QUERY_EMBEDDING_TIMEOUT_SECONDS,
            )
            expected_dimensions = len(probe[0])
        async with get_db().begin_nested():
            _dimensions, refreshed = await _ensure_embeddings(
                projection,
                documents,
                model=model,
                expected_dimensions=expected_dimensions,
                force=force_embeddings,
            )
    except llm_embedding.EmbeddingError:
        logger.warning("Tool index refresh fell back to lexical retrieval")
        return ToolIndexRefreshResult(
            documents_indexed=len(documents),
            embeddings_refreshed=0,
            documents_pruned=pruned,
            semantic_available=False,
            degradation_reason="embedding_unavailable",
        )
    except Exception:
        logger.exception("Tool index refresh semantic projection failed")
        return ToolIndexRefreshResult(
            documents_indexed=len(documents),
            embeddings_refreshed=0,
            documents_pruned=pruned,
            semantic_available=False,
            degradation_reason="semantic_projection_failed",
        )

    return ToolIndexRefreshResult(
        documents_indexed=len(documents),
        embeddings_refreshed=refreshed,
        documents_pruned=pruned,
        semantic_available=True,
    )


async def _lexical_fingerprints(
    catalog: AgentToolCatalog,
    *,
    query: str,
    limit: int,
) -> list[str]:
    fingerprints = [entry.definition_fingerprint for entry in catalog.entries]
    tokens = _SEARCH_TOKEN_RE.findall(query.lower())[:32]
    if not tokens:
        return []
    # Discovery should tolerate one unmatched word in a natural-language objective.
    # OR combines the bounded normalized lexemes; rank still rewards multiple matches.
    ts_query = func.to_tsquery("simple", " | ".join(tokens))
    rank = func.ts_rank_cd(ToolSearchDocument.search_vector, ts_query)
    result = await get_db().execute(
        select(ToolSearchDocument.definition_fingerprint)
        .where(
            ToolSearchDocument.definition_fingerprint.in_(fingerprints),
            or_(
                ToolSearchDocument.search_vector.op("@@")(ts_query),
                ToolSearchDocument.name.ilike(f"%{query}%"),
                ToolSearchDocument.description.ilike(f"%{query}%"),
                ToolSearchDocument.search_text.ilike(f"%{query}%"),
            ),
        )
        .order_by(rank.desc(), ToolSearchDocument.name)
        .limit(limit)
    )
    return [str(row[0]) for row in result.all()]


async def _semantic_fingerprints(
    catalog: AgentToolCatalog,
    *,
    model: ToolEmbeddingModel,
    dimensions: int,
    query_embedding: list[float],
    limit: int,
) -> list[str]:
    distance = cast(
        ColumnElement[float],
        sql_cast(
            ToolSearchDocument.embedding.op("<=>")(query_embedding),
            Float,
        ),
    )
    result = await get_db().execute(
        select(
            ToolSearchDocument.definition_fingerprint,
            distance.label("distance"),
        )
        .where(
            ToolSearchDocument.definition_fingerprint.in_(
                [entry.definition_fingerprint for entry in catalog.entries]
            ),
            ToolSearchDocument.model_key == model.key,
            ToolSearchDocument.dimensions == dimensions,
            ToolSearchDocument.embedding.is_not(None),
        )
        .order_by(distance, ToolSearchDocument.definition_fingerprint)
        .limit(limit)
    )
    rows: list[str] = []
    for row in result.all():
        raw_distance = float(row[1])
        if math.isfinite(raw_distance):
            rows.append(str(row[0]))
    return rows


def _python_lexical_fingerprints(
    catalog: AgentToolCatalog,
    query: str,
    *,
    limit: int,
) -> list[str]:
    terms = set(_SEARCH_TOKEN_RE.findall(query.lower()))
    scored: list[tuple[int, int, str, str]] = []
    normalized_query = query.strip().lower()
    for entry in catalog.entries:
        entry_terms = set(_SEARCH_TOKEN_RE.findall(entry.embedding_text.lower()))
        overlap = len(terms & entry_terms)
        exact = int(entry.name.lower() == normalized_query)
        if overlap or exact:
            scored.append(
                (
                    exact,
                    overlap,
                    entry.name,
                    entry.definition_fingerprint,
                )
            )
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [fingerprint for _exact, _overlap, _name, fingerprint in scored[:limit]]


def _fuse(
    catalog: AgentToolCatalog,
    *,
    lexical: Sequence[str],
    semantic: Sequence[str],
    limit: int,
) -> tuple[ToolSearchHit, ...]:
    lexical_ranks = {
        fingerprint: rank for rank, fingerprint in enumerate(lexical, start=1)
    }
    semantic_ranks = {
        fingerprint: rank for rank, fingerprint in enumerate(semantic, start=1)
    }
    entries = {
        entry.definition_fingerprint: entry for entry in catalog.entries
    }
    scores: dict[str, float] = {}
    for fingerprint, rank in lexical_ranks.items():
        scores[fingerprint] = scores.get(fingerprint, 0.0) + (
            1.0 / (RRF_RANK_CONSTANT + rank)
        )
    for fingerprint, rank in semantic_ranks.items():
        scores[fingerprint] = scores.get(fingerprint, 0.0) + (
            1.0 / (RRF_RANK_CONSTANT + rank)
        )
    ordered = sorted(
        scores,
        key=lambda fingerprint: (
            -scores[fingerprint],
            entries[fingerprint].name,
            fingerprint,
        ),
    )
    return tuple(
        ToolSearchHit(
            entry=entries[fingerprint],
            score=scores[fingerprint],
            lexical_rank=lexical_ranks.get(fingerprint),
            semantic_rank=semantic_ranks.get(fingerprint),
        )
        for fingerprint in ordered[:limit]
    )


def _catalog_only_fallback(
    catalog: AgentToolCatalog,
    *,
    query: str,
    limit: int,
    surface: str,
    started: float,
    reason: str,
) -> ToolSearchResult:
    lexical = _python_lexical_fingerprints(
        catalog,
        query,
        limit=min(MAX_CANDIDATES, max(24, limit * 3)),
    )
    hits = _fuse(
        catalog,
        lexical=lexical,
        semantic=(),
        limit=limit,
    )
    result = ToolSearchResult(
        query=query,
        catalog_version=catalog.version,
        mode="catalog_only",
        hits=hits,
        degraded=True,
        degradation_reason=reason,
    )
    metrics.observe_search(
        surface=surface,
        mode=result.mode,
        degraded=True,
        degradation_reason=result.degradation_reason,
        catalog_size=len(catalog.entries),
        result_count=len(hits),
        latency_seconds=time.monotonic() - started,
    )
    return result


async def search_catalog(
    catalog: AgentToolCatalog,
    *,
    query: str,
    limit: int = 8,
    surface: str = "planner",
) -> ToolSearchResult:
    """Search only the supplied effective catalog, with lexical fail-open."""

    started = time.monotonic()
    normalized_query = " ".join(query.split())[:4_000]
    bounded_limit = max(1, min(limit, MAX_RESULTS))
    if not normalized_query or not catalog.entries:
        result = ToolSearchResult(
            query=normalized_query,
            catalog_version=catalog.version,
            mode="catalog_only",
            hits=(),
        )
        metrics.observe_search(
            surface=surface,
            mode=result.mode,
            degraded=False,
            degradation_reason=None,
            catalog_size=len(catalog.entries),
            result_count=0,
            latency_seconds=time.monotonic() - started,
        )
        return result

    candidate_limit = min(
        MAX_CANDIDATES,
        max(24, bounded_limit * 3),
    )
    documents: dict[str, ToolSearchDocument] = {}
    try:
        async with get_db().begin_nested():
            documents = await _sync_documents(catalog)
            lexical = await _lexical_fingerprints(
                catalog,
                query=normalized_query,
                limit=candidate_limit,
            )
    except Exception:
        logger.exception("Tool discovery database projection failed")
        return _catalog_only_fallback(
            catalog,
            query=normalized_query,
            limit=bounded_limit,
            surface=surface,
            started=started,
            reason="search_projection_unavailable",
        )

    try:
        async with get_db().begin_nested():
            model = await _resolve_embedding_model()
    except Exception:
        logger.exception("Tool discovery embedding model resolution failed")
        model = None
    if model is None:
        hits = _fuse(
            catalog,
            lexical=lexical,
            semantic=(),
            limit=bounded_limit,
        )
        result = ToolSearchResult(
            query=normalized_query,
            catalog_version=catalog.version,
            mode="lexical",
            hits=hits,
            degraded=True,
            degradation_reason="embedding_not_configured",
        )
        metrics.observe_search(
            surface=surface,
            mode=result.mode,
            degraded=True,
            degradation_reason=result.degradation_reason,
            catalog_size=len(catalog.entries),
            result_count=len(hits),
            latency_seconds=time.monotonic() - started,
        )
        return result

    try:
        embeddings = await _embed_many(
            [normalized_query],
            model=model,
            timeout_seconds=QUERY_EMBEDDING_TIMEOUT_SECONDS,
        )
        query_embedding = embeddings[0]
        async with get_db().begin_nested():
            dimensions, _refreshed = await _ensure_embeddings(
                catalog,
                documents,
                model=model,
                expected_dimensions=len(query_embedding),
            )
            if dimensions is not None and dimensions == len(query_embedding):
                semantic = await _semantic_fingerprints(
                    catalog,
                    model=model,
                    dimensions=dimensions,
                    query_embedding=query_embedding,
                    limit=candidate_limit,
                )
            else:
                semantic = []
    except llm_embedding.EmbeddingError:
        logger.warning("Tool discovery fell back to lexical retrieval")
        semantic = []
    except Exception:
        logger.exception("Tool discovery semantic search failed")
        semantic = []

    mode: ToolSearchMode = "hybrid" if semantic else "lexical"
    degraded = not semantic
    degradation_reason = None if semantic else "semantic_search_unavailable"
    hits = _fuse(
        catalog,
        lexical=lexical,
        semantic=semantic,
        limit=bounded_limit,
    )
    result = ToolSearchResult(
        query=normalized_query,
        catalog_version=catalog.version,
        mode=mode,
        hits=hits,
        degraded=degraded,
        degradation_reason=degradation_reason,
    )
    metrics.observe_search(
        surface=surface,
        mode=result.mode,
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        catalog_size=len(catalog.entries),
        result_count=len(hits),
        latency_seconds=time.monotonic() - started,
    )
    return result


async def search_catalog_in_isolated_session(
    catalog: AgentToolCatalog,
    *,
    query: str,
    limit: int = 8,
    surface: str = "planner",
) -> ToolSearchResult:
    """Search without sharing the caller's contextual SQLAlchemy session.

    Pydantic AI may execute capability and MCP calls concurrently. A dedicated
    transaction prevents an optional discovery failure from invalidating the durable
    Task transaction used by checkpoints. The fallback is intentionally database-free.
    """

    started = time.monotonic()
    normalized_query = " ".join(query.split())[:4_000]
    bounded_limit = max(1, min(limit, MAX_RESULTS))
    if not normalized_query or not catalog.entries:
        return await search_catalog(
            catalog,
            query=normalized_query,
            limit=bounded_limit,
            surface=surface,
        )
    try:
        async with get_db_session():
            return await search_catalog(
                catalog,
                query=normalized_query,
                limit=bounded_limit,
                surface=surface,
            )
    except Exception:
        logger.exception("Isolated tool discovery transaction failed")
        return _catalog_only_fallback(
            catalog,
            query=normalized_query,
            limit=bounded_limit,
            surface=surface,
            started=started,
            reason="search_transaction_unavailable",
        )


__all__ = [
    "ToolSearchHit",
    "ToolIndexRefreshResult",
    "ToolSearchMode",
    "ToolSearchResult",
    "refresh_catalog_index",
    "search_catalog",
    "search_catalog_in_isolated_session",
]
