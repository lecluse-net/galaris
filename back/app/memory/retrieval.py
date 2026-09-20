"""Topic-aware governed-memory recall with hybrid and lexical fail-open paths."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence, TypeAlias, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import Float, cast as sql_cast, exists, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.params import runtime_settings

from . import metrics, service
from .access import effective_access, readable_item_clause
from .admission import admit_search_hits
from .embedding import (
    EmbeddingModel,
    MemoryEmbeddingError,
    MemoryEmbeddingNotConfiguredError,
    embed_query,
    resolve_embedding_model,
)
from .models import (
    MemoryContactItem,
    MemoryEmbeddingChunk,
    MemoryItem,
    MemoryLink,
    MemorySource,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)
from .schemas import (
    MemoryRecallRequest,
    MemoryItemPublic,
    MemoryIndexCoverage,
    MemoryRecallResult,
    MemoryRetrievalSource,
    MemorySearchHit,
    MemorySearchPassage,
    MemorySearchPage,
    MemorySearchRequest,
    MemoryTraversalStep,
)
from .topic_ranking import rank_topic_projection_embeddings
from .semantic_index import complete_projection_clause
from .passages import lexical_excerpt, query_identity
from . import relevance


RRF_RANK_CONSTANT = 60
MAX_HYBRID_CANDIDATES = 500
MIN_GRAPH_LINK_CONFIDENCE = 0.75
SUGGESTED_TOPIC_RELATION = "topic_membership_candidate"
RRF_RANKING_VERSION = "memory-query-evidence/v10"
MIN_INFERRED_TOPIC_SIMILARITY = 0.55
_SOURCE_WEIGHTS: dict[MemoryRetrievalSource, float] = {
    "thematic_lexical": 1.25,
    "thematic_vector": 1.25,
    "global_lexical": 1.0,
    "global_vector": 1.0,
    "graph_link": 1.1,
    "structural_link": 1.1,
    "suggested_topic_link": 1.0,
}
RankedItem: TypeAlias = UUID | tuple[UUID, float]
SemanticCandidate: TypeAlias = tuple[MemoryItemPublic, str, float, list[float], list[MemorySearchPassage]]


@dataclass
class _RecallDiagnostics:
    coverage: MemoryIndexCoverage | None = None
    model: EmbeddingModel | None = None


_LEXICAL_TERM_RE = re.compile(r"[^\W_]{3,}", flags=re.UNICODE)
_LEXICAL_STOPWORDS = frozenset(
    {
        "and",
        "alors",
        "are",
        "aussi",
        "avoir",
        "bonjour",
        "cela",
        "comme",
        "comment",
        "avec",
        "dans",
        "des",
        "donc",
        "elle",
        "elles",
        "encore",
        "est",
        "faire",
        "fait",
        "faites",
        "for",
        "from",
        "ils",
        "juste",
        "les",
        "leur",
        "mais",
        "maintenant",
        "merci",
        "non",
        "notre",
        "oui",
        "peut",
        "peux",
        "pouvez",
        "pour",
        "pourquoi",
        "quoi",
        "que",
        "qui",
        "sans",
        "ses",
        "son",
        "sont",
        "sur",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "tout",
        "très",
        "une",
        "vais",
        "votre",
        "with",
        "without",
        "your",
    }
)
_MAX_LEXICAL_TERMS = 12


@dataclass(frozen=True, slots=True)
class _RecallParameters:
    limit: int
    candidate_limit: int
    semantic_query: str
    semantic_query_max_chars: int
    semantic_weight: float
    lexical_weight: float
    topic_weight: float
    graph_weight: float
    suggested_link_weight: float
    authority_weight: float
    freshness_weight: float
    centrality_weight: float
    diversity_lambda: float


def _resolve_parameters(request: MemoryRecallRequest) -> _RecallParameters:
    """Resolve the canonical ranking exclusively from live application Params."""

    limit = int(request.limit or runtime_settings.MEMORY_CONTEXT_MAX_ITEMS)
    limit = max(1, min(limit, 500))
    candidate_limit = int(runtime_settings.MEMORY_RECALL_CANDIDATE_LIMIT)
    candidate_limit = max(limit, min(candidate_limit, MAX_HYBRID_CANDIDATES))
    semantic_query_max_chars = int(
        runtime_settings.MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS
    )
    semantic_query = " ".join((request.semantic_query or request.query).split())[
        :semantic_query_max_chars
    ].strip()
    raw_weights = [
        float(runtime_settings.MEMORY_RECALL_SEMANTIC_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_LEXICAL_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_TOPIC_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_GRAPH_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_AUTHORITY_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_FRESHNESS_WEIGHT),
        float(runtime_settings.MEMORY_RECALL_CENTRALITY_WEIGHT),
    ]
    total_weight = sum(raw_weights)
    if total_weight <= 0:
        raise ValueError("At least one memory-recall weight must be positive.")
    weights = [value / total_weight for value in raw_weights]
    return _RecallParameters(
        limit=limit,
        candidate_limit=candidate_limit,
        semantic_query=semantic_query,
        semantic_query_max_chars=semantic_query_max_chars,
        semantic_weight=weights[0],
        lexical_weight=weights[1],
        topic_weight=weights[2],
        graph_weight=weights[3],
        suggested_link_weight=float(
            runtime_settings.MEMORY_RECALL_SUGGESTED_LINK_WEIGHT
        ),
        authority_weight=weights[4],
        freshness_weight=weights[5],
        centrality_weight=weights[6],
        diversity_lambda=float(runtime_settings.MEMORY_RECALL_DIVERSITY_LAMBDA),
    )


def _normalized(values: dict[UUID, float]) -> dict[UUID, float]:
    finite = {key: value for key, value in values.items() if math.isfinite(value)}
    if not finite:
        return {}
    low = min(finite.values())
    high = max(finite.values())
    if high <= low:
        return {key: 1.0 for key in finite}
    return {key: (value - low) / (high - low) for key, value in finite.items()}


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _text_similarity(left: str, right: str) -> float:
    left_terms = {
        match.group(0).casefold() for match in _LEXICAL_TERM_RE.finditer(left)
    }
    right_terms = {
        match.group(0).casefold() for match in _LEXICAL_TERM_RE.finditer(right)
    }
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _meaningful_lexical_terms(
    value: str, *, limit: int | None = _MAX_LEXICAL_TERMS,
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _LEXICAL_TERM_RE.finditer(value):
        folded = match.group(0).casefold()
        if folded in _LEXICAL_STOPWORDS or folded in seen:
            continue
        seen.add(folded)
        terms.append(folded)
        if limit is not None and len(terms) >= limit:
            break
    return tuple(terms)


def _relaxed_lexical_query(query: str) -> str:
    """Build a multilingual any-term FTS query for recall candidate generation."""

    return query.strip() if query_identity(query) is not None else (" OR ".join(_meaningful_lexical_terms(query)) or query.strip())


def _search_request(
    request: MemoryRecallRequest,
    *,
    limit: int,
    topic_item_id: UUID | None,
    contact_item_id: UUID | None,
) -> MemorySearchRequest:
    return MemorySearchRequest(
        agent_id=request.agent_id,
        recall_query=request.query,
        # Recall is a candidate-ranking operation, not an exact search. Requiring
        # every word of a task label to match makes the lexical fail-open useless
        # precisely when the embedding provider is unavailable.
        query=_relaxed_lexical_query(request.query),
        limit=limit,
        memory_types=request.memory_types,
        node_kinds=request.node_kinds,
        task_id=request.task_id,
        memory_role=request.memory_role,
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        strict_contact_scope=request.strict_contact_scope,
        exclude_topic_projections=True,
        exclude_agent_projections=request.exclude_agent_projections,
        exclude_source_managed=request.exclude_source_managed,
    )


def _branch_requests(
    request: MemoryRecallRequest, *, limit: int
) -> tuple[MemorySearchRequest, MemorySearchRequest | None]:
    global_request = _search_request(
        request,
        limit=limit,
        topic_item_id=None,
        contact_item_id=request.contact_item_id,
    )
    thematic_request = (
        _search_request(
            request,
            limit=limit,
            topic_item_id=request.topic_item_id,
            contact_item_id=request.contact_item_id,
        )
        if request.topic_item_id is not None
        else None
    )
    return global_request, thematic_request


async def _record(
    request: MemoryRecallRequest,
    hits: Sequence[MemorySearchHit],
    *,
    record_llm_access: bool,
) -> None:
    if not record_llm_access:
        return
    await service.record_llm_retrieval(
        agent_id=request.agent_id,
        item_scores=[(hit.item.id, hit.score) for hit in hits],
        query=request.query,
        task_id=request.task_id,
        access_kind="search",
    )


def _item_filters(
    request: MemorySearchRequest,
) -> list[ColumnElement[bool]]:
    now = datetime.now(timezone.utc)
    filters: list[ColumnElement[bool]] = [
        readable_item_clause(request.agent_id),
        or_(MemoryItem.valid_from.is_(None), MemoryItem.valid_from <= now),
        or_(MemoryItem.valid_until.is_(None), MemoryItem.valid_until > now),
    ]
    if request.memory_types:
        filters.append(MemoryItem.memory_type.in_(request.memory_types))
    if request.topic_item_id is not None and request.contact_item_id is not None:
        filters.append(
            exists(
                select(MemoryTopicContactItem.id)
                .join(
                    MemoryTopicContactScope,
                    MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
                )
                .where(
                    MemoryTopicContactItem.item_id == MemoryItem.id,
                    MemoryTopicContactScope.owner_agent_id == request.agent_id,
                    MemoryTopicContactScope.topic_item_id == request.topic_item_id,
                    MemoryTopicContactScope.contact_item_id == request.contact_item_id,
                )
            )
        )
    elif request.topic_item_id is not None:
        filters.append(
            exists(
                select(MemoryLink.id).where(
                    MemoryLink.source_item_id == request.topic_item_id,
                    MemoryLink.target_item_id == MemoryItem.id,
                    MemoryLink.relation_type == "topic_contains",
                    MemoryLink.suggested.is_(False),
                )
            )
        )
    elif request.contact_item_id is not None:
        directly_scoped_to_contact = exists(
            select(MemoryContactItem.id).where(
                MemoryContactItem.item_id == MemoryItem.id,
                MemoryContactItem.owner_agent_id == request.agent_id,
                MemoryContactItem.contact_item_id == request.contact_item_id,
            )
        )
        legacy_scoped_to_contact = exists(
            select(MemoryTopicContactItem.id)
            .join(
                MemoryTopicContactScope,
                MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
            )
            .where(
                MemoryTopicContactItem.item_id == MemoryItem.id,
                MemoryTopicContactScope.owner_agent_id == request.agent_id,
                MemoryTopicContactScope.contact_item_id == request.contact_item_id,
            )
        )
        if request.strict_contact_scope:
            filters.append(
                or_(directly_scoped_to_contact, legacy_scoped_to_contact)
            )
        else:
            directly_conversation_scoped = exists(
                select(MemoryContactItem.id).where(
                    MemoryContactItem.item_id == MemoryItem.id
                )
            )
            legacy_conversation_scoped = exists(
                select(MemoryTopicContactItem.id).where(
                    MemoryTopicContactItem.item_id == MemoryItem.id
                )
            )
            filters.append(
                or_(
                    directly_scoped_to_contact,
                    legacy_scoped_to_contact,
                    ~(directly_conversation_scoped | legacy_conversation_scoped),
                )
            )
    if request.exclude_topic_projections:
        filters.extend(
            [
                or_(
                    MemoryItem.metadata_["memory_role"].as_string().is_(None),
                    MemoryItem.metadata_["memory_role"].as_string() != "topic",
                ),
                or_(
                    MemoryItem.managed_source_kind.is_(None),
                    MemoryItem.managed_source_kind != "messenger_contact",
                ),
            ]
        )
    if request.exclude_source_managed:
        filters.append(MemoryItem.source_managed.is_(False))
    if request.exclude_agent_projections:
        filters.append(
            or_(
                MemoryItem.managed_source_kind.is_(None),
                MemoryItem.managed_source_kind != "agent",
            )
        )
    if request.node_kinds:
        filters.append(MemoryItem.node_kind.in_(request.node_kinds))
    if request.memory_role == "experience":
        filters.append(
            MemoryItem.metadata_["memory_role"].as_string() == "experience"
        )
    elif request.memory_role == "ordinary":
        filters.append(
            or_(
                MemoryItem.metadata_["memory_role"].as_string().is_(None),
                MemoryItem.metadata_["memory_role"].as_string() != "experience",
            )
        )
    return filters


async def _has_semantic_index(
    request: MemorySearchRequest, model: EmbeddingModel
) -> bool:
    indexed = await get_db().scalar(
        select(MemoryEmbeddingChunk.id)
        .join(MemoryItem, MemoryItem.id == MemoryEmbeddingChunk.item_id)
        .where(
            *_item_filters(request),
            MemoryEmbeddingChunk.model_key == model.key,
            MemoryEmbeddingChunk.source_fingerprint == MemoryItem.semantic_fingerprint,
            complete_projection_clause(model.key),
        )
        .limit(1)
    )
    return indexed is not None


async def _index_coverage(request: MemorySearchRequest, model: EmbeddingModel) -> MemoryIndexCoverage:
    row = (await get_db().execute(select(
        func.count(MemoryItem.id),
        func.count(MemoryItem.id).filter(complete_projection_clause(model.key)),
    ).where(*_item_filters(request), or_(
        MemoryItem.node_kind.not_in(("attachment", "folder")), MemoryItem.search_text != "",
    )))).one()
    return MemoryIndexCoverage(model_code=model.code, eligible_items=int(row[0]), indexed_items=int(row[1]))


async def _semantic_candidates(
    request: MemorySearchRequest,
    *,
    model: EmbeddingModel,
    query_embedding: list[float],
    limit: int,
) -> list[SemanticCandidate]:
    """Return the nearest current chunk per accessible item using exact search."""

    dimensions = len(query_embedding)
    distance = cast(
        ColumnElement[float],
        sql_cast(
            MemoryEmbeddingChunk.embedding.op("<=>")(query_embedding),
            Float,
        ),
    )
    per_item = (
        select(
            MemoryEmbeddingChunk.item_id.label("item_id"),
            MemoryEmbeddingChunk.text.label("chunk_text"),
            MemoryEmbeddingChunk.embedding.label("embedding"),
            distance.label("distance"),
            MemoryItem.revision.label("revision"),
            MemoryItem.lock_version.label("lock_version"),
            MemoryItem.semantic_fingerprint.label("fingerprint"),
            MemoryEmbeddingChunk.chunk_index.label("chunk_index"),
            MemoryEmbeddingChunk.locator.label("locator"),
            func.row_number()
            .over(
                partition_by=MemoryEmbeddingChunk.item_id,
                order_by=distance,
            )
            .label("item_row"),
        )
        .join(MemoryItem, MemoryItem.id == MemoryEmbeddingChunk.item_id)
        .where(
            *_item_filters(request),
            MemoryEmbeddingChunk.model_key == model.key,
            MemoryEmbeddingChunk.dimensions == dimensions,
            MemoryEmbeddingChunk.source_fingerprint == MemoryItem.semantic_fingerprint,
            complete_projection_clause(model.key),
        )
        .subquery()
    )
    result = await get_db().execute(
        select(
            per_item.c.item_id,
            per_item.c.chunk_text,
            per_item.c.embedding,
            per_item.c.distance,
            per_item.c.revision,
            per_item.c.lock_version,
            per_item.c.fingerprint,
            per_item.c.chunk_index,
            per_item.c.locator,
        )
        .where(per_item.c.item_row <= 3)
        .order_by(per_item.c.distance, per_item.c.item_id, per_item.c.chunk_index)
        .limit(limit * 3)
    )
    rows = list(result.all())
    if not rows:
        return []
    item_ids = [cast(UUID, row[0]) for row in rows]
    item_result = await get_db().scalars(
        select(MemoryItem)
        .options(selectinload(MemoryItem.grants))
        .execution_options(populate_existing=True)
        .where(
            MemoryItem.id.in_(item_ids),
            *_item_filters(request),
        )
    )
    items = {item.id: item for item in item_result.all()}
    candidates: list[SemanticCandidate] = []
    passages_by_id: dict[UUID, list[MemorySearchPassage]] = {}
    for row in rows:
        item_id = cast(UUID, row[0])
        item = items.get(item_id)
        if item is None or (item.revision, item.lock_version, item.semantic_fingerprint) != (row[4], row[5], row[6]):
            continue
        raw_distance = float(row[3])
        if not math.isfinite(raw_distance):
            continue
        locator = dict(row[8] or {})
        passage = MemorySearchPassage(
            uri=f"{'document' if item.node_kind == 'document' else 'memory'}://{item.id}",
            revision=item.revision, chunk_index=int(row[7]), excerpt=_excerpt(str(row[1])),
            **locator,
        )
        if item_id in passages_by_id:
            passages_by_id[item_id].append(passage)
            continue
        if len(candidates) >= limit:
            continue
        passages_by_id[item_id] = [passage]
        candidates.append(
            (service.item_to_public(item, await effective_access(item, request.agent_id)),
             str(row[1]), raw_distance, list(cast(Sequence[float], row[2])), passages_by_id[item_id])
        )
    return candidates


def _fused_scores(
    ranked_sources: Sequence[tuple[MemoryRetrievalSource, Sequence[RankedItem]]],
) -> tuple[
    list[tuple[UUID, float]],
    dict[UUID, list[MemoryRetrievalSource]],
]:
    scores: dict[UUID, float] = {}
    sources: dict[UUID, list[MemoryRetrievalSource]] = {}
    for source, item_ids in ranked_sources:
        weight = _SOURCE_WEIGHTS[source]
        for rank, entry in enumerate(item_ids, start=1):
            item_id, strength = (
                entry if isinstance(entry, tuple) else (entry, 1.0)
            )
            scores[item_id] = scores.get(item_id, 0.0) + (
                weight * max(0.0, min(1.0, strength))
                / (RRF_RANK_CONSTANT + rank)
            )
            item_sources = sources.setdefault(item_id, [])
            if source not in item_sources:
                item_sources.append(source)
    fused = sorted(scores.items(), key=lambda entry: (-entry[1], str(entry[0])))
    return fused, sources


async def _graph_candidates(
    request: MemorySearchRequest,
    *,
    seed_ids: Sequence[UUID],
    limit: int,
) -> list[tuple[MemoryItemPublic, str, float]]:
    """Expand one hop through strong confirmed links after applying recall scope."""

    ordered_seeds = tuple(dict.fromkeys(seed_ids))
    if not ordered_seeds:
        return []
    seed_ranks = {
        item_id: rank for rank, item_id in enumerate(ordered_seeds, start=1)
    }
    rows = (
        await get_db().execute(
            select(
                MemoryLink.source_item_id,
                MemoryLink.target_item_id,
                MemoryLink.confidence,
            ).where(
                MemoryLink.suggested.is_(False),
                MemoryLink.confidence >= MIN_GRAPH_LINK_CONFIDENCE,
                or_(
                    MemoryLink.source_item_id.in_(ordered_seeds),
                    MemoryLink.target_item_id.in_(ordered_seeds),
                ),
            )
        )
    ).all()
    evidence: dict[UUID, tuple[int, float]] = {}
    for source_id, target_id, raw_confidence in rows:
        confidence = float(raw_confidence)
        if not math.isfinite(confidence):
            continue
        for seed_id, neighbor_id in (
            (cast(UUID, source_id), cast(UUID, target_id)),
            (cast(UUID, target_id), cast(UUID, source_id)),
        ):
            seed_rank = seed_ranks.get(seed_id)
            if seed_rank is None:
                continue
            candidate = (seed_rank, max(0.0, min(1.0, confidence)))
            current = evidence.get(neighbor_id)
            if current is None or (candidate[0], -candidate[1]) < (
                current[0],
                -current[1],
            ):
                evidence[neighbor_id] = candidate
    if not evidence:
        return []
    item_rows = await get_db().scalars(
        select(MemoryItem)
        .options(selectinload(MemoryItem.grants))
        .execution_options(populate_existing=True)
        .where(MemoryItem.id.in_(evidence), *_item_filters(request))
    )
    items = {item.id: item for item in item_rows.all()}
    ranked_ids = sorted(
        items,
        key=lambda item_id: (
            evidence[item_id][0],
            -evidence[item_id][1],
            str(item_id),
        ),
    )[:limit]
    return [
        (service.item_to_public(items[item_id], await effective_access(items[item_id], request.agent_id)),
         items[item_id].search_text, evidence[item_id][1])
        for item_id in ranked_ids
    ]


async def _weighted_rank(
    *,
    parameters: _RecallParameters,
    scope_request: MemorySearchRequest,
    ranked_sources: Sequence[tuple[MemoryRetrievalSource, Sequence[RankedItem]]],
    lexical_by_id: dict[UUID, MemorySearchHit],
    semantic_by_id: dict[
        UUID, tuple[MemoryItemPublic, str, float | None, list[float] | None]
    ],
    graph_candidates: Sequence[tuple[MemoryItemPublic, str, float]],
    thematic_affinity: float,
    structural_paths: dict[UUID, list[MemoryTraversalStep]],
) -> tuple[
    list[tuple[UUID, float]],
    dict[UUID, list[MemoryRetrievalSource]],
]:
    """Rank the available query candidates without a relevance admission cutoff."""

    _rrf, sources = _fused_scores(ranked_sources)
    query = scope_request.recall_query if scope_request.recall_query is not None else scope_request.query
    evidence_text: dict[UUID, str] = {}
    candidate_items: dict[UUID, MemoryItemPublic] = {}
    for identity in sources:
        lexical_hit = lexical_by_id.get(identity)
        semantic_entry = semantic_by_id.get(identity)
        if lexical_hit is not None and semantic_entry is not None and not _same_snapshot(lexical_hit.item, semantic_entry[0]):
            # Never transfer evidence from an older lexical page onto a newer
            # semantic snapshot that would pass the final admission check.
            lexical_by_id.pop(identity)
            sources[identity] = [source for source in sources[identity] if not source.endswith("_lexical")]
            lexical_hit = None
        fragments: list[str] = []
        if lexical_hit is not None:
            fragments.extend((lexical_hit.item.title, lexical_hit.excerpt))
            candidate_items[identity] = lexical_hit.item
        if semantic_entry is not None:
            fragments.extend((semantic_entry[0].title, semantic_entry[1]))
            candidate_items[identity] = semantic_entry[0]
        evidence_text[identity] = " ".join(fragments)
    weights = relevance.term_weights(query, evidence_text.values())
    lexical_evidence = {identity: relevance.coverage(text, weights) for identity, text in evidence_text.items()}
    exact_ids = {identity for identity, item in candidate_items.items()
                 if query_identity(query) == identity or relevance.fold(query.strip()) == relevance.fold(item.title.strip())}
    # Lexical/vector scores order candidates; they must never empty the recall.
    # Graph-only neighbours remain contextual bonuses, not standalone evidence.
    eligible_ids = {
        identity for identity in candidate_items
        if any(source.endswith(("_lexical", "_vector")) for source in sources[identity])
    }
    structural = await _structural_candidates(scope_request, seeds=eligible_ids, limit=parameters.candidate_limit, paths=structural_paths)
    graph_candidates = [*graph_candidates, *structural]
    for item, text, _strength in structural:
        content = f"{item.title} {text}"
        if not text.strip() or not relevance.matched_terms(content, weights):
            continue
        eligible_ids.add(item.id)
        evidence_text[item.id] = content
        candidate_items[item.id] = item
        lexical_evidence[item.id] = relevance.coverage(content, weights)
        item_sources = sources.setdefault(item.id, [])
        if "structural_link" not in item_sources:
            item_sources.append("structural_link")
        semantic_by_id.setdefault(item.id, (item, text, None, None))
    sources = {
        item_id: item_sources
        for item_id, item_sources in sources.items()
        if item_id in eligible_ids
    }
    candidate_ids = tuple(sources)
    if not candidate_ids:
        return [], sources

    lexical = _normalized(
        {
            item_id: hit.score
            for item_id, hit in lexical_by_id.items()
            if item_id in sources
        }
    )
    semantic = {
        item_id: float(entry[2] or 0.0)
        for item_id, entry in semantic_by_id.items()
        if item_id in sources
    }
    graph = {
        item.id: max(0.0, min(1.0, confidence))
        for item, _text, confidence in graph_candidates
        if item.id in sources
    }
    if parameters.suggested_link_weight > 0:
        suggested_rows = (
            await get_db().execute(
                select(MemoryLink.target_item_id, MemoryLink.confidence).where(
                    MemoryLink.suggested.is_(True),
                    MemoryLink.relation_type == SUGGESTED_TOPIC_RELATION,
                    MemoryLink.target_item_id.in_(candidate_ids),
                )
            )
        ).all()
        for target_id, raw_confidence in suggested_rows:
            item_id = cast(UUID, target_id)
            confidence = float(raw_confidence)
            if not math.isfinite(confidence):
                continue
            strength = (
                max(0.0, min(1.0, confidence))
                * parameters.suggested_link_weight
            )
            graph[item_id] = max(graph.get(item_id, 0.0), strength)
            item_sources = sources.setdefault(item_id, [])
            if "suggested_topic_link" not in item_sources:
                item_sources.append("suggested_topic_link")

    source_rows = (
        await get_db().execute(
            select(MemorySource.item_id, func.count(MemorySource.id))
            .where(MemorySource.item_id.in_(candidate_ids))
            .group_by(MemorySource.item_id)
        )
    ).all()
    authority = _normalized(
        {
            cast(UUID, item_id): math.log1p(int(count))
            for item_id, count in source_rows
        }
    )

    link_rows = (
        await get_db().execute(
            select(
                MemoryLink.source_item_id,
                MemoryLink.target_item_id,
                MemoryLink.confidence,
            ).where(
                MemoryLink.suggested.is_(False),
                or_(
                    MemoryLink.source_item_id.in_(candidate_ids),
                    MemoryLink.target_item_id.in_(candidate_ids),
                ),
            )
        )
    ).all()
    related_ids = set(candidate_ids)
    for source_id, target_id, _confidence in link_rows:
        related_ids.update((cast(UUID, source_id), cast(UUID, target_id)))
    readable_related_ids: set[UUID] = set(
        (
            await get_db().scalars(
                select(MemoryItem.id).where(
                    MemoryItem.id.in_(related_ids),
                    *_item_filters(scope_request),
                )
            )
        ).all()
    )
    weighted_degree: dict[UUID, float] = {}
    for source_id, target_id, confidence in link_rows:
        source_uuid = cast(UUID, source_id)
        target_uuid = cast(UUID, target_id)
        if not {source_uuid, target_uuid}.issubset(readable_related_ids):
            continue
        strength = max(0.0, min(1.0, float(confidence)))
        for item_id in (source_uuid, target_uuid):
            if item_id in sources:
                weighted_degree[item_id] = (
                    weighted_degree.get(item_id, 0.0) + strength
                )
    centrality = _normalized(
        {item_id: math.log1p(value) for item_id, value in weighted_degree.items()}
    )

    now = datetime.now(timezone.utc)
    freshness: dict[UUID, float] = {}
    text_by_id: dict[UUID, str] = {}
    embedding_by_id: dict[UUID, list[float]] = {}
    for item_id in candidate_ids:
        semantic_entry = semantic_by_id.get(item_id)
        lexical_hit = lexical_by_id.get(item_id)
        if semantic_entry is not None:
            item, chunk_text, _similarity, embedding = semantic_entry
            changed_at = item.updated_at or item.created_at
            text_by_id[item_id] = " ".join((item.title, chunk_text))
            if embedding is not None:
                embedding_by_id[item_id] = embedding
        elif lexical_hit is not None:
            changed_at = lexical_hit.item.updated_at or lexical_hit.item.created_at
            text_by_id[item_id] = " ".join(
                (
                    lexical_hit.item.title,
                    lexical_hit.excerpt,
                )
            )
        else:
            continue
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - changed_at).total_seconds() / 86_400)
        freshness[item_id] = math.exp(-age_days / 365.0)

    scores: dict[UUID, float] = {}
    bounded_thematic_affinity = max(0.0, min(1.0, thematic_affinity))
    for item_id in candidate_ids:
        item_sources = sources.get(item_id, [])
        thematic = any(source.startswith("thematic_") for source in item_sources)
        bonus = (
            parameters.topic_weight
            * (bounded_thematic_affinity if thematic else 0.0)
            + parameters.graph_weight * graph.get(item_id, 0.0)
            + parameters.authority_weight * authority.get(item_id, 0.0)
            + parameters.freshness_weight * freshness.get(item_id, 0.0)
            + parameters.centrality_weight * centrality.get(item_id, 0.0)
        )
        content_weight = parameters.semantic_weight + parameters.lexical_weight
        semantic_share = parameters.semantic_weight / content_weight if content_weight else 0.5
        evidence = lexical_evidence.get(item_id, 0.0)
        primary = evidence + 0.30 * (semantic_share * semantic.get(item_id, 0.0)
                                     + (1.0 - semantic_share) * lexical.get(item_id, 0.0))
        scores[item_id] = min(1.0, (primary + 0.03 * bonus) / 1.33)

    tiers = {identity: (3 if identity in exact_ids else 2 if lexical_evidence.get(identity, 0.0) >= 0.65 else 1)
             for identity in candidate_ids}

    selected: list[tuple[UUID, float]] = []
    remaining = set(candidate_ids)
    pair_similarities: dict[tuple[UUID, UUID], float] = {}
    while remaining and len(selected) < parameters.limit:
        best_id: UUID | None = None
        best_adjusted = -1.0
        for item_id in remaining:
            maximum_similarity = 0.0
            duplicate = False
            for selected_id, _score in selected:
                pair = (item_id, selected_id)
                left_item, right_item = candidate_items[item_id], candidate_items[selected_id]
                duplicate = duplicate or (left_item.content_hash == right_item.content_hash
                    and relevance.fold(left_item.title) == relevance.fold(right_item.title)
                    and item_id not in exact_ids)
                if pair not in pair_similarities:
                    left_embedding = embedding_by_id.get(item_id)
                    right_embedding = embedding_by_id.get(selected_id)
                    vector_similarity = _cosine(left_embedding, right_embedding) if left_embedding is not None and right_embedding is not None else 0.0
                    text_similarity = _text_similarity(text_by_id.get(item_id, ""), text_by_id.get(selected_id, ""))
                    pair_similarities[pair] = 0.75 * vector_similarity + 0.25 * text_similarity if vector_similarity > 0 else text_similarity
                maximum_similarity = max(maximum_similarity, pair_similarities[pair])
            if duplicate:
                continue
            adjusted = max(
                0.0,
                scores[item_id]
                - min(0.05, parameters.diversity_lambda) * maximum_similarity,
            )
            if best_id is None or (tiers[item_id], adjusted, str(item_id)) > (
                tiers[best_id], best_adjusted, str(best_id),
            ):
                best_id = item_id
                best_adjusted = adjusted
        if best_id is None:
            break
        selected.append((best_id, best_adjusted))
        remaining.remove(best_id)
    return selected, sources


async def _structural_candidates(
    request: MemorySearchRequest, *, seeds: set[UUID], limit: int,
    paths: dict[UUID, list[MemoryTraversalStep]],
) -> list[tuple[MemoryItemPublic, str, float]]:
    """Four authorized hops, at most 500 visible edges per level.

    References follow their source direction; containment can be traversed in
    either direction. Filtering precedes limits, so hidden nodes cannot consume
    the budget or bridge between two visible nodes.
    """
    from .document_structure import PROJECTION

    if not seeds or not request.query.strip() or query_identity(request.query) is not None:
        return []
    traversal_request = request.model_copy(update={"node_kinds": None})
    visible = select(MemoryItem.id).where(*_item_filters(traversal_request)).correlate(None)
    visited = set(seeds)
    frontier = set(seeds)
    strengths: dict[UUID, float] = {}
    for depth in range(1, 5):
        edges = (await get_db().execute(select(
            MemoryLink.source_item_id, MemoryLink.target_item_id, MemoryLink.relation_type,
        ).where(
            MemoryLink.projection_key == PROJECTION,
            MemoryLink.suggested.is_(False),
            MemoryLink.source_item_id.in_(visible), MemoryLink.target_item_id.in_(visible),
            or_(MemoryLink.source_item_id.in_(frontier), MemoryLink.target_item_id.in_(frontier)),
        ).order_by(MemoryLink.source_item_id, MemoryLink.target_item_id, MemoryLink.relation_type).limit(500))).all()
        next_ids: set[UUID] = set()
        for source, target, relation in edges:
            step = MemoryTraversalStep(source_item_id=source, target_item_id=target, relation_type=relation)
            if source in frontier and target not in visited:
                next_ids.add(target)
                paths.setdefault(target, [*paths.get(source, []), step])
            if relation in {"in_folder", "parent_of", "has_attachment"} and target in frontier and source not in visited:
                next_ids.add(source)
                paths.setdefault(source, [*paths.get(target, []), step])
        frontier = set(sorted(next_ids, key=str)[:max(0, limit - len(strengths))])
        if not frontier:
            break
        strengths.update({identity: 1 / depth for identity in frontier})
        visited.update(frontier)
    items = await get_db().scalars(select(MemoryItem).options(selectinload(MemoryItem.grants)).execution_options(populate_existing=True).where(
        MemoryItem.id.in_(strengths), *_item_filters(request),
    ))
    return [(service.item_to_public(item, await effective_access(item, request.agent_id)),
             item.search_text, strengths[item.id]) for item in items]


def _excerpt(text: str, *, limit: int = 800) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _same_snapshot(left: MemoryItemPublic, right: MemoryItemPublic) -> bool:
    return (left.id, left.revision, left.lock_version, left.content_hash, left.semantic_fingerprint) == (
        right.id, right.revision, right.lock_version, right.content_hash, right.semantic_fingerprint,
    )


async def _hydrate_hits(
    request: MemoryRecallRequest,
    *,
    fused: Sequence[tuple[UUID, float]],
    sources: dict[UUID, list[MemoryRetrievalSource]],
    structural_paths: dict[UUID, list[MemoryTraversalStep]],
    lexical_by_id: dict[UUID, MemorySearchHit],
    semantic_by_id: dict[
        UUID, tuple[MemoryItemPublic, str, float | None, list[float] | None]
    ],
    passages_by_id: dict[UUID, list[MemorySearchPassage]] | None = None,
) -> list[MemorySearchHit]:
    hits: list[MemorySearchHit] = []
    query_terms = set(relevance.terms(request.query))
    for item_id, score in fused:
        semantic_entry = semantic_by_id.get(item_id)
        lexical_hit = lexical_by_id.get(item_id)
        if semantic_entry is not None:
            item, chunk_text, semantic_similarity, _embedding = semantic_entry
            if not item.access.can_read:
                continue
            item_public = item
            excerpt = _excerpt(chunk_text)
            source_refs = (
                lexical_hit.source_refs
                if lexical_hit is not None
                else await service.source_refs(item.id)
            )
        else:
            assert lexical_hit is not None
            item_public = lexical_hit.item
            excerpt = lexical_hit.excerpt
            source_refs = lexical_hit.source_refs
            semantic_similarity = None
        if lexical_hit is not None and query_terms and _same_snapshot(lexical_hit.item, item_public):
            # A vector can identify the right document through its introduction
            # while the lexical window contains the requested table or fact.
            # Both excerpts carry the same revision proof checked at admission.
            lexical_evidence = query_terms.intersection(
                relevance.terms(lexical_hit.excerpt)
            )
            current_evidence = query_terms.intersection(
                relevance.terms(excerpt)
            )
            if len(lexical_evidence) > len(current_evidence):
                excerpt = lexical_hit.excerpt
        hits.append(
            MemorySearchHit(
                item=item_public,
                excerpt=excerpt,
                score=score,
                semantic_similarity=semantic_similarity,
                passages=(passages_by_id or {}).get(item_id, []),
                source_refs=source_refs,
                retrieval_sources=sources.get(item_id, []),
                structural_path=structural_paths.get(item_id, []),
            )
        )
    return hits


def _candidate_counts(
    sources: dict[UUID, list[MemoryRetrievalSource]],
) -> tuple[int, int]:
    thematic = sum(
        any(source.startswith("thematic_") for source in item_sources)
        for item_sources in sources.values()
    )
    global_ = sum(
        any(source.startswith("global_") for source in item_sources)
        for item_sources in sources.values()
    )
    return thematic, global_


def _result_counts(hits: Sequence[MemorySearchHit]) -> tuple[int, int]:
    thematic = sum(
        any(source.startswith("thematic_") for source in hit.retrieval_sources)
        for hit in hits
    )
    global_ = sum(
        any(source.startswith("global_") for source in hit.retrieval_sources)
        for hit in hits
    )
    return thematic, global_


async def _lexical_recall(
    request: MemoryRecallRequest,
    *,
    parameters: _RecallParameters,
    global_page: MemorySearchPage,
    thematic_page: MemorySearchPage | None,
    record_llm_access: bool,
    degraded: bool = False,
    degradation_reason: str | None = None,
    thematic_affinity: float = 0.0,
) -> MemoryRecallResult:
    ranked_sources: list[tuple[MemoryRetrievalSource, Sequence[RankedItem]]] = []
    lexical_by_id = {hit.item.id: hit for hit in global_page.hits}
    global_strengths = _normalized(
        {hit.item.id: hit.score for hit in global_page.hits}
    )
    if thematic_page is not None:
        lexical_by_id.update({hit.item.id: hit for hit in thematic_page.hits})
        thematic_strengths = _normalized(
            {hit.item.id: hit.score for hit in thematic_page.hits}
        )
        ranked_sources.append(
            (
                "thematic_lexical",
                [
                    (hit.item.id, thematic_strengths.get(hit.item.id, 1.0))
                    for hit in thematic_page.hits
                ],
            )
        )
    ranked_sources.append(
        (
            "global_lexical",
            [
                (hit.item.id, global_strengths.get(hit.item.id, 1.0))
                for hit in global_page.hits
            ],
        )
    )
    seed_ranking, _seed_sources = _fused_scores(ranked_sources)
    global_request, _thematic_request = _branch_requests(
        request,
        limit=parameters.candidate_limit,
    )
    graph_candidates = await _graph_candidates(
        global_request,
        seed_ids=[item_id for item_id, _score in seed_ranking],
        limit=parameters.candidate_limit,
    )
    if graph_candidates:
        ranked_sources.append(
            (
                "graph_link",
                [
                    (item.id, confidence)
                    for item, _text, confidence in graph_candidates
                ],
            )
        )
    semantic_by_id: dict[
        UUID, tuple[MemoryItemPublic, str, float | None, list[float] | None]
    ] = {
        item.id: (item, text, None, None)
        for item, text, _confidence in graph_candidates
    }
    structural_paths: dict[UUID, list[MemoryTraversalStep]] = {}
    fused, sources = await _weighted_rank(
        structural_paths=structural_paths,
        parameters=parameters,
        scope_request=global_request,
        ranked_sources=ranked_sources,
        lexical_by_id=lexical_by_id,
        semantic_by_id=semantic_by_id,
        graph_candidates=graph_candidates,
        thematic_affinity=thematic_affinity,
    )
    hits = await _hydrate_hits(
        request,
        structural_paths=structural_paths,
        fused=fused,
        sources=sources,
        lexical_by_id=lexical_by_id,
        semantic_by_id=semantic_by_id,
    )
    thematic_candidates, global_candidates = _candidate_counts(sources)
    thematic_results, global_results = _result_counts(hits)
    return MemoryRecallResult(
        query=request.query.strip(),
        hits=hits,
        mode="lexical",
        degraded=degraded,
        degradation_reason=degradation_reason,
        has_more=(
            global_page.has_more
            or (thematic_page is not None and thematic_page.has_more)
            or len(sources) > parameters.limit
        ),
        ranking_version=RRF_RANKING_VERSION,
        thematic_candidate_count=thematic_candidates,
        global_candidate_count=global_candidates,
        thematic_result_count=thematic_results,
        global_result_count=global_results,
    )


async def _recall_items(
    request: MemoryRecallRequest,
    *,
    record_llm_access: bool = False,
    diagnostics: _RecallDiagnostics | None = None,
) -> MemoryRecallResult:
    """Combine thematic and global ranks while preserving lexical fail-open."""

    parameters = _resolve_parameters(request)
    request = request.model_copy(update={"limit": parameters.limit})
    candidate_limit = parameters.candidate_limit
    global_request, thematic_request = _branch_requests(
        request,
        limit=candidate_limit,
    )
    thematic_affinity = 1.0 if thematic_request is not None else 0.0
    # Short titles and identifiers still need a lexical lookup, even when the
    # query has no terms long enough for the relaxed full-text expansion.
    global_page = await service.search_items(global_request, record_llm_access=False)
    thematic_page = (
        await service.search_items(thematic_request, record_llm_access=False)
        if thematic_request is not None
        else None
    )
    if not request.query.strip() or query_identity(request.query) is not None:
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )

    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="embedding_not_configured",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )
    except Exception:
        logger.exception("Memory embedding model resolution failed")
        await get_db().rollback()
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="embedding_unavailable",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )

    try:
        if diagnostics is not None:
            diagnostics.model = model
            diagnostics.coverage = await _index_coverage(global_request, model)
        index_available = await _has_semantic_index(global_request, model)
    except Exception:
        logger.exception("Memory semantic index availability check failed")
        await get_db().rollback()
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="semantic_index_unavailable",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )
    if not index_available:
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="embedding_index_empty",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )

    try:
        query_embedding = await embed_query(parameters.semantic_query, model=model)
        if thematic_request is None and parameters.topic_weight > 0:
            topic_ranking = await rank_topic_projection_embeddings(
                query_embedding,
                model=model,
                limit=1,
                agent_id=request.agent_id,
            )
            if topic_ranking.matches:
                closest_topic = topic_ranking.matches[0]
                thematic_affinity = max(
                    0.0,
                    min(1.0, closest_topic.similarity),
                )
                if thematic_affinity >= MIN_INFERRED_TOPIC_SIMILARITY:
                    thematic_request = _search_request(
                        request,
                        limit=candidate_limit,
                        topic_item_id=closest_topic.memory_item_id,
                        contact_item_id=request.contact_item_id,
                    )
                    thematic_page = await service.search_items(
                        thematic_request,
                        record_llm_access=False,
                    )
        global_semantic = await _semantic_candidates(
            global_request,
            model=model,
            query_embedding=query_embedding,
            limit=candidate_limit,
        )
        thematic_semantic = (
            await _semantic_candidates(
                thematic_request,
                model=model,
                query_embedding=query_embedding,
                limit=candidate_limit,
            )
            if thematic_request is not None
            else []
        )
    except MemoryEmbeddingError:
        logger.warning("Advanced memory search fell back to lexical retrieval")
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="embedding_unavailable",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )
    except Exception:
        logger.exception("Advanced memory semantic search failed")
        await get_db().rollback()
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="semantic_search_failed",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )
    if not global_semantic:
        return await _lexical_recall(
            request,
            parameters=parameters,
            global_page=global_page,
            thematic_page=thematic_page,
            degraded=True,
            degradation_reason="no_current_semantic_candidates",
            record_llm_access=record_llm_access,
            thematic_affinity=thematic_affinity,
        )

    lexical_by_id = {hit.item.id: hit for hit in global_page.hits}
    global_lexical_strengths = _normalized(
        {hit.item.id: hit.score for hit in global_page.hits}
    )
    thematic_lexical_strengths: dict[UUID, float] = {}
    if thematic_page is not None:
        lexical_by_id.update({hit.item.id: hit for hit in thematic_page.hits})
        thematic_lexical_strengths = _normalized(
            {hit.item.id: hit.score for hit in thematic_page.hits}
        )
    semantic_by_id: dict[
        UUID, tuple[MemoryItemPublic, str, float | None, list[float] | None]
    ] = {
        item.id: (
            item,
            chunk_text,
            max(0.0, min(1.0, 1.0 - distance)),
            embedding,
        )
        for item, chunk_text, distance, embedding, _passages in global_semantic
    }
    semantic_by_id.update(
        {
            item.id: (
                item,
                chunk_text,
                max(0.0, min(1.0, 1.0 - distance)),
                embedding,
            )
            for item, chunk_text, distance, embedding, _passages in thematic_semantic
        }
    )
    ranked_sources: list[tuple[MemoryRetrievalSource, Sequence[RankedItem]]] = []
    if thematic_page is not None:
        ranked_sources.extend(
            [
                (
                    "thematic_lexical",
                    [
                        (
                            hit.item.id,
                            thematic_lexical_strengths.get(hit.item.id, 1.0),
                        )
                        for hit in thematic_page.hits
                    ],
                ),
                (
                    "thematic_vector",
                    [
                        (item.id, max(0.0, min(1.0, 1.0 - distance)))
                        for item, _text, distance, _embedding, _passages in thematic_semantic
                    ],
                ),
            ]
        )
    ranked_sources.extend(
        [
            (
                "global_lexical",
                [
                    (hit.item.id, global_lexical_strengths.get(hit.item.id, 1.0))
                    for hit in global_page.hits
                ],
            ),
            (
                "global_vector",
                [
                    (item.id, max(0.0, min(1.0, 1.0 - distance)))
                    for item, _text, distance, _embedding, _passages in global_semantic
                ],
            ),
        ]
    )
    seed_ranking, _seed_sources = _fused_scores(ranked_sources)
    graph_candidates = await _graph_candidates(
        global_request,
        seed_ids=[item_id for item_id, _score in seed_ranking],
        limit=candidate_limit,
    )
    if graph_candidates:
        ranked_sources.append(
            (
                "graph_link",
                [
                    (item.id, confidence)
                    for item, _text, confidence in graph_candidates
                ],
            )
        )
        for item, chunk_text, _confidence in graph_candidates:
            semantic_by_id.setdefault(item.id, (item, chunk_text, None, None))
    structural_paths: dict[UUID, list[MemoryTraversalStep]] = {}
    fused, sources = await _weighted_rank(
        structural_paths=structural_paths,
        parameters=parameters,
        scope_request=global_request,
        ranked_sources=ranked_sources,
        lexical_by_id=lexical_by_id,
        semantic_by_id=semantic_by_id,
        graph_candidates=graph_candidates,
        thematic_affinity=thematic_affinity,
    )
    hits = await _hydrate_hits(
        request,
        structural_paths=structural_paths,
        fused=fused,
        sources=sources,
        lexical_by_id=lexical_by_id,
        semantic_by_id=semantic_by_id,
        passages_by_id={item.id: passages for item, _text, _distance, _embedding, passages in
                        [*global_semantic, *thematic_semantic]},
    )
    thematic_candidates, global_candidates = _candidate_counts(sources)
    thematic_results, global_results = _result_counts(hits)
    return MemoryRecallResult(
        query=request.query.strip(),
        hits=hits,
        mode="hybrid",
        has_more=(
            global_page.has_more
            or (thematic_page is not None and thematic_page.has_more)
            or len(global_semantic) >= candidate_limit
            or len(thematic_semantic) >= candidate_limit
            or len(sources) > parameters.limit
        ),
        ranking_version=RRF_RANKING_VERSION,
        thematic_candidate_count=thematic_candidates,
        global_candidate_count=global_candidates,
        thematic_result_count=thematic_results,
        global_result_count=global_results,
    )


async def _enrich_document_passages(
    request: MemoryRecallRequest, hits: Sequence[MemorySearchHit], model: EmbeddingModel,
) -> None:
    """Merge lexical and vector passages from the same admitted source generation."""
    documents = {hit.item.id: hit for hit in hits if hit.item.node_kind == "document"}
    prefix = relevance.prefix_query(request.query)
    if not documents or not prefix or query_identity(request.query) is not None:
        return
    ts_query = func.to_tsquery("simple", prefix)
    vector = func.to_tsvector("simple", MemoryEmbeddingChunk.text)
    rank = func.ts_rank_cd(vector, ts_query)
    per_document = select(
        MemoryEmbeddingChunk.item_id, MemoryEmbeddingChunk.chunk_index,
        MemoryEmbeddingChunk.text.label("chunk_text"), MemoryEmbeddingChunk.locator,
        MemoryItem.revision, MemoryItem.lock_version, MemoryItem.semantic_fingerprint,
        func.row_number().over(partition_by=MemoryEmbeddingChunk.item_id,
                               order_by=(rank.desc(), MemoryEmbeddingChunk.chunk_index)).label("position"),
    ).join(MemoryItem, MemoryItem.id == MemoryEmbeddingChunk.item_id).where(
        MemoryEmbeddingChunk.item_id.in_(documents), MemoryEmbeddingChunk.model_key == model.key,
        MemoryEmbeddingChunk.source_fingerprint == MemoryItem.semantic_fingerprint,
        complete_projection_clause(model.key), vector.op("@@")(ts_query),
        readable_item_clause(request.agent_id),
    ).subquery()
    rows = (await get_db().execute(select(per_document).where(per_document.c.position <= 3))).mappings().all()
    for row in rows:
        hit = documents[cast(UUID, row["item_id"])]
        if (hit.item.revision, hit.item.lock_version, hit.item.semantic_fingerprint) != (
            row["revision"], row["lock_version"], row["semantic_fingerprint"],
        ):
            continue
        passage = MemorySearchPassage(
            uri=f"document://{hit.item.id}", revision=hit.item.revision,
            chunk_index=int(row["chunk_index"]),
            excerpt=lexical_excerpt(str(row["chunk_text"]), request.query),
            **dict(row["locator"] or {}),
        )
        hit.passages = [p for p in hit.passages if p.chunk_index != passage.chunk_index] + [passage]
    for hit in documents.values():
        weights = relevance.term_weights(request.query, [hit.excerpt, *(p.excerpt for p in hit.passages)])
        hit.passages.sort(key=lambda p: (-relevance.coverage(p.excerpt, weights), p.chunk_index))
        hit.passages = hit.passages[:3]
        if hit.passages and relevance.coverage(hit.passages[0].excerpt, weights) >= relevance.coverage(hit.excerpt, weights):
            hit.excerpt = hit.passages[0].excerpt


async def admit_recall_hits(request: MemoryRecallRequest, hits: Sequence[MemorySearchHit]) -> list[MemorySearchHit]:
    """Recheck the live scope as well as revision and access before exposure."""
    global_request, _ = _branch_requests(request, limit=max(1, len(hits)))
    return await admit_search_hits(request.agent_id, hits, scope_filters=_item_filters(global_request))


async def recall_items(
    request: MemoryRecallRequest,
    *,
    record_llm_access: bool = False,
    telemetry_kind: str | None = None,
) -> MemoryRecallResult:
    """Recall memories and publish content-free operational measurements."""

    started_at = time.perf_counter()
    diagnostics = _RecallDiagnostics()
    result = await _recall_items(
        request,
        record_llm_access=record_llm_access,
        diagnostics=diagnostics,
    )
    result.index_coverage = diagnostics.coverage
    if diagnostics.model is not None:
        await _enrich_document_passages(request, result.hits, diagnostics.model)
    if diagnostics.coverage is not None and diagnostics.coverage.indexed_items < diagnostics.coverage.eligible_items:
        result.degraded = True
        result.degradation_reason = result.degradation_reason or "semantic_index_partial"
    original_count = len(result.hits)
    result.hits = await admit_recall_hits(request, result.hits)
    result.relevance_status = "matched" if result.hits else "no_sufficient_evidence"
    result.admission_omitted_count = original_count - len(result.hits)
    if result.admission_omitted_count:
        result.degraded = True
        result.degradation_reason = result.degradation_reason or "results_changed_during_search"
        result.has_more = True
    result.thematic_result_count, result.global_result_count = _result_counts(result.hits)
    await _record(request, result.hits, record_llm_access=record_llm_access)
    metrics.observe_recall(
        kind=telemetry_kind or ("search" if record_llm_access else "internal"),
        mode=result.mode,
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        result_count=len(result.hits),
        latency_seconds=max(0.0, time.perf_counter() - started_at),
    )
    return result


__all__ = ["recall_items"]
