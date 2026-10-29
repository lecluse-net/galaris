"""Ranked Dataset discovery with live ACLs and an explicit lexical fallback."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
import hashlib
import json
import math
from typing import Any, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import Float, cast as sql_cast, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.file_share import ResourceContext, ResourceDescriptor, ResourceSearchHit, ResourceSearchResult, ResourceUri, parse_resource_uri
from app.llm import EmbeddingError, require_configured_embedding_model
from core.database import get_db

from .access import accessible_clause
from .contracts import DatasetNotFoundError
from .models import Dataset, DatasetSearchChunk, DatasetSearchIndex
from .passages import DatasetPassage, lexical_passages
from .search_index import current_index
from .search_predicates import search_vector, text_search_clause


MAX_CANDIDATES = 100
RANKING_VERSION = "dataset-hybrid/1"


def _signature(uri: ResourceUri, query: str, mode: str) -> str:
    return hashlib.sha256(json.dumps([str(uri), query, mode], ensure_ascii=False).encode()).hexdigest()[:20]


def _offset(cursor: str | None, signature: str) -> int:
    if cursor is None:
        return 0
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if value["signature"] != signature or type(value["offset"]) is not int or not 0 <= value["offset"] <= 10_000:
            raise ValueError()
        return value["offset"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ValueError("Invalid Dataset search cursor; restart this query") from None


def _cursor(offset: int, signature: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"offset": offset, "signature": signature}).encode()).decode()


async def search_datasets(
    ctx: ResourceContext, uri: ResourceUri, query: str, *, mode: str,
    limit: int, cursor: str | None,
    describe: Callable[[ResourceContext, ResourceUri], Awaitable[ResourceDescriptor]],
) -> ResourceSearchResult:
    actor = ctx.management_scope or ctx.agent_id
    signature = _signature(uri, query, mode)
    offset = _offset(cursor, signature)
    filters = [accessible_clause(actor)]
    if uri.locator:
        from .service import record
        identity = UUID(uri.segments[0])
        await record(identity, actor)
        filters.append(Dataset.id == identity)
    ts_query = func.websearch_to_tsquery("simple", query)
    rank = func.ts_rank_cd(search_vector(), ts_query)
    matches = text_search_clause(query)
    lexical = (await get_db().execute(select(Dataset.id, Dataset.revision, Dataset.lock_version).where(*filters, matches)
        .order_by(rank.desc(), Dataset.id).limit(MAX_CANDIDATES if mode == "semantic" else offset + limit + 1))).all()
    snapshots = {row.id: (row.revision, row.lock_version) for row in lexical}
    rows = {row.id: row for row in lexical}
    scores = {row.id: 1 / (60 + position) for position, row in enumerate(lexical, 1)}
    passages: dict[UUID, list[DatasetPassage]] = {}
    sources = {row.id: ["dataset_lexical"] for row in lexical}
    coverage: dict[str, Any] | None = None
    degradation: str | None = None
    hybrid = False
    semantic_window_full = False
    if mode == "semantic":
        try:
            model = await require_configured_embedding_model()
            totals = (await get_db().execute(select(func.count(Dataset.id),
                func.count(Dataset.id).filter(Dataset.id.in_(select(DatasetSearchIndex.dataset_id).where(current_index(model.key)))))
                .where(*filters))).one()
            coverage = {"eligible_items": int(totals[0]), "indexed_items": int(totals[1]), "model_code": model.code}
            if totals[1]:
                vectors = await model.embed([query], timeout=5.0)
                embedding = vectors[0] if len(vectors) == 1 else []
                if not embedding or not all(math.isfinite(v) for v in embedding) or not any(embedding):
                    raise ValueError("Invalid Dataset query embedding")
                distance = cast(ColumnElement[float], sql_cast(DatasetSearchChunk.embedding.op("<=>")(embedding), Float))
                candidates = (select(Dataset.id.label("identity"), Dataset.revision, Dataset.lock_version,
                    DatasetSearchChunk.json_pointer, DatasetSearchChunk.text, distance.label("distance"),
                    func.row_number().over(partition_by=Dataset.id, order_by=(distance, DatasetSearchChunk.chunk_index)).label("position"))
                    .join(DatasetSearchIndex, DatasetSearchIndex.dataset_id == Dataset.id)
                    .join(DatasetSearchChunk, DatasetSearchChunk.index_id == DatasetSearchIndex.id)
                    .where(*filters, current_index(model.key), DatasetSearchIndex.dimensions == len(embedding)).subquery())
                semantic = (await get_db().execute(select(candidates).where(candidates.c.position == 1)
                    .order_by(candidates.c.distance, candidates.c.identity).limit(MAX_CANDIDATES))).mappings().all()
                semantic_window_full = len(semantic) == MAX_CANDIDATES
                hybrid = True
                if not semantic:
                    degradation = "dataset_no_current_vector_candidates"
                for position, hit in enumerate(semantic, 1):
                    identity = cast(UUID, hit["identity"])
                    version = (int(hit["revision"]), int(hit["lock_version"]))
                    if identity in snapshots and snapshots[identity] != version:
                        scores.pop(identity, None)
                        sources.pop(identity, None)
                    scores[identity] = scores.get(identity, 0.0) + 1 / (60 + position)
                    snapshots[identity] = version
                    passages[identity] = [DatasetPassage(str(hit["json_pointer"]), str(hit["text"]))]
                    sources.setdefault(identity, []).append("dataset_vector")
            if totals[1] < totals[0]:
                degradation = "dataset_index_incomplete"
        except (EmbeddingError, ValueError, TimeoutError):
            logger.warning("Dataset semantic discovery fell back to lexical search")
            degradation = "dataset_embedding_unavailable"
    # Recheck live rights and source versions after the provider await. Never
    # carry vector evidence onto an edited resource or a revoked grant.
    if scores:
        current = (await get_db().execute(select(Dataset.id, Dataset.revision, Dataset.lock_version)
            .where(*filters, Dataset.id.in_(scores)))).all()
        rows = {row.id: row for row in current if (row.revision, row.lock_version) == snapshots[row.id]}
        if len(rows) < len(scores):
            degradation = "results_changed_during_search"
    ranked = sorted(rows, key=lambda identity: (-scores[identity], str(identity)))
    selected = ranked[offset:offset + limit]
    hits: list[ResourceSearchHit] = []
    for identity in selected:
        version = snapshots[identity]
        row = await get_db().scalar(select(Dataset).where(*filters, Dataset.id == identity,
            Dataset.revision == version[0], Dataset.lock_version == version[1])
            .execution_options(populate_existing=True))
        if row is None:
            degradation = "results_changed_during_search"
            continue
        evidence = lexical_passages(row.content, query)
        if identity in passages:
            from .passages import terms
            evidence = sorted([*evidence, *passages[identity]],
                key=lambda p: -len(terms(p.text) & terms(query)))[:3]
        try:
            descriptor = await describe(ctx, parse_resource_uri(f"data://{identity}"))
        except DatasetNotFoundError:
            degradation = "results_changed_during_search"
            continue
        hits.append(ResourceSearchHit(resource=descriptor,
            score=scores[identity], excerpt=evidence[0].text if evidence else "",
            retrieval_sources=sources[identity],
            passages=[{"json_pointer": p.json_pointer, "excerpt": p.text, "source_revision": row.revision} for p in evidence]))
    # Description hydration may await after earlier hits were checked. Admit the
    # complete page together immediately before returning any of its evidence.
    omitted = len(hits) < len(selected)
    if hits:
        admitted = (await get_db().execute(select(Dataset.id, Dataset.revision, Dataset.lock_version)
            .where(*filters, Dataset.id.in_(selected)))).all()
        valid = {row.id for row in admitted if (row.revision, row.lock_version) == snapshots[row.id]}
        previous_count = len(hits)
        hits = [hit for hit in hits if UUID(hit.resource.uri.removeprefix("data://")) in valid]
        omitted = omitted or previous_count > len(hits)
    if omitted:
        degradation = "results_changed_during_search"
    more = offset + len(selected) < len(ranked)
    return ResourceSearchResult(uri=str(uri), query=query, mode=cast(Any, mode), hits=hits,
        truncated=more or omitted, next_cursor=_cursor(offset + len(selected), signature) if more else None,
        retrieval_mode="hybrid" if hybrid else "lexical", degraded=degradation is not None,
        degradation_reason=degradation, ranking_version=RANKING_VERSION,
        candidate_window_exhausted=mode == "semantic" and (semantic_window_full or len(lexical) == MAX_CANDIDATES),
        index_coverage=coverage, evidence_status="unassessed" if hits else "no_evidence")
