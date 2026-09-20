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
from sqlalchemy.orm import aliased
from sqlalchemy.sql import cast as sql_cast
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.params import runtime_settings
from core.user import user_service

from . import service
from .embedding import MemoryEmbeddingNotConfiguredError, resolve_embedding_model
from .models import (
    MemoryContactItem,
    MemoryEmbeddingChunk,
    MemoryFinding,
    MemoryItem,
    MemoryItemGrant,
    MemoryLink,
    MemorySource,
    MemoryTopicContactItem,
)
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
            candidate_item.node_kind == "memory",
            candidate_item.source_managed.is_(False),
        )
        .group_by(candidate_item.id)
        .subquery()
    )
    rows = (
        await get_db().execute(
            select(MemoryItem, scores.c.similarity)
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


async def detect_for_item(item_id: UUID) -> list[UUID]:
    """Detect current findings for one item without invoking a generative model."""

    item = await get_db().get(MemoryItem, item_id)
    if (
        item is None
        or item.deleted_at is not None
        or item.owner_agent_id is None
        or item.node_kind != "memory"
        or item.source_managed
    ):
        return []
    actionable: list[MemoryFinding] = []
    aging_mode = runtime_settings.MEMORY_AGING_MODE
    aging_days = runtime_settings.MEMORY_AGING_AFTER_DAYS
    if (
        aging_mode != "off"
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

    duplicate_mode = runtime_settings.MEMORY_DUPLICATE_MODE
    contradiction_mode = runtime_settings.MEMORY_CONTRADICTION_MODE
    if duplicate_mode != "off" or contradiction_mode != "off":
        minimum = min(
            runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
            if duplicate_mode != "off"
            else 1.0,
            runtime_settings.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD
            if contradiction_mode != "off"
            else 1.0,
        )
        item_scope = await _scope_signature(item.id)
        for candidate, similarity in await _indexed_candidates(
            item, minimum_similarity=minimum
        ):
            if str(candidate.id) < str(item.id):
                continue
            if await _scope_signature(candidate.id) != item_scope:
                continue
            signal = _contradiction_signal(item, candidate)
            if (
                contradiction_mode != "off"
                and signal is not None
                and similarity
                >= runtime_settings.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD
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
                    threshold=runtime_settings.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD,
                    proposed_action="keep_newest",
                    details={
                        "signal": signal,
                        "proposed_canonical_item_id": str(canonical.id),
                    },
                    reuse_pending=contradiction_mode == "automatic",
                )
            elif (
                duplicate_mode != "off"
                and similarity >= runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD
            ):
                canonical = min((item, candidate), key=_meaningful_at)
                finding = await _store_finding(
                    kind="duplicate",
                    primary=item,
                    related=candidate,
                    score=similarity,
                    threshold=runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
                    proposed_action="merge_keep_oldest",
                    details={"proposed_canonical_item_id": str(canonical.id)},
                    reuse_pending=duplicate_mode == "automatic",
                )
            else:
                finding = None
            if finding is not None:
                actionable.append(finding)
    await get_db().commit()
    for finding in actionable:
        mode = {
            "duplicate": duplicate_mode,
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
            runtime_settings.MEMORY_DUPLICATE_MODE,
        ),
        "contradiction": (
            runtime_settings.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD,
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
    if canonical.id == duplicate.id:
        raise service.MemoryConflictError("A memory cannot be merged into itself.")
    if canonical.owner_agent_id != duplicate.owner_agent_id:
        raise service.MemoryConflictError("Memories owned by different agents cannot be merged.")
    if await _scope_signature(canonical.id) != await _scope_signature(duplicate.id):
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
        if (row.source_kind, row.source_ref) in existing_sources:
            await db.delete(row)
        else:
            row.item_id = canonical.id
            existing_sources.add((row.source_kind, row.source_ref))

    existing_grants = {
        row.agent_id: row
        for row in (
            await db.scalars(
                select(MemoryItemGrant).where(MemoryItemGrant.item_id == canonical.id)
            )
        ).all()
    }
    for row in (
        await db.scalars(
            select(MemoryItemGrant).where(MemoryItemGrant.item_id == duplicate.id)
        )
    ).all():
        existing = existing_grants.get(row.agent_id)
        if existing is not None:
            existing.can_write = existing.can_write or row.can_write
            await db.delete(row)
        else:
            row.item_id = canonical.id

    await db.execute(delete(MemoryContactItem).where(MemoryContactItem.item_id == duplicate.id))
    await db.execute(
        delete(MemoryTopicContactItem).where(MemoryTopicContactItem.item_id == duplicate.id)
    )
    links = (
        await db.scalars(
            select(MemoryLink).where(
                or_(
                    MemoryLink.source_item_id == duplicate.id,
                    MemoryLink.target_item_id == duplicate.id,
                )
            )
        )
    ).all()
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
    primary = await get_db().get(MemoryItem, finding.primary_item_id)
    related = (
        await get_db().get(MemoryItem, finding.related_item_id)
        if finding.related_item_id is not None
        else None
    )
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
