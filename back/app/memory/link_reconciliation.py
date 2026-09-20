"""Idempotent reconstruction of every link derived from canonical memory data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.conversation import ConversationRound
from app.goal import Goal, GoalCycle
from app.process import ProcessRun
from app.task import Task
from app.topic import Topic
from core.database import get_db

from .models import (
    MemoryContactItem,
    MemoryItem,
    MemoryLink,
    MemorySource,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)
from .topic_maintenance import build_topic_maintenance_plan


MemoryLinkFamily = Literal["canonical", "suggested"]
TOPIC_PROJECTION = "memory.topic_membership"
CONTACT_PROJECTION = "memory.contact_membership"
TOPIC_CONTACT_PROJECTION = "memory.topic_contact_membership"
GOAL_PROJECTION = "goal.cycle_membership"
PROCESS_PROJECTION = "process.result_membership"
TOPIC_MAINTENANCE_PROJECTION = "memory.topic_maintenance"
PROJECTION_VERSION = 1
CANONICAL_PROJECTIONS = frozenset(
    {TOPIC_PROJECTION, CONTACT_PROJECTION, GOAL_PROJECTION, PROCESS_PROJECTION}
)


@dataclass(frozen=True, slots=True)
class DerivedMemoryLink:
    source_item_id: UUID
    target_item_id: UUID
    relation_type: str
    projection_key: str
    confidence: float = 1.0
    suggested: bool = False
    projection_version: int = PROJECTION_VERSION
    metadata: dict[str, object] = field(default_factory=lambda: {})

    @property
    def key(self) -> tuple[UUID, UUID, str]:
        return (self.source_item_id, self.target_item_id, self.relation_type)


@dataclass(frozen=True, slots=True)
class MemoryLinkReconciliationResult:
    scope_item_id: UUID | None
    sources_scanned: int = 0
    desired: int = 0
    created: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    manual_conflicts: int = 0
    incomplete_sources: int = 0
    contact_memberships_created: int = 0
    contact_memberships_updated: int = 0
    contact_memberships_removed: int = 0
    topic_contact_memberships_created: int = 0
    topic_contact_memberships_updated: int = 0
    topic_contact_memberships_removed: int = 0
    suggestions_available: bool = True

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _SourceScope:
    item_id: UUID
    owner_agent_id: int
    source_kind: str
    source_ref: str
    topic_item_id: UUID | None
    contact_item_id: UUID | None
    incomplete: bool = False


@dataclass(slots=True)
class _MutableResult:
    scope_item_id: UUID | None
    sources_scanned: int = 0
    desired: int = 0
    created: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    manual_conflicts: int = 0
    incomplete_sources: int = 0
    contact_memberships_created: int = 0
    contact_memberships_updated: int = 0
    contact_memberships_removed: int = 0
    topic_contact_memberships_created: int = 0
    topic_contact_memberships_updated: int = 0
    topic_contact_memberships_removed: int = 0
    suggestions_available: bool = True

    def freeze(self) -> MemoryLinkReconciliationResult:
        return MemoryLinkReconciliationResult(**asdict(self))


def _managed_metadata(kind: str) -> dict[str, object]:
    return {
        "managed_projection": True,
        "projection_kind": kind,
    }


async def _task_scopes(item_id: UUID | None) -> list[_SourceScope]:
    query = (
        select(
            MemorySource.item_id,
            MemoryItem.owner_agent_id,
            MemorySource.source_kind,
            MemorySource.source_ref,
            Topic.memory_item_id,
            Task.contact_memory_item_id,
            Task.topic_id,
            Task.messenger_connection_id,
            Task.ai,
        )
        .select_from(MemorySource)
        .join(MemoryItem, MemoryItem.id == MemorySource.item_id)
        .join(Task, Task.id == MemorySource.task_id)
        .outerjoin(Topic, Topic.id == Task.topic_id)
        .where(
            MemorySource.source_kind.in_(("task", "task_outcome")),
            MemoryItem.source_managed.is_(False),
        )
        .execution_options(include_historized=True)
    )
    if item_id is not None:
        query = query.where(
            or_(
                MemorySource.item_id == item_id,
                Topic.memory_item_id == item_id,
                Task.contact_memory_item_id == item_id,
            )
        )
    rows = (await get_db().execute(query)).all()
    result: list[_SourceScope] = []
    for (
        memory_id,
        owner_agent_id,
        source_kind,
        source_ref,
        topic_item_id,
        contact_item_id,
        topic_id,
        connection_id,
        sender_is_ai,
    ) in rows:
        if owner_agent_id is None:
            continue
        needs_contact = connection_id is not None and not bool(sender_is_ai)
        result.append(
            _SourceScope(
                item_id=memory_id,
                owner_agent_id=int(owner_agent_id),
                source_kind=str(source_kind),
                source_ref=str(source_ref),
                topic_item_id=topic_item_id,
                contact_item_id=contact_item_id,
                incomplete=(
                    topic_id is None
                    or topic_item_id is None
                    or (needs_contact and contact_item_id is None)
                ),
            )
        )
    return result


async def _conversation_scopes(item_id: UUID | None) -> list[_SourceScope]:
    query = (
        select(
            MemorySource.item_id,
            MemoryItem.owner_agent_id,
            MemorySource.source_kind,
            MemorySource.source_ref,
            Topic.memory_item_id,
            ConversationRound.contact_memory_item_id,
            ConversationRound.topic_id,
        )
        .select_from(MemorySource)
        .join(MemoryItem, MemoryItem.id == MemorySource.item_id)
        .join(
            ConversationRound,
            ConversationRound.id == MemorySource.conversation_round_id,
        )
        .outerjoin(Topic, Topic.id == ConversationRound.topic_id)
        .where(
            MemorySource.source_kind == "conversation_round",
            MemoryItem.source_managed.is_(False),
        )
        .execution_options(include_historized=True)
    )
    if item_id is not None:
        query = query.where(
            or_(
                MemorySource.item_id == item_id,
                Topic.memory_item_id == item_id,
                ConversationRound.contact_memory_item_id == item_id,
            )
        )
    rows = (await get_db().execute(query)).all()
    return [
        _SourceScope(
            item_id=memory_id,
            owner_agent_id=int(owner_agent_id),
            source_kind=str(source_kind),
            source_ref=str(source_ref),
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
            incomplete=(
                topic_id is None
                or topic_item_id is None
                or contact_item_id is None
            ),
        )
        for (
            memory_id,
            owner_agent_id,
            source_kind,
            source_ref,
            topic_item_id,
            contact_item_id,
            topic_id,
        ) in rows
        if owner_agent_id is not None
    ]


async def _source_scopes(item_id: UUID | None) -> list[_SourceScope]:
    scopes = [
        *(await _task_scopes(item_id)),
        *(await _conversation_scopes(item_id)),
    ]
    return list(
        {
            (
                scope.item_id,
                scope.source_kind,
                scope.source_ref,
                scope.topic_item_id,
                scope.contact_item_id,
            ): scope
            for scope in scopes
        }.values()
    )


async def _reconcile_contact_memberships(
    scopes: list[_SourceScope],
    *,
    item_id: UUID | None,
    result: _MutableResult,
) -> None:
    desired_by_item: dict[UUID, _SourceScope] = {}
    conflicting_items: set[UUID] = set()
    for scope in sorted(
        (value for value in scopes if value.contact_item_id is not None),
        key=lambda value: (str(value.item_id), value.source_kind, value.source_ref),
    ):
        current = desired_by_item.get(scope.item_id)
        if current is not None and current.contact_item_id != scope.contact_item_id:
            conflicting_items.add(scope.item_id)
            continue
        desired_by_item.setdefault(scope.item_id, scope)
    for memory_id in conflicting_items:
        desired_by_item.pop(memory_id, None)
        result.incomplete_sources += 1

    query = select(MemoryContactItem)
    if item_id is not None:
        query = query.where(
            or_(
                MemoryContactItem.item_id == item_id,
                MemoryContactItem.contact_item_id == item_id,
            )
        )
    existing = list((await get_db().scalars(query)).all())
    existing_by_item = {row.item_id: row for row in existing}
    for row in existing:
        if row.item_id in desired_by_item:
            continue
        await get_db().delete(row)
        result.contact_memberships_removed += 1
    for memory_id, scope in desired_by_item.items():
        assert scope.contact_item_id is not None
        row = existing_by_item.get(memory_id)
        if row is None:
            get_db().add(
                MemoryContactItem(
                    owner_agent_id=scope.owner_agent_id,
                    contact_item_id=scope.contact_item_id,
                    item_id=memory_id,
                    source_kind=scope.source_kind,
                    source_ref=scope.source_ref,
                )
            )
            result.contact_memberships_created += 1
            continue
        if (
            row.owner_agent_id != scope.owner_agent_id
            or row.contact_item_id != scope.contact_item_id
            or row.source_kind != scope.source_kind
            or row.source_ref != scope.source_ref
        ):
            row.owner_agent_id = scope.owner_agent_id
            row.contact_item_id = scope.contact_item_id
            row.source_kind = scope.source_kind
            row.source_ref = scope.source_ref
            result.contact_memberships_updated += 1
    await get_db().flush()


async def _scope_id(scope: _SourceScope) -> UUID:
    assert scope.topic_item_id is not None
    assert scope.contact_item_id is not None
    inserted = await get_db().scalar(
        pg_insert(MemoryTopicContactScope)
        .values(
            owner_agent_id=scope.owner_agent_id,
            topic_item_id=scope.topic_item_id,
            contact_item_id=scope.contact_item_id,
        )
        .on_conflict_do_nothing(
            index_elements=[
                MemoryTopicContactScope.owner_agent_id,
                MemoryTopicContactScope.topic_item_id,
                MemoryTopicContactScope.contact_item_id,
            ]
        )
        .returning(MemoryTopicContactScope.id)
    )
    if inserted is not None:
        return inserted
    existing = await get_db().scalar(
        select(MemoryTopicContactScope.id).where(
            MemoryTopicContactScope.owner_agent_id == scope.owner_agent_id,
            MemoryTopicContactScope.topic_item_id == scope.topic_item_id,
            MemoryTopicContactScope.contact_item_id == scope.contact_item_id,
        )
    )
    if existing is None:
        raise RuntimeError("Topic/contact memory scope could not be resolved.")
    return existing


async def _reconcile_topic_contact_memberships(
    scopes: list[_SourceScope],
    *,
    item_id: UUID | None,
    result: _MutableResult,
) -> None:
    desired: dict[tuple[int, UUID, UUID, UUID], _SourceScope] = {}
    for scope in sorted(
        (
            value
            for value in scopes
            if value.topic_item_id is not None and value.contact_item_id is not None
        ),
        key=lambda value: (value.source_kind, value.source_ref),
    ):
        assert scope.topic_item_id is not None
        assert scope.contact_item_id is not None
        desired.setdefault(
            (
                scope.owner_agent_id,
                scope.topic_item_id,
                scope.contact_item_id,
                scope.item_id,
            ),
            scope,
        )
    query = select(MemoryTopicContactItem, MemoryTopicContactScope).join(
        MemoryTopicContactScope,
        MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
    )
    if item_id is not None:
        query = query.where(
            or_(
                MemoryTopicContactItem.item_id == item_id,
                MemoryTopicContactScope.topic_item_id == item_id,
                MemoryTopicContactScope.contact_item_id == item_id,
            )
        )
    existing_rows = list((await get_db().execute(query)).all())
    existing = {
        (
            scope.owner_agent_id,
            scope.topic_item_id,
            scope.contact_item_id,
            row.item_id,
        ): (row, scope)
        for row, scope in existing_rows
    }
    for key, (row, _scope) in existing.items():
        if key in desired:
            continue
        await get_db().delete(row)
        result.topic_contact_memberships_removed += 1
    for key, source_scope in desired.items():
        scope_id = await _scope_id(source_scope)
        current = existing.get(key)
        if current is None:
            get_db().add(
                MemoryTopicContactItem(
                    scope_id=scope_id,
                    item_id=source_scope.item_id,
                    source_kind=source_scope.source_kind,
                    source_ref=source_scope.source_ref,
                )
            )
            result.topic_contact_memberships_created += 1
            continue
        row, _old_scope = current
        if (
            row.scope_id != scope_id
            or row.source_kind != source_scope.source_kind
            or row.source_ref != source_scope.source_ref
        ):
            row.scope_id = scope_id
            row.source_kind = source_scope.source_kind
            row.source_ref = source_scope.source_ref
            result.topic_contact_memberships_updated += 1
    await get_db().flush()
    await get_db().execute(
        delete(MemoryTopicContactScope).where(
            ~exists(
                select(MemoryTopicContactItem.id).where(
                    MemoryTopicContactItem.scope_id == MemoryTopicContactScope.id
                )
            )
        )
    )


async def _canonical_links(
    scopes: list[_SourceScope], item_id: UUID | None
) -> list[DerivedMemoryLink]:
    links: dict[tuple[UUID, UUID, str], DerivedMemoryLink] = {}
    for scope in scopes:
        if scope.topic_item_id is not None:
            link = DerivedMemoryLink(
                source_item_id=scope.topic_item_id,
                target_item_id=scope.item_id,
                relation_type="topic_contains",
                projection_key=TOPIC_PROJECTION,
                metadata=_managed_metadata("topic"),
            )
            links[link.key] = link
        if scope.contact_item_id is not None:
            link = DerivedMemoryLink(
                source_item_id=scope.contact_item_id,
                target_item_id=scope.item_id,
                relation_type="contact_contains",
                projection_key=CONTACT_PROJECTION,
                metadata=_managed_metadata("contact"),
            )
            links[link.key] = link

    goal_query = (
        select(GoalCycle.memory_item_id, Goal.memory_item_id)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .where(
            GoalCycle.memory_item_id.is_not(None),
            Goal.memory_item_id.is_not(None),
            Goal.deleted_at.is_(None),
        )
        .execution_options(include_historized=True)
    )
    if item_id is not None:
        goal_query = goal_query.where(
            or_(
                GoalCycle.memory_item_id == item_id,
                Goal.memory_item_id == item_id,
            )
        )
    for cycle_item_id, goal_item_id in (await get_db().execute(goal_query)).all():
        if cycle_item_id is None or goal_item_id is None:
            continue
        link = DerivedMemoryLink(
            source_item_id=cycle_item_id,
            target_item_id=goal_item_id,
            relation_type="cycle_of",
            projection_key=GOAL_PROJECTION,
            metadata={"managed_projection": True},
        )
        links[link.key] = link

    process_items = list(
        (
            await get_db().scalars(
                select(MemoryItem).where(
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.managed_source_kind.in_(
                        ("process_definition", "process_run")
                    ),
                )
            )
        ).all()
    )
    definitions: dict[int, UUID] = {}
    runs: dict[UUID, UUID] = {}
    for memory in process_items:
        prefix, _, raw_id = str(memory.managed_source_ref or "").partition(":")
        try:
            if prefix == "process_definition":
                definitions[int(raw_id)] = memory.id
            elif prefix == "process_run":
                runs[UUID(raw_id)] = memory.id
        except ValueError:
            continue
    if runs and definitions:
        process_query = select(ProcessRun.id, ProcessRun.process_id).where(
            ProcessRun.id.in_(runs),
            ProcessRun.process_id.in_(definitions),
            ProcessRun.status == "success",
            ProcessRun.deleted_at.is_(None),
        )
        for run_id, process_id in (await get_db().execute(process_query)).all():
            run_item_id = runs[run_id]
            definition_item_id = definitions[int(process_id)]
            if item_id is not None and item_id not in (
                run_item_id,
                definition_item_id,
            ):
                continue
            link = DerivedMemoryLink(
                source_item_id=run_item_id,
                target_item_id=definition_item_id,
                relation_type="result_of",
                projection_key=PROCESS_PROJECTION,
                metadata={"managed_projection": True},
            )
            links[link.key] = link
    return list(links.values())


async def _topic_contact_links() -> list[DerivedMemoryLink]:
    """Project one structural edge for every authoritative Topic/contact scope."""

    rows = list(
        (
            await get_db().execute(
                select(
                    MemoryTopicContactScope.topic_item_id,
                    MemoryTopicContactScope.contact_item_id,
                ).distinct()
            )
        ).all()
    )
    return [
        DerivedMemoryLink(
            source_item_id=topic_item_id,
            target_item_id=contact_item_id,
            relation_type="topic_involves_contact",
            projection_key=TOPIC_CONTACT_PROJECTION,
            metadata=_managed_metadata("topic_contact"),
        )
        for topic_item_id, contact_item_id in rows
    ]


async def _suggested_links(
    item_id: UUID | None,
) -> tuple[list[DerivedMemoryLink], bool]:
    plan = await build_topic_maintenance_plan()
    if plan is None:
        return [], False
    return (
        [
            DerivedMemoryLink(
                source_item_id=suggestion.source_item_id,
                target_item_id=suggestion.target_item_id,
                relation_type=suggestion.relation_type,
                projection_key=TOPIC_MAINTENANCE_PROJECTION,
                projection_version=1,
                confidence=suggestion.confidence,
                suggested=True,
                metadata=dict(suggestion.metadata),
            )
            for suggestion in plan.suggestions
            if item_id is None
            or item_id in (suggestion.source_item_id, suggestion.target_item_id)
        ],
        True,
    )


async def _write_links(
    desired: list[DerivedMemoryLink],
    *,
    item_id: UUID | None,
    projection_keys: frozenset[str],
    result: _MutableResult,
) -> None:
    query = select(MemoryLink)
    if item_id is not None:
        query = query.where(
            or_(
                MemoryLink.source_item_id == item_id,
                MemoryLink.target_item_id == item_id,
            )
        )
    existing_rows = list((await get_db().scalars(query)).all())
    existing = {
        (row.source_item_id, row.target_item_id, row.relation_type): row
        for row in existing_rows
    }
    desired_by_key = {link.key: link for link in desired}
    result.desired += len(desired_by_key)
    for key, row in existing.items():
        if row.projection_key not in projection_keys or key in desired_by_key:
            continue
        await get_db().delete(row)
        result.removed += 1
    for key, link in desired_by_key.items():
        row = existing.get(key)
        if row is None:
            inserted = await get_db().scalar(
                pg_insert(MemoryLink)
                .values(
                    source_item_id=link.source_item_id,
                    target_item_id=link.target_item_id,
                    relation_type=link.relation_type,
                    confidence=link.confidence,
                    suggested=link.suggested,
                    created_by_agent_id=None,
                    projection_key=link.projection_key,
                    projection_version=link.projection_version,
                    metadata_=link.metadata,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        MemoryLink.source_item_id,
                        MemoryLink.target_item_id,
                        MemoryLink.relation_type,
                    ]
                )
                .returning(MemoryLink.id)
            )
            if inserted is None:
                result.manual_conflicts += 1
            else:
                result.created += 1
            continue
        if row.projection_key is None:
            result.manual_conflicts += 1
            continue
        if row.projection_key != link.projection_key:
            result.manual_conflicts += 1
            continue
        metadata = dict(link.metadata)
        if (
            row.confidence != link.confidence
            or row.suggested != link.suggested
            or row.projection_version != link.projection_version
            or row.metadata_ != metadata
        ):
            row.confidence = link.confidence
            row.suggested = link.suggested
            row.projection_version = link.projection_version
            row.metadata_ = metadata
            result.updated += 1
        else:
            result.unchanged += 1
    await get_db().flush()


async def reconcile_memory_links(
    *,
    item_id: UUID | None = None,
    families: frozenset[MemoryLinkFamily] | None = None,
) -> MemoryLinkReconciliationResult:
    """Converge all derived links globally or around one MemoryItem."""

    selected = families or frozenset({"canonical", "suggested"})
    # Serialize global and targeted writers. The graph has a natural unique key,
    # but one writer must not sweep an edge while another is deriving it.
    await get_db().execute(select(func.pg_advisory_xact_lock(6_412_907_331)))
    if item_id is not None:
        item = await get_db().get(MemoryItem, item_id)
        if item is None:
            raise ValueError(f"Memory item does not exist: {item_id}")
    result = _MutableResult(scope_item_id=item_id)
    scopes: list[_SourceScope] = []
    canonical: list[DerivedMemoryLink] = []
    suggested: list[DerivedMemoryLink] = []
    if "canonical" in selected:
        scopes = await _source_scopes(item_id)
        result.sources_scanned = len(scopes)
        result.incomplete_sources = sum(scope.incomplete for scope in scopes)
        canonical = await _canonical_links(scopes, item_id)
    if "suggested" in selected:
        # Resolve the optional vector model before making canonical writes:
        # its fail-open path may roll back a provider-resolution transaction.
        suggested, available = await _suggested_links(item_id)
        result.suggestions_available = available
    if "canonical" in selected:
        await _reconcile_contact_memberships(scopes, item_id=item_id, result=result)
        await _reconcile_topic_contact_memberships(
            scopes, item_id=item_id, result=result
        )
        await _write_links(
            canonical,
            item_id=item_id,
            projection_keys=CANONICAL_PROJECTIONS,
            result=result,
        )
        # The direct Topic/contact edge summarizes a shared authoritative scope.
        # Reconcile this small family globally because its endpoints do not include
        # the scoped memory item that may have created or removed the last scope.
        await _write_links(
            await _topic_contact_links(),
            item_id=None,
            projection_keys=frozenset({TOPIC_CONTACT_PROJECTION}),
            result=result,
        )
    if "suggested" in selected:
        if result.suggestions_available:
            await _write_links(
                suggested,
                item_id=item_id,
                projection_keys=frozenset({TOPIC_MAINTENANCE_PROJECTION}),
                result=result,
            )
    await get_db().commit()
    return result.freeze()


__all__ = [
    "MemoryLinkFamily",
    "MemoryLinkReconciliationResult",
    "reconcile_memory_links",
]
