"""Lightweight deterministic memory-maintenance detection and actions.

This module never calls an LLM. Pair detection only reads the current embedding
index, while contradiction classification and aging are deterministic.
"""

from __future__ import annotations


import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

from sqlalchemy import Float, and_, delete, func, or_, select, update
from sqlalchemy.orm import aliased, joinedload
from sqlalchemy.sql import cast as sql_cast
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.params import runtime_settings
from core.user import user_service

from . import service
from .embedding import MemoryEmbeddingNotConfiguredError, resolve_embedding_model
from .models import MemoryContactItem, MemoryEmbeddingChunk, MemoryFinding, MemoryItem, MemoryLink, MemorySource, MemoryTopicContactItem, MemoryUsage
from app.document import Document, DocumentAttachment
from .schemas import MemoryFindingPublic


_WORD_RE = re.compile(r"[^\W\d_][\w'-]{2,}", re.UNICODE)
_CORRECTION_MARKERS = (
    "correction",
    "contrairement",
    "désormais",
    "dorénavant",
    "en fait",
    "n'est plus",
    "ne doit plus",
    "ne sont plus",
    "remplace",
    "actually",
    "contrary",
    "from now on",
    "no longer",
    "instead of",
    "replaces",
)
_NEGATION_MARKERS = (
    " ne ",
    " n'",
    " pas ",
    " plus ",
    " jamais ",
    " no ",
    " not ",
    "n't ",
    " never ",
)


def _finding_public(finding: MemoryFinding) -> MemoryFindingPublic:
    return MemoryFindingPublic.model_validate(
        {
            "id": finding.id,
            "kind": finding.kind,
            "primary_item_id": finding.primary_item_id,
            "related_item_id": finding.related_item_id,
            "primary_revision": finding.primary_revision,
            "related_revision": finding.related_revision,
            "score": finding.score,
            "threshold": finding.threshold,
            "proposed_action": finding.proposed_action,
            "status": finding.status,
            "details": dict(finding.details),
            "detected_at": finding.detected_at,
            "resolved_at": finding.resolved_at,
        }
    )


def _fingerprint(
    kind: str,
    primary_item_id: UUID,
    primary_revision: int,
    related_item_id: UUID | None = None,
    related_revision: int | None = None,
) -> str:
    pair = [(str(primary_item_id), primary_revision)]
    if related_item_id is not None and related_revision is not None:
        pair.append((str(related_item_id), related_revision))
        pair.sort()
    raw = ":".join([kind, *(f"{item_id}@{revision}" for item_id, revision in pair)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _meaningful_at(item: MemoryItem) -> datetime:
    return item.updated_at or item.created_at


def _source_backed(item: MemoryItem) -> bool:
    return item.source_managed or item.node_kind in {"document", "file", "attachment", "directory"}


def _source_contains_fact(source: MemoryItem, memory: MemoryItem) -> bool:
    # Cross-domain absorption requires literal complete evidence, not just a high
    # embedding score. Never collapse independent authoritative resources here.
    fact = " ".join(memory.search_text.casefold().split())
    return bool(fact) and fact in " ".join(source.search_text.casefold().split())


def _duplicate_canonical(first: MemoryItem, second: MemoryItem) -> MemoryItem:
    return min((first, second), key=lambda item: (not _source_backed(item), _meaningful_at(item), str(item.id)))


async def file_pair_compatible(first: MemoryItem, second: MemoryItem) -> bool:
    """Byte identity cannot widen ownership or a document's live ACL boundary."""
    if (first.owner_agent_id, first.owner_user_id, first.node_kind, first.visibility,
        first.valid_from, first.valid_until) != (
        second.owner_agent_id, second.owner_user_id, second.node_kind, second.visibility,
        second.valid_from, second.valid_until):
        return False
    db = get_db()
    if first.node_kind == "attachment":
        parents = [set(await db.scalars(select(DocumentAttachment.document_id).where(
            DocumentAttachment.memory_item_id == item.id,
        ))) for item in (first, second)]
        if not parents[0] or parents[0] != parents[1]:
            return False
    # Documentary references have independent lifetimes and are never merged by
    # the personal-memory maintenance engine.
    return first.node_kind != "document"


async def _file_candidates(item: MemoryItem) -> list[tuple[MemoryItem, float]]:
    rows = await get_db().scalars(select(MemoryItem).where(
        MemoryItem.id != item.id,
        MemoryItem.file_sha256 == item.file_sha256,
        MemoryItem.node_kind == item.node_kind,
        MemoryItem.owner_agent_id.is_not_distinct_from(item.owner_agent_id),
        MemoryItem.owner_user_id.is_not_distinct_from(item.owner_user_id),
    ).order_by(MemoryItem.id).limit(100))
    return [(candidate, 1.0) for candidate in rows
            if await file_pair_compatible(item, candidate)]


def _normalized_text(item: MemoryItem) -> str:
    return " ".join((item.title, item.search_text)).casefold()


def _has_correction_marker(item: MemoryItem) -> bool:
    text = _normalized_text(item)
    return any(marker in text for marker in _CORRECTION_MARKERS)


def _contradiction_signal(first: MemoryItem, second: MemoryItem) -> str | None:
    """Return a conservative explainable signal, or no contradiction."""

    first_text = f" {_normalized_text(first)} "
    second_text = f" {_normalized_text(second)} "
    first_correction = next(
        (marker for marker in _CORRECTION_MARKERS if marker in first_text), None
    )
    second_correction = next(
        (marker for marker in _CORRECTION_MARKERS if marker in second_text), None
    )
    first_negated = any(marker in first_text for marker in _NEGATION_MARKERS)
    second_negated = any(marker in second_text for marker in _NEGATION_MARKERS)
    if not first_correction and not second_correction and first_negated == second_negated:
        return None
    first_words = set(_WORD_RE.findall(first_text))
    second_words = set(_WORD_RE.findall(second_text))
    shorter = min(len(first_words), len(second_words))
    if shorter == 0 or len(first_words & second_words) / shorter < 0.45:
        return None
    if first_correction:
        return f"explicit_marker:{first_correction}"
    if second_correction:
        return f"explicit_marker:{second_correction}"
    return "opposite_negation"


async def _scope_signature(item_id: UUID) -> tuple[UUID | None, tuple[UUID, ...]]:
    direct = await get_db().scalar(
        select(MemoryContactItem.contact_item_id).where(
            MemoryContactItem.item_id == item_id
        )
    )
    topics = tuple(
        sorted(
            (
                await get_db().scalars(
                    select(MemoryTopicContactItem.scope_id).where(
                        MemoryTopicContactItem.item_id == item_id
                    )
                )
            ).all(),
            key=str,
        )
    )
    return direct, topics


async def _indexed_candidates(
    item: MemoryItem, *, minimum_similarity: float, limit: int = 10
) -> list[tuple[MemoryItem, float]]:
    try:
        model = await resolve_embedding_model()
    except MemoryEmbeddingNotConfiguredError:
        return []
    source_chunk = aliased(MemoryEmbeddingChunk)
    candidate_chunk = aliased(MemoryEmbeddingChunk)
    candidate_item = aliased(MemoryItem)
    similarity = cast(
        ColumnElement[float],
        1.0
        - sql_cast(
            source_chunk.embedding.op("<=>")(candidate_chunk.embedding), Float
        ),
    )
    scores = (
        select(
            candidate_item.id.label("item_id"),
            func.max(similarity).label("similarity"),
        )
        .select_from(source_chunk)
        .join(
            candidate_chunk,
            and_(
                candidate_chunk.model_key == source_chunk.model_key,
                candidate_chunk.dimensions == source_chunk.dimensions,
                candidate_chunk.item_id != source_chunk.item_id,
            ),
        )
        .join(candidate_item, candidate_item.id == candidate_chunk.item_id)
        .where(
            source_chunk.item_id == item.id,
            source_chunk.model_key == model.key,
            source_chunk.source_fingerprint == item.semantic_fingerprint,
            candidate_chunk.source_fingerprint == candidate_item.semantic_fingerprint,
            candidate_item.owner_agent_id == item.owner_agent_id,
        )
        .group_by(candidate_item.id)
        .subquery()
    )
    rows = (
        await get_db().execute(
            select(MemoryItem, scores.c.similarity)
            .options(joinedload(MemoryItem.document))
            .join(scores, scores.c.item_id == MemoryItem.id)
            .where(scores.c.similarity >= minimum_similarity)
            .order_by(scores.c.similarity.desc(), MemoryItem.id)
            .limit(limit)
        )
    ).all()
    return [(candidate, float(score)) for candidate, score in rows]


async def _store_finding(
    *,
    kind: str,
    primary: MemoryItem,
    related: MemoryItem | None,
    score: float | None,
    threshold: float,
    proposed_action: str,
    details: dict[str, object],
    reuse_pending: bool = False,
) -> MemoryFinding | None:
    """Create a finding, or reuse its pending row for automatic execution."""

    fingerprint = _fingerprint(
        kind,
        primary.id,
        primary.revision,
        related.id if related is not None else None,
        related.revision if related is not None else None,
    )
    existing = await get_db().scalar(
        select(MemoryFinding).where(MemoryFinding.fingerprint == fingerprint)
    )
    if existing is not None:
        return existing if reuse_pending and existing.status == "pending" else None
    finding = MemoryFinding(
        kind=kind,
        primary_item_id=primary.id,
        related_item_id=related.id if related is not None else None,
        primary_revision=primary.revision,
        related_revision=related.revision if related is not None else None,
        score=score,
        threshold=threshold,
        proposed_action=proposed_action,
        fingerprint=fingerprint,
        details=details,
    )
    get_db().add(finding)
    await get_db().flush()
    return finding


async def detect_for_item(item_id: UUID, *, manual: bool = False) -> list[UUID]:
    """Detect current findings for one item without invoking a generative model."""

    item = await get_db().get(MemoryItem, item_id)
    if (
        item is None
        or item.deleted_at is not None
        or not ((item.node_kind == "memory" and not item.source_managed and item.owner_agent_id is not None)
                or (item.node_kind in ("file", "attachment") and item.file_sha256 is not None))
    ):
        return []
    actionable: list[MemoryFinding] = []
    aging_mode = "manual" if manual else runtime_settings.MEMORY_AGING_MODE
    aging_days = runtime_settings.MEMORY_AGING_AFTER_DAYS
    if (
        item.node_kind == "memory"
        and aging_mode != "off"
        and item.old_at is None
        and _meaningful_at(item)
        <= datetime.now(timezone.utc) - timedelta(days=aging_days)
    ):
        finding = await _store_finding(
            kind="aging",
            primary=item,
            related=None,
            score=None,
            threshold=float(aging_days),
            proposed_action="mark_old",
            details={"meaningful_at": _meaningful_at(item).isoformat()},
            reuse_pending=aging_mode == "automatic",
        )
        if finding is not None:
            actionable.append(finding)

    contradiction_mode = "manual" if manual else runtime_settings.MEMORY_CONTRADICTION_MODE
    minimum = runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
    item_scope = await _scope_signature(item.id)
    candidates = (await _file_candidates(item) if item.file_sha256 is not None
                  else await _indexed_candidates(item, minimum_similarity=minimum))
    for candidate, similarity in candidates:
        item_fact = item.metadata_.get("atomic_fact")
        candidate_fact = candidate.metadata_.get("atomic_fact")
        if item_fact is not None and candidate_fact is not None and item_fact != candidate_fact:
            # Equal labels or embeddings never make two subjects/properties/values
            # identical. Their typed assertion is the identity boundary.
            continue
        backed = _source_backed(candidate) and not _source_backed(item)
        if item.file_sha256 is None and not backed and str(candidate.id) < str(item.id):
            continue
        if backed and not _source_contains_fact(candidate, item):
            continue
        if not backed and await _scope_signature(candidate.id) != item_scope:
            continue
        if candidate.temporal != item.temporal:
            continue
        signal = None if item.file_sha256 is not None or backed else _contradiction_signal(item, candidate)
        if (
            contradiction_mode != "off"
            and signal is not None
            and similarity
            >= runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
        ):
            item_corrects = _has_correction_marker(item)
            candidate_corrects = _has_correction_marker(candidate)
            canonical = (
                item
                if item_corrects and not candidate_corrects
                else candidate
                if candidate_corrects and not item_corrects
                else max((item, candidate), key=_meaningful_at)
            )
            finding = await _store_finding(
                kind="contradiction",
                primary=item,
                related=candidate,
                score=similarity,
                threshold=runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
                proposed_action="keep_newest",
                details={
                    "signal": signal,
                    "proposed_canonical_item_id": str(canonical.id),
                },
                reuse_pending=contradiction_mode == "automatic",
            )
        elif similarity >= runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD:
            canonical = (min((item, candidate), key=lambda node: (node.created_at, str(node.id)))
                         if item.file_sha256 else _duplicate_canonical(item, candidate))
            finding = await _store_finding(
                kind="duplicate",
                primary=item,
                related=candidate,
                score=similarity,
                threshold=runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
                proposed_action="merge_keep_oldest",
                details={"proposed_canonical_item_id": str(canonical.id),
                         **({"file_sha256": item.file_sha256} if item.file_sha256 else {})},
                # A manual inspection only proposes findings; Dream applies them.
                reuse_pending=not manual,
            )
        else:
            finding = None
        if finding is not None:
            actionable.append(finding)
    await get_db().commit()
    for finding in actionable:
        mode = {
            "duplicate": "manual" if manual else "automatic",
            "contradiction": contradiction_mode,
            "aging": aging_mode,
        }[finding.kind]
        if mode == "automatic":
            current_status = await get_db().scalar(
                select(MemoryFinding.status).where(MemoryFinding.id == finding.id)
            )
            if current_status == "pending":
                await apply_finding(finding.id, canonical_item_id=None)
    return [finding.id for finding in actionable]


async def _finding_revisions_are_current(finding: MemoryFinding) -> bool:
    primary_revision = await get_db().scalar(
        select(MemoryItem.revision).where(
            MemoryItem.id == finding.primary_item_id,
            MemoryItem.deleted_at.is_(None),
        )
    )
    if primary_revision != finding.primary_revision:
        return False
    if finding.related_item_id is None:
        return True
    related_revision = await get_db().scalar(
        select(MemoryItem.revision).where(
            MemoryItem.id == finding.related_item_id,
            MemoryItem.deleted_at.is_(None),
        )
    )
    return related_revision == finding.related_revision


async def _aging_finding_matches(
    finding: MemoryFinding, threshold: float, *, now: datetime
) -> bool:
    item = await get_db().get(MemoryItem, finding.primary_item_id)
    return bool(
        item is not None
        and item.deleted_at is None
        and item.old_at is None
        and _meaningful_at(item) <= now - timedelta(days=threshold)
    )


async def reconcile_policy_findings() -> int:
    """Align persisted threshold findings with the current runtime policy.

    Raising a threshold obsoletes false positives immediately. A finding made
    obsolete for that reason can become pending again if the threshold is later
    lowered, provided the exact item revisions still exist.
    """

    policies: dict[str, tuple[float, str]] = {
        "duplicate": (
            runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
            "automatic",
        ),
        "contradiction": (
            runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
            runtime_settings.MEMORY_CONTRADICTION_MODE,
        ),
        "aging": (
            float(runtime_settings.MEMORY_AGING_AFTER_DAYS),
            runtime_settings.MEMORY_AGING_MODE,
        ),
    }
    rows = (
        await get_db().scalars(
            select(MemoryFinding).where(
                MemoryFinding.kind.in_(tuple(policies)),
                MemoryFinding.status.in_(("pending", "obsolete")),
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    changed = 0
    for finding in rows:
        threshold, mode = policies[finding.kind]
        details = dict(finding.details)
        obsolete_for_threshold = details.get("obsolete_reason") == "policy_threshold"
        matches = (
            finding.score is not None and finding.score >= threshold
            if finding.kind != "aging"
            else await _aging_finding_matches(finding, threshold, now=now)
        )
        row_changed = False
        if finding.status == "pending" and not matches:
            finding.status = "obsolete"
            finding.resolved_at = now
            details["obsolete_reason"] = "policy_threshold"
            finding.details = details
            row_changed = True
        elif (
            finding.status == "obsolete"
            and obsolete_for_threshold
            and mode != "off"
            and matches
            and await _finding_revisions_are_current(finding)
        ):
            finding.status = "pending"
            finding.resolved_at = None
            details.pop("obsolete_reason", None)
            finding.details = details
            row_changed = True
        if finding.threshold != threshold:
            finding.threshold = threshold
            row_changed = True
        changed += int(row_changed)
    if changed:
        await get_db().commit()
    return changed


async def list_findings(
    *,
    agent_id: int,
    item_id: UUID | None = None,
    status: str = "pending",
    limit: int = 500,
) -> list[MemoryFindingPublic]:
    await reconcile_policy_findings()
    query = (
        select(MemoryFinding)
        .join(MemoryItem, MemoryItem.id == MemoryFinding.primary_item_id)
        .where(
            MemoryItem.owner_agent_id == agent_id,
            MemoryFinding.status == status,
        )
        .order_by(MemoryFinding.detected_at.desc(), MemoryFinding.id)
        .limit(limit)
    )
    if item_id is not None:
        query = query.where(
            or_(
                MemoryFinding.primary_item_id == item_id,
                MemoryFinding.related_item_id == item_id,
            )
        )
    return [_finding_public(row) for row in (await get_db().scalars(query)).all()]


async def get_finding_agent_id(finding_id: UUID) -> int | None:
    """Resolve the owner Agent behind one maintenance finding."""

    return await get_db().scalar(
        select(MemoryItem.owner_agent_id)
        .join(MemoryFinding, MemoryFinding.primary_item_id == MemoryItem.id)
        .where(MemoryFinding.id == finding_id)
    )


async def _invalidate_item_findings(item_id: UUID, *, except_id: UUID) -> None:
    await get_db().execute(
        update(MemoryFinding)
        .where(
            MemoryFinding.id != except_id,
            MemoryFinding.status == "pending",
            or_(
                MemoryFinding.primary_item_id == item_id,
                MemoryFinding.related_item_id == item_id,
            ),
        )
        .values(status="obsolete", resolved_at=datetime.now(timezone.utc))
    )


async def _merge_items(canonical: MemoryItem, duplicate: MemoryItem, finding_id: UUID) -> None:
    source_absorption = _source_backed(canonical) and not _source_backed(duplicate)
    if canonical.node_kind == "document" and (canonical.document is None or canonical.document.deleted_at is not None):
        raise service.MemoryConflictError("The canonical Document is no longer available.")
    if (canonical.metadata_.get("atomic_fact") is not None and duplicate.metadata_.get("atomic_fact") is not None
            and canonical.metadata_["atomic_fact"] != duplicate.metadata_["atomic_fact"]):
        raise service.MemoryConflictError("Different atomic assertions cannot be merged as identical memories.")
    if source_absorption and not _source_contains_fact(canonical, duplicate):
        raise service.MemoryConflictError("The source no longer contains the complete duplicate fact.")
    if not source_absorption and (canonical.node_kind == "document" or duplicate.node_kind == "document"):
        raise service.MemoryConflictError("Document memories cannot be merged independently of their documents.")
    if _source_backed(duplicate) and not (canonical.file_sha256 and duplicate.file_sha256):
        raise service.MemoryConflictError("Source-backed resources must survive personal-memory deduplication.")
    if canonical.id == duplicate.id:
        raise service.MemoryConflictError("A memory cannot be merged into itself.")
    if canonical.owner_agent_id != duplicate.owner_agent_id:
        raise service.MemoryConflictError("Memories owned by different agents cannot be merged.")
    file_merge = not source_absorption and (canonical.file_sha256 is not None or duplicate.file_sha256 is not None)
    if file_merge and (canonical.file_sha256 != duplicate.file_sha256
                       or not await file_pair_compatible(canonical, duplicate)):
        raise service.MemoryConflictError("File identities or access scopes changed before merging.")
    if canonical.temporal != duplicate.temporal:
        raise service.MemoryConflictError("Memories with different temporal anchors cannot be merged.")
    if not source_absorption and await _scope_signature(canonical.id) != await _scope_signature(duplicate.id):
        raise service.MemoryConflictError("Memory scopes changed and are no longer compatible.")
    db = get_db()
    existing_sources = {
        (row.source_kind, row.source_ref)
        for row in (
            await db.scalars(select(MemorySource).where(MemorySource.item_id == canonical.id))
        ).all()
    }
    for row in (
        await db.scalars(select(MemorySource).where(MemorySource.item_id == duplicate.id))
    ).all():
        if source_absorption:
            # Keep private provenance in the owner-bound finding, never append it
            # to a potentially shared Document or File's exposed source list.
            finding = await db.get(MemoryFinding, finding_id)
            assert finding is not None
            provenance = list(finding.details.get("absorbed_sources", []))
            provenance.append({"source_kind": row.source_kind, "source_ref": row.source_ref})
            finding.details = {**finding.details, "absorbed_sources": provenance}
            continue
        if (row.source_kind, row.source_ref) in existing_sources:
            await db.delete(row)
        else:
            row.item_id = canonical.id
            existing_sources.add((row.source_kind, row.source_ref))

    await db.execute(delete(MemoryContactItem).where(MemoryContactItem.item_id == duplicate.id))
    await db.execute(
        delete(MemoryTopicContactItem).where(MemoryTopicContactItem.item_id == duplicate.id)
    )
    for usage in await db.scalars(select(MemoryUsage).where(MemoryUsage.item_id == duplicate.id)):
        repeated = None if usage.task_id is None else await db.scalar(select(MemoryUsage.id).where(
            MemoryUsage.item_id == canonical.id, MemoryUsage.agent_id == usage.agent_id,
            MemoryUsage.task_id == usage.task_id, MemoryUsage.access_kind == usage.access_kind,
        ))
        if repeated is not None:
            await db.delete(usage)
        else:
            usage.item_id = canonical.id
    canonical.access_count += duplicate.access_count
    accessed = [value for value in (canonical.last_accessed_at, duplicate.last_accessed_at) if value is not None]
    canonical.last_accessed_at = max(accessed) if accessed else None
    if file_merge:
        from .catalogue_projection import merge_file_nodes
        from .semantic_index import stage_embedding_refresh, delete_item_embeddings

        await db.execute(update(DocumentAttachment).where(
            DocumentAttachment.memory_item_id == duplicate.id,
        ).values(memory_item_id=canonical.id))
        await merge_file_nodes(canonical, duplicate)
        stage_embedding_refresh(canonical)
        await delete_item_embeddings(duplicate.id)
        await _invalidate_item_findings(duplicate.id, except_id=finding_id)
        await _invalidate_item_findings(canonical.id, except_id=finding_id)
        await db.flush()
        return
    links: list[MemoryLink] = list((
        await db.scalars(
            select(MemoryLink).where(
                or_(
                    MemoryLink.source_item_id == duplicate.id,
                    MemoryLink.target_item_id == duplicate.id,
                )
            )
        )
    ).all())
    if source_absorption and links:
        # Link metadata and even a relation between two readable resources can
        # disclose private conversation evidence. A shared canonical source must
        # not inherit the ordinary copy's graph provenance. Keep it owner-bound.
        finding = await db.get(MemoryFinding, finding_id)
        assert finding is not None
        finding.details = {**finding.details, "absorbed_links": [
            {"source_item_id": str(link.source_item_id), "target_item_id": str(link.target_item_id),
             "relation_type": link.relation_type, "metadata": dict(link.metadata_)}
            for link in links
        ]}
        for link in links:
            await db.delete(link)
        links = []
    for link in links:
        source_id = canonical.id if link.source_item_id == duplicate.id else link.source_item_id
        target_id = canonical.id if link.target_item_id == duplicate.id else link.target_item_id
        if source_id == target_id:
            await db.delete(link)
            continue
        exists_link = await db.scalar(
            select(MemoryLink.id).where(
                MemoryLink.id != link.id,
                MemoryLink.source_item_id == source_id,
                MemoryLink.target_item_id == target_id,
                MemoryLink.relation_type == link.relation_type,
            )
        )
        if exists_link is not None:
            await db.delete(link)
        else:
            link.source_item_id = source_id
            link.target_item_id = target_id
    if not source_absorption:
        canonical.old_at = None
        canonical.old_reason = None
    await _invalidate_item_findings(duplicate.id, except_id=finding_id)
    await _invalidate_item_findings(canonical.id, except_id=finding_id)
    await db.commit()
    await service.forget_merged_item(duplicate.id)


async def apply_finding(
    finding_id: UUID, *, canonical_item_id: UUID | None
) -> MemoryFindingPublic:
    finding = await get_db().scalar(
        select(MemoryFinding).where(MemoryFinding.id == finding_id).with_for_update()
    )
    if finding is None:
        raise service.MemoryNotFoundError("Memory finding not found.")
    if finding.status != "pending":
        raise service.MemoryConflictError("This finding is no longer pending.")
    identities = [finding.primary_item_id]
    if finding.related_item_id is not None:
        identities.append(finding.related_item_id)
    # Source owners lock Document before refreshing its Memory reference. Keep
    # that order and hold the source revision through duplicate retirement.
    document_ids = list(await get_db().scalars(select(MemoryItem.id).where(
        MemoryItem.id.in_(identities), MemoryItem.node_kind == "document")))
    if document_ids:
        await get_db().scalars(select(Document).where(Document.id.in_(document_ids))
            .order_by(Document.id).with_for_update().execution_options(populate_existing=True))
    locked = {item.id: item for item in await get_db().scalars(select(MemoryItem).where(
        MemoryItem.id.in_(identities),
    ).order_by(MemoryItem.id).with_for_update().execution_options(populate_existing=True))}
    primary = locked.get(finding.primary_item_id)
    related = locked.get(finding.related_item_id) if finding.related_item_id is not None else None
    if (
        primary is None
        or primary.revision != finding.primary_revision
        or (
            finding.related_item_id is not None
            and (
                related is None or related.revision != finding.related_revision
            )
        )
    ):
        finding.status = "obsolete"
        finding.resolved_at = datetime.now(timezone.utc)
        await get_db().commit()
        return _finding_public(finding)
    from .catalogue_projection import catalogue_projection_write

    async with catalogue_projection_write():
        if finding.kind == "aging":
            primary.old_at = datetime.now(timezone.utc)
            primary.old_reason = f"age:{int(finding.threshold)}d"
        else:
            assert related is not None
            proposed_raw = finding.details.get("proposed_canonical_item_id")
            proposed_id = UUID(str(proposed_raw)) if proposed_raw else primary.id
            selected_id = canonical_item_id or proposed_id
            if selected_id not in {primary.id, related.id}:
                raise service.MemoryConflictError("The canonical memory must belong to the finding.")
            canonical = primary if selected_id == primary.id else related
            duplicate = related if selected_id == primary.id else primary
            if finding.kind == "duplicate" and _source_backed(canonical) != _source_backed(duplicate):
                canonical = _duplicate_canonical(primary, related)
                duplicate = related if canonical.id == primary.id else primary
                finding.details = {**finding.details, "proposed_canonical_item_id": str(canonical.id),
                                   "canonical_priority": "source_backed"}
            await _merge_items(canonical, duplicate, finding.id)
        finding.status = "applied"
        finding.resolved_at = datetime.now(timezone.utc)
        finding.resolved_by = user_service.get_current_user_id()
        await get_db().commit()
    return _finding_public(finding)


async def dismiss_finding(finding_id: UUID) -> MemoryFindingPublic:
    finding = await get_db().scalar(
        select(MemoryFinding).where(MemoryFinding.id == finding_id).with_for_update()
    )
    if finding is None:
        raise service.MemoryNotFoundError("Memory finding not found.")
    if finding.status != "pending":
        raise service.MemoryConflictError("This finding is no longer pending.")
    finding.status = "dismissed"
    finding.resolved_at = datetime.now(timezone.utc)
    finding.resolved_by = user_service.get_current_user_id()
    await get_db().commit()
    return _finding_public(finding)


async def clear_old_flag(item_id: UUID) -> None:
    """Clear age state and obsolete its pending age finding after meaningful edits."""

    await get_db().execute(
        update(MemoryFinding)
        .where(
            MemoryFinding.primary_item_id == item_id,
            MemoryFinding.kind == "aging",
            MemoryFinding.status == "pending",
        )
        .values(status="obsolete", resolved_at=datetime.now(timezone.utc))
    )


__all__ = [
    "apply_finding",
    "clear_old_flag",
    "get_finding_agent_id",
    "detect_for_item",
    "dismiss_finding",
    "list_findings",
    "reconcile_policy_findings",
]
