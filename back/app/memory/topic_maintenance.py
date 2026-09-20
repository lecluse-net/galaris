"""Private-scope vector evidence for non-authoritative Topic maintenance."""

from __future__ import annotations

import asyncio
import hashlib
import math
import multiprocessing
import os
import struct
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable, Mapping, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import LargeBinary, and_, func, or_, select

from core.database import get_db

from .contracts import (
    TopicMaintenancePlan,
    TopicMaintenanceResult,
    TopicMaintenanceSuggestion,
)
from .embedding import (
    MemoryEmbeddingNotConfiguredError,
    resolve_embedding_model,
)
from .models import MemoryEmbeddingChunk, MemoryItem, MemoryLink


SUGGESTION_VERSION = 1
MAX_INDEXED_CHUNKS = 10_000
MAX_SUGGESTIONS_PER_KIND = 100
ORPHAN_MIN_SIMILARITY = 0.55
OUTLIER_MAX_SIMILARITY = 0.20
MERGE_MIN_SIMILARITY = 0.90
SPLIT_CLUSTER_MIN_SIMILARITY = 0.75
SPLIT_GROUP_MAX_SIMILARITY = 0.35
GENERATED_BY = "topic_maintenance"

TOPIC_MEMBERSHIP_CANDIDATE = "topic_membership_candidate"
TOPIC_MEMBERSHIP_ANOMALY = "topic_membership_anomaly"
TOPIC_MERGE_CANDIDATE = "topic_merge_candidate"
TOPIC_SPLIT_CANDIDATE = "topic_split_candidate"
SUGGESTED_RELATIONS = frozenset(
    {
        TOPIC_MEMBERSHIP_CANDIDATE,
        TOPIC_MEMBERSHIP_ANOMALY,
        TOPIC_MERGE_CANDIDATE,
        TOPIC_SPLIT_CANDIDATE,
    }
)


@dataclass(frozen=True, slots=True)
class _IndexedItem:
    item_id: UUID
    owner_agent_id: int | None
    vector: tuple[float, ...]
    fingerprint: str


_RawChunk = tuple[UUID, int | None, str, bytes]
_compute_pool: ProcessPoolExecutor | None = None
_compute_lock: asyncio.Lock | None = None


def _lower_compute_priority() -> None:
    # This process only computes rebuildable suggestions; audio/HTTP come first.
    os.nice(10)


def stop_topic_maintenance() -> None:
    """Stop CPU work on cancellation/shutdown instead of leaving it running."""
    global _compute_pool
    pool, _compute_pool = _compute_pool, None
    if pool is not None:
        pool.terminate_workers()


def _normalized(values: Iterable[float]) -> tuple[float, ...] | None:
    vector = tuple(float(value) for value in values)
    norm = math.sqrt(sum(value * value for value in vector))
    if not vector or not math.isfinite(norm) or norm <= 0.0:
        return None
    return tuple(value / norm for value in vector)


def _mean_vector(vectors: list[tuple[float, ...]]) -> tuple[float, ...] | None:
    if not vectors:
        return None
    if len(vectors) == 1:
        return _normalized(vectors[0])
    dimensions = len(vectors[0])
    compatible = [vector for vector in vectors if len(vector) == dimensions]
    if not compatible:
        return None
    return _normalized(
        sum(vector[index] for vector in compatible) / len(compatible)
        for index in range(dimensions)
    )


def _similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return -1.0
    value = math.sumprod(left, right)
    return max(-1.0, min(1.0, value))


def _confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


async def _indexed_rows(model_key: str) -> list[_RawChunk]:
    rows = list(
        (
            await get_db().execute(
                select(
                    MemoryItem.id,
                    MemoryItem.owner_agent_id,
                    MemoryItem.semantic_fingerprint,
                    # Leave vector decoding to the CPU process as well.
                    func.vector_send(MemoryEmbeddingChunk.embedding, type_=LargeBinary),
                )
                .join(
                    MemoryEmbeddingChunk,
                    MemoryEmbeddingChunk.item_id == MemoryItem.id,
                )
                .where(
                    MemoryEmbeddingChunk.model_key == model_key,
                    MemoryEmbeddingChunk.source_fingerprint
                    == MemoryItem.semantic_fingerprint,
                    or_(
                        and_(
                            MemoryItem.source_managed.is_(True),
                            MemoryItem.managed_source_kind == "topic",
                            MemoryItem.visibility == "public",
                            MemoryItem.owner_agent_id.is_(None),
                        ),
                        and_(
                            MemoryItem.source_managed.is_(False),
                            MemoryItem.node_kind == "memory",
                            MemoryItem.owner_agent_id.is_not(None),
                        ),
                    ),
                )
                .order_by(MemoryItem.id, MemoryEmbeddingChunk.chunk_index)
                .limit(MAX_INDEXED_CHUNKS + 1)
            )
        ).all()
    )
    return [
        (item_id, owner_agent_id, str(fingerprint), bytes(vector))
        for item_id, owner_agent_id, fingerprint, vector in rows
    ]


def _indexed_items(rows: list[_RawChunk]) -> tuple[list[_IndexedItem], bool]:
    truncated = len(rows) > MAX_INDEXED_CHUNKS
    rows = rows[:MAX_INDEXED_CHUNKS]
    grouped: dict[UUID, list[tuple[float, ...]]] = defaultdict(list)
    attributes: dict[UUID, tuple[int | None, str]] = {}
    for item_id, owner_agent_id, fingerprint, raw_vector in rows:
        # pgvector wire format: two int16 header fields, then network float32s.
        # Binary transport preserves the exact indexed floats and their snapshot.
        dimensions = struct.unpack_from("!H", raw_vector)[0]
        vector = _normalized(struct.unpack_from(f"!{dimensions}f", raw_vector, 4))
        if vector is None:
            continue
        resolved_item_id = item_id
        grouped[resolved_item_id].append(vector)
        attributes[resolved_item_id] = (
            owner_agent_id,
            str(fingerprint),
        )
    indexed: list[_IndexedItem] = []
    for item_id, vectors in grouped.items():
        mean = _mean_vector(vectors)
        if mean is None:
            continue
        owner_agent_id, fingerprint = attributes[item_id]
        indexed.append(
            _IndexedItem(
                item_id=item_id,
                owner_agent_id=owner_agent_id,
                vector=mean,
                fingerprint=fingerprint,
            )
        )
    return indexed, truncated


async def _canonical_memberships(
    item_ids: set[UUID],
) -> dict[UUID, set[UUID]]:
    if not item_ids:
        return {}
    rows = list(
        (
            await get_db().execute(
                select(MemoryLink.source_item_id, MemoryLink.target_item_id).where(
                    MemoryLink.relation_type == "topic_contains",
                    MemoryLink.suggested.is_(False),
                    MemoryLink.source_item_id.in_(item_ids),
                    MemoryLink.target_item_id.in_(item_ids),
                )
            )
        ).all()
    )
    memberships: dict[UUID, set[UUID]] = defaultdict(set)
    for topic_item_id, memory_item_id in rows:
        memberships[cast(UUID, topic_item_id)].add(cast(UUID, memory_item_id))
    return dict(memberships)


def _metadata(
    *, model_key: str, suggestion_kind: str, similarity: float, **extra: object
) -> dict[str, object]:
    return {
        "generated_by": GENERATED_BY,
        "suggestion_version": SUGGESTION_VERSION,
        "suggestion_kind": suggestion_kind,
        "model_key": model_key,
        "similarity": round(similarity, 8),
        **extra,
    }


def _orphan_suggestions(
    *,
    topics: Mapping[UUID, _IndexedItem],
    memories: Mapping[UUID, _IndexedItem],
    memberships: Mapping[UUID, set[UUID]],
    model_key: str,
) -> list[TopicMaintenanceSuggestion]:
    attached = {
        memory_item_id
        for members in memberships.values()
        for memory_item_id in members
    }
    scored: list[tuple[float, UUID, UUID]] = []
    for memory_id, memory in memories.items():
        if memory_id in attached:
            continue
        candidates = [
            (_similarity(memory.vector, topic.vector), topic_id)
            for topic_id, topic in topics.items()
        ]
        if not candidates:
            continue
        similarity, topic_id = max(candidates, key=lambda row: (row[0], str(row[1])))
        if similarity >= ORPHAN_MIN_SIMILARITY:
            scored.append((similarity, topic_id, memory_id))
    scored.sort(key=lambda row: (-row[0], str(row[1]), str(row[2])))
    return [
        TopicMaintenanceSuggestion(
            source_item_id=topic_id,
            target_item_id=memory_id,
            relation_type=TOPIC_MEMBERSHIP_CANDIDATE,
            confidence=_confidence(similarity),
            metadata=_metadata(
                model_key=model_key,
                suggestion_kind="orphan_membership",
                similarity=similarity,
            ),
        )
        for similarity, topic_id, memory_id in scored[:MAX_SUGGESTIONS_PER_KIND]
    ]


def _outlier_suggestions(
    *,
    topics: Mapping[UUID, _IndexedItem],
    memories: Mapping[UUID, _IndexedItem],
    memberships: Mapping[UUID, set[UUID]],
    model_key: str,
) -> list[TopicMaintenanceSuggestion]:
    scored: list[tuple[float, UUID, UUID]] = []
    for topic_id, member_ids in memberships.items():
        topic = topics.get(topic_id)
        if topic is None:
            continue
        for memory_id in member_ids:
            memory = memories.get(memory_id)
            if memory is None:
                continue
            similarity = _similarity(topic.vector, memory.vector)
            if similarity <= OUTLIER_MAX_SIMILARITY:
                scored.append((similarity, topic_id, memory_id))
    scored.sort(key=lambda row: (row[0], str(row[1]), str(row[2])))
    return [
        TopicMaintenanceSuggestion(
            source_item_id=topic_id,
            target_item_id=memory_id,
            relation_type=TOPIC_MEMBERSHIP_ANOMALY,
            confidence=_confidence((1.0 - similarity) / 2.0),
            metadata=_metadata(
                model_key=model_key,
                suggestion_kind="membership_outlier",
                similarity=similarity,
            ),
        )
        for similarity, topic_id, memory_id in scored[:MAX_SUGGESTIONS_PER_KIND]
    ]


def _merge_suggestions(
    *, topics: Mapping[UUID, _IndexedItem], model_key: str
) -> list[TopicMaintenanceSuggestion]:
    scored: list[tuple[float, UUID, UUID]] = []
    ordered = sorted(topics.items(), key=lambda row: str(row[0]))
    for (left_id, left), (right_id, right) in combinations(ordered, 2):
        similarity = _similarity(left.vector, right.vector)
        if similarity >= MERGE_MIN_SIMILARITY:
            scored.append((similarity, left_id, right_id))
    scored.sort(key=lambda row: (-row[0], str(row[1]), str(row[2])))
    return [
        TopicMaintenanceSuggestion(
            source_item_id=left_id,
            target_item_id=right_id,
            relation_type=TOPIC_MERGE_CANDIDATE,
            confidence=_confidence(similarity),
            metadata=_metadata(
                model_key=model_key,
                suggestion_kind="topic_merge",
                similarity=similarity,
            ),
        )
        for similarity, left_id, right_id in scored[:MAX_SUGGESTIONS_PER_KIND]
    ]


def _components(
    members: list[_IndexedItem],
) -> list[list[_IndexedItem]]:
    parent = list(range(len(members)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, right_index in combinations(range(len(members)), 2):
        # Connectivity is transitive: another edge inside an established
        # component cannot change the groups, so do not compare its vectors.
        if root(left_index) == root(right_index):
            continue
        if (
            _similarity(
                members[left_index].vector,
                members[right_index].vector,
            )
            >= SPLIT_CLUSTER_MIN_SIMILARITY
        ):
            union(left_index, right_index)
    grouped: dict[int, list[_IndexedItem]] = defaultdict(list)
    for index, member in enumerate(members):
        grouped[root(index)].append(member)
    return [
        sorted(component, key=lambda item: str(item.item_id))
        for component in grouped.values()
        if len(component) >= 2
    ]


def _split_suggestions(
    *,
    memories: Mapping[UUID, _IndexedItem],
    memberships: Mapping[UUID, set[UUID]],
    model_key: str,
) -> list[TopicMaintenanceSuggestion]:
    scored: list[tuple[float, UUID, list[_IndexedItem], list[_IndexedItem]]] = []
    for topic_id, member_ids in memberships.items():
        by_owner: dict[int, list[_IndexedItem]] = defaultdict(list)
        for memory_id in member_ids:
            memory = memories.get(memory_id)
            if memory is not None and memory.owner_agent_id is not None:
                by_owner[memory.owner_agent_id].append(memory)
        for owner_members in by_owner.values():
            if len(owner_members) < 4:
                continue
            components = _components(owner_members)
            for left, right in combinations(components, 2):
                cross_similarity = max(
                    _similarity(a.vector, b.vector) for a in left for b in right
                )
                if cross_similarity <= SPLIT_GROUP_MAX_SIMILARITY:
                    scored.append((cross_similarity, topic_id, left, right))
    scored.sort(
        key=lambda row: (
            row[0],
            str(row[1]),
            str(row[2][0].item_id),
            str(row[3][0].item_id),
        )
    )
    suggestions: list[TopicMaintenanceSuggestion] = []
    for similarity, topic_id, left, right in scored[:MAX_SUGGESTIONS_PER_KIND]:
        left_rep = left[0]
        right_rep = right[0]
        source, target = sorted(
            (left_rep.item_id, right_rep.item_id), key=str
        )
        suggestions.append(
            TopicMaintenanceSuggestion(
                source_item_id=source,
                target_item_id=target,
                relation_type=TOPIC_SPLIT_CANDIDATE,
                confidence=_confidence(1.0 - max(0.0, similarity)),
                metadata=_metadata(
                    model_key=model_key,
                    suggestion_kind="topic_split",
                    similarity=similarity,
                    topic_item_id=str(topic_id),
                    owner_agent_id=left_rep.owner_agent_id,
                    first_group=[str(item.item_id) for item in left[:20]],
                    second_group=[str(item.item_id) for item in right[:20]],
                ),
            )
        )
    return suggestions


def _snapshot_id(
    *,
    model_key: str,
    indexed: Iterable[_IndexedItem],
    memberships: Mapping[UUID, set[UUID]],
) -> str:
    parts = [f"model:{model_key}"]
    parts.extend(
        (
            f"item:{item.item_id}:{item.fingerprint}:"
            f"{','.join(format(value, '.8g') for value in item.vector)}"
        )
        for item in sorted(indexed, key=lambda row: str(row.item_id))
    )
    parts.extend(
        f"link:{topic_id}:{memory_id}"
        for topic_id, member_ids in sorted(
            memberships.items(), key=lambda row: str(row[0])
        )
        for memory_id in sorted(member_ids, key=str)
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _compute_plan(
    rows: list[_RawChunk],
    memberships: dict[UUID, set[UUID]],
    model_key: str,
    include_suggestions: bool,
) -> TopicMaintenancePlan | None:
    """CPU-only worker: no session, credentials, storage or external calls."""
    indexed, truncated = _indexed_items(rows)
    topics = {
        item.item_id: item for item in indexed if item.owner_agent_id is None
    }
    memories = {
        item.item_id: item for item in indexed if item.owner_agent_id is not None
    }
    if not topics:
        return None
    eligible_ids = set(topics) | set(memories)
    memberships = {
        topic_id: members & eligible_ids
        for topic_id, members in memberships.items()
        if topic_id in eligible_ids and members & eligible_ids
    }
    suggestions = [
        *_orphan_suggestions(
            topics=topics,
            memories=memories,
            memberships=memberships,
            model_key=model_key,
        ),
        *_outlier_suggestions(
            topics=topics,
            memories=memories,
            memberships=memberships,
            model_key=model_key,
        ),
        *_merge_suggestions(topics=topics, model_key=model_key),
        *_split_suggestions(
            memories=memories,
            memberships=memberships,
            model_key=model_key,
        ),
    ] if include_suggestions else []
    return TopicMaintenancePlan(
        snapshot_id=_snapshot_id(
            model_key=model_key,
            indexed=indexed,
            memberships=memberships,
        ),
        model_key=model_key,
        suggestions=tuple(suggestions),
        topic_count=len(topics),
        memory_count=len(memories),
        truncated=truncated,
    )


async def _build_plan(*, include_suggestions: bool) -> TopicMaintenancePlan | None:
    global _compute_lock
    if _compute_lock is None:
        _compute_lock = asyncio.Lock()
    # Serialize before loading vectors: concurrent requests cannot queue copies
    # of the whole index in RAM or spawn additional CPU workers.
    async with _compute_lock:
        return await _build_plan_locked(include_suggestions=include_suggestions)


async def _build_plan_locked(*, include_suggestions: bool) -> TopicMaintenancePlan | None:
    global _compute_pool
    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return None
    except Exception:
        logger.exception("Topic maintenance model resolution failed")
        await get_db().rollback()
        return None
    rows = await _indexed_rows(model.key)
    if not any(owner_id is None for _, owner_id, _, _ in rows[:MAX_INDEXED_CHUNKS]):
        return None
    memberships = await _canonical_memberships(
        {item_id for item_id, _, _, _ in rows[:MAX_INDEXED_CHUNKS]}
    )
    if _compute_pool is None:
        _compute_pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_lower_compute_priority,
        )
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _compute_pool, _compute_plan, rows, memberships, model.key, include_suggestions
        )
    except (asyncio.CancelledError, BrokenProcessPool):
        stop_topic_maintenance()
        raise


async def build_topic_maintenance_plan() -> TopicMaintenancePlan | None:
    """Compute suggestions in one lower-priority process, leaving audio/HTTP free."""
    return await _build_plan(include_suggestions=True)


async def topic_maintenance_snapshot_id() -> str | None:
    plan = await _build_plan(include_suggestions=False)
    return plan.snapshot_id if plan is not None else None


async def topic_maintenance_available() -> bool:
    """Cheap availability guard; snapshot generation remains in claim_one."""

    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return False
    except Exception:
        logger.exception("Topic maintenance availability check failed")
        await get_db().rollback()
        return False
    topic_chunk = await get_db().scalar(
        select(MemoryEmbeddingChunk.id)
        .join(MemoryItem, MemoryItem.id == MemoryEmbeddingChunk.item_id)
        .where(
            MemoryEmbeddingChunk.model_key == model.key,
            MemoryEmbeddingChunk.source_fingerprint
            == MemoryItem.semantic_fingerprint,
            MemoryItem.source_managed.is_(True),
            MemoryItem.managed_source_kind == "topic",
            MemoryItem.visibility == "public",
            MemoryItem.owner_agent_id.is_(None),
        )
        .limit(1)
    )
    return topic_chunk is not None


async def apply_topic_maintenance_plan(
    plan: TopicMaintenancePlan,
) -> TopicMaintenanceResult:
    """Replace only generated suggestions; canonical graph edges stay immutable."""

    db = get_db()
    desired = {
        (item.source_item_id, item.target_item_id, item.relation_type): item
        for item in plan.suggestions
        if item.source_item_id != item.target_item_id
        and item.relation_type in SUGGESTED_RELATIONS
    }
    existing = list(
        (
            await db.scalars(
                select(MemoryLink).where(
                    MemoryLink.suggested.is_(True),
                    MemoryLink.relation_type.in_(SUGGESTED_RELATIONS),
                    MemoryLink.metadata_["generated_by"].as_string()
                    == GENERATED_BY,
                )
            )
        ).all()
    )
    existing_by_key = {
        (link.source_item_id, link.target_item_id, link.relation_type): link
        for link in existing
    }
    removed = 0
    for key, link in existing_by_key.items():
        if key not in desired:
            await db.delete(link)
            removed += 1

    created = 0
    updated = 0
    for key, suggestion in desired.items():
        link = existing_by_key.get(key)
        if link is None:
            conflicting = await db.scalar(
                select(MemoryLink).where(
                    MemoryLink.source_item_id == suggestion.source_item_id,
                    MemoryLink.target_item_id == suggestion.target_item_id,
                    MemoryLink.relation_type == suggestion.relation_type,
                )
            )
            if conflicting is not None:
                continue
            db.add(
                MemoryLink(
                    source_item_id=suggestion.source_item_id,
                    target_item_id=suggestion.target_item_id,
                    relation_type=suggestion.relation_type,
                    confidence=suggestion.confidence,
                    suggested=True,
                    created_by_agent_id=None,
                    projection_key="memory.topic_maintenance",
                    projection_version=SUGGESTION_VERSION,
                    metadata_=dict(suggestion.metadata),
                )
            )
            created += 1
            continue
        metadata = dict(suggestion.metadata)
        if link.confidence != suggestion.confidence or link.metadata_ != metadata:
            link.confidence = suggestion.confidence
            link.metadata_ = metadata
            updated += 1
    await db.commit()
    return TopicMaintenanceResult(
        active=len(desired),
        created=created,
        updated=updated,
        removed=removed,
    )


def plan_to_payload(plan: TopicMaintenancePlan) -> dict[str, Any]:
    return {
        "snapshot_id": plan.snapshot_id,
        "model_key": plan.model_key,
        "topic_count": plan.topic_count,
        "memory_count": plan.memory_count,
        "truncated": plan.truncated,
        "suggestions": [
            {
                "source_item_id": str(suggestion.source_item_id),
                "target_item_id": str(suggestion.target_item_id),
                "relation_type": suggestion.relation_type,
                "confidence": suggestion.confidence,
                "metadata": suggestion.metadata,
            }
            for suggestion in plan.suggestions
        ],
    }


def plan_from_payload(payload: Mapping[str, Any]) -> TopicMaintenancePlan:
    raw_suggestions = payload.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise ValueError("Topic maintenance payload requires suggestions.")
    suggestions: list[TopicMaintenanceSuggestion] = []
    for raw in cast(list[object], raw_suggestions):
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid Topic maintenance suggestion payload.")
        raw_mapping = cast(Mapping[object, object], raw)
        metadata = raw_mapping.get("metadata")
        metadata_mapping: Mapping[object, object]
        if isinstance(metadata, Mapping):
            metadata_mapping = cast(Mapping[object, object], metadata)
        else:
            metadata_mapping = cast(Mapping[object, object], {})
        confidence_value = raw_mapping["confidence"]
        if not isinstance(confidence_value, (int, float, str)):
            raise ValueError("Invalid Topic maintenance confidence.")
        suggestions.append(
            TopicMaintenanceSuggestion(
                source_item_id=UUID(str(raw_mapping["source_item_id"])),
                target_item_id=UUID(str(raw_mapping["target_item_id"])),
                relation_type=str(raw_mapping["relation_type"]),
                confidence=float(confidence_value),
                metadata={
                    str(key): value for key, value in metadata_mapping.items()
                },
            )
        )
    return TopicMaintenancePlan(
        snapshot_id=str(payload["snapshot_id"]),
        model_key=str(payload["model_key"]),
        suggestions=tuple(suggestions),
        topic_count=int(payload.get("topic_count") or 0),
        memory_count=int(payload.get("memory_count") or 0),
        truncated=bool(payload.get("truncated")),
    )


__all__ = [
    "GENERATED_BY",
    "SUGGESTED_RELATIONS",
    "TOPIC_MEMBERSHIP_ANOMALY",
    "TOPIC_MEMBERSHIP_CANDIDATE",
    "TOPIC_MERGE_CANDIDATE",
    "TOPIC_SPLIT_CANDIDATE",
    "apply_topic_maintenance_plan",
    "build_topic_maintenance_plan",
    "plan_from_payload",
    "plan_to_payload",
    "topic_maintenance_snapshot_id",
    "topic_maintenance_available",
]
