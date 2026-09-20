"""Public contact-directory operations backed by canonical Memory items."""

from __future__ import annotations

from collections import defaultdict

from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select, union_all, update

from core.database import get_db

from . import service
from .contracts import (
    ContactReferenceCleaner,
    ContactReferenceRewriter,
    MessengerContactIdentity as ContactIdentityRecord,
    MessengerContactRecord,
)
from .messenger_contact import MESSENGER_CONTACT_SOURCE_KIND
from .models import (
    MemoryAssociation,
    MemoryContactIdentity,
    MemoryContactItem,
    MemoryItem,
    MemoryLink,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)


async def _contact_item(
    contact_item_id: UUID, *, for_update: bool = False
) -> MemoryItem | None:
    query = select(MemoryItem).where(
        MemoryItem.id == contact_item_id,
        MemoryItem.source_managed.is_(True),
        MemoryItem.managed_source_kind == MESSENGER_CONTACT_SOURCE_KIND,
    )
    if for_update:
        query = query.with_for_update()
    return await get_db().scalar(query)


def _display_name(
    item: MemoryItem, identities: tuple[ContactIdentityRecord, ...]
) -> str:
    for identity in identities:
        if identity.display_name:
            return identity.display_name
    metadata_name = str(item.metadata_.get("display_name") or "").strip()
    if metadata_name:
        return metadata_name
    return item.title.removeprefix("Contact — ").strip() or item.title


async def list_messenger_contacts(
    *,
    owner_agent_id: int,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    contact_item_id: UUID | None = None,
) -> tuple[tuple[MessengerContactRecord, ...], int]:
    """List active canonical contacts for one managed Agent."""

    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)
    normalized_query = " ".join(query.split())[:500]
    filters = [
        MemoryItem.owner_agent_id == owner_agent_id,
        MemoryItem.source_managed.is_(True),
        MemoryItem.managed_source_kind == MESSENGER_CONTACT_SOURCE_KIND,
    ]
    if contact_item_id is not None:
        filters.append(MemoryItem.id == contact_item_id)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                MemoryItem.title.ilike(pattern),
                exists(
                    select(MemoryContactIdentity.id).where(
                        MemoryContactIdentity.contact_item_id == MemoryItem.id,
                        or_(
                            MemoryContactIdentity.display_name.ilike(pattern),
                            MemoryContactIdentity.namespace.ilike(pattern),
                            MemoryContactIdentity.external_id.ilike(pattern),
                        ),
                    )
                ),
            )
        )
    total = int(
        await get_db().scalar(
            select(func.count(MemoryItem.id)).where(*filters)
        )
        or 0
    )
    items = tuple(
        (
            await get_db().scalars(
                select(MemoryItem)
                .where(*filters)
                .order_by(func.lower(MemoryItem.title), MemoryItem.id)
                .offset(bounded_offset)
                .limit(bounded_limit)
            )
        ).all()
    )
    if not items:
        return (), total

    item_ids = [item.id for item in items]
    identities_by_contact: dict[UUID, list[ContactIdentityRecord]] = defaultdict(list)
    identity_rows = (
        await get_db().scalars(
            select(MemoryContactIdentity)
            .where(MemoryContactIdentity.contact_item_id.in_(item_ids))
            .order_by(
                MemoryContactIdentity.identity_kind,
                MemoryContactIdentity.namespace,
                MemoryContactIdentity.external_id,
            )
        )
    ).all()
    for identity in identity_rows:
        kind = (
            "galaris_user"
            if identity.identity_kind == "galaris_user"
            else "messenger"
        )
        identities_by_contact[identity.contact_item_id].append(
            ContactIdentityRecord(
                id=identity.id,
                kind=kind,
                namespace=identity.namespace,
                external_id=identity.external_id,
                display_name=identity.display_name,
                galaris_user_id=identity.galaris_user_id,
            )
        )

    scoped_items = union_all(
        select(
            MemoryContactItem.contact_item_id.label("contact_item_id"),
            MemoryContactItem.item_id.label("item_id"),
        ),
        select(
            MemoryTopicContactScope.contact_item_id.label("contact_item_id"),
            MemoryTopicContactItem.item_id.label("item_id"),
        ).join(
            MemoryTopicContactScope,
            MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
        ),
    ).subquery()
    linked_counts = {
        contact_item_id: int(count)
        for contact_item_id, count in (
            await get_db().execute(
                select(
                    scoped_items.c.contact_item_id,
                    func.count(func.distinct(scoped_items.c.item_id)),
                )
                .where(scoped_items.c.contact_item_id.in_(item_ids))
                .group_by(scoped_items.c.contact_item_id)
            )
        ).all()
    }
    records: list[MessengerContactRecord] = []
    for item in items:
        identities = tuple(identities_by_contact[item.id])
        assert item.owner_agent_id is not None
        records.append(
            MessengerContactRecord(
                memory_item_id=item.id,
                owner_agent_id=item.owner_agent_id,
                title=item.title,
                display_name=_display_name(item, identities),
                identities=identities,
                linked_memory_count=linked_counts.get(item.id, 0),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return tuple(records), total


async def get_messenger_contact(contact_item_id: UUID) -> MessengerContactRecord | None:
    """Resolve one contact through the same public administrative projection."""

    item = await _contact_item(contact_item_id)
    if item is None or item.owner_agent_id is None:
        return None
    records, _total = await list_messenger_contacts(
        owner_agent_id=item.owner_agent_id,
        limit=1,
        offset=0,
        contact_item_id=contact_item_id,
    )
    return next(
        (record for record in records if record.memory_item_id == contact_item_id),
        None,
    )


async def _move_topic_contact_scopes(
    source_contact_item_id: UUID, target_contact_item_id: UUID
) -> int:
    moved = 0
    source_scopes = list(
        (
            await get_db().scalars(
                select(MemoryTopicContactScope).where(
                    MemoryTopicContactScope.contact_item_id
                    == source_contact_item_id
                )
            )
        ).all()
    )
    for source_scope in source_scopes:
        target_scope = await get_db().scalar(
            select(MemoryTopicContactScope).where(
                MemoryTopicContactScope.owner_agent_id
                == source_scope.owner_agent_id,
                MemoryTopicContactScope.topic_item_id
                == source_scope.topic_item_id,
                MemoryTopicContactScope.contact_item_id
                == target_contact_item_id,
            )
        )
        if target_scope is None:
            source_scope.contact_item_id = target_contact_item_id
            moved += 1
            continue
        existing_item_ids = set(
            (
                await get_db().scalars(
                    select(MemoryTopicContactItem.item_id).where(
                        MemoryTopicContactItem.scope_id == target_scope.id
                    )
                )
            ).all()
        )
        source_items = list(
            (
                await get_db().scalars(
                    select(MemoryTopicContactItem).where(
                        MemoryTopicContactItem.scope_id == source_scope.id
                    )
                )
            ).all()
        )
        for source_item in source_items:
            if source_item.item_id in existing_item_ids:
                await get_db().delete(source_item)
            else:
                source_item.scope_id = target_scope.id
                existing_item_ids.add(source_item.item_id)
        await get_db().delete(source_scope)
        moved += 1
    return moved


async def _move_memory_links(
    source_contact_item_id: UUID, target_contact_item_id: UUID
) -> int:
    moved = 0
    links = list(
        (
            await get_db().scalars(
                select(MemoryLink).where(
                    or_(
                        MemoryLink.source_item_id == source_contact_item_id,
                        MemoryLink.target_item_id == source_contact_item_id,
                    )
                )
            )
        ).all()
    )
    for link in links:
        source_id = (
            target_contact_item_id
            if link.source_item_id == source_contact_item_id
            else link.source_item_id
        )
        target_id = (
            target_contact_item_id
            if link.target_item_id == source_contact_item_id
            else link.target_item_id
        )
        if source_id == target_id:
            await get_db().delete(link)
            continue
        duplicate = await get_db().scalar(
            select(MemoryLink.id).where(
                MemoryLink.id != link.id,
                MemoryLink.source_item_id == source_id,
                MemoryLink.target_item_id == target_id,
                MemoryLink.relation_type == link.relation_type,
            )
        )
        if duplicate is not None:
            await get_db().delete(link)
            continue
        link.source_item_id = source_id
        link.target_item_id = target_id
        moved += 1
    return moved


async def _move_legacy_associations(
    source_contact_item_id: UUID, target_contact_item_id: UUID
) -> None:
    associations = list(
        (
            await get_db().scalars(
                select(MemoryAssociation).where(
                    or_(
                        MemoryAssociation.item_a_id == source_contact_item_id,
                        MemoryAssociation.item_b_id == source_contact_item_id,
                    )
                )
            )
        ).all()
    )
    for association in associations:
        item_a_id = (
            target_contact_item_id
            if association.item_a_id == source_contact_item_id
            else association.item_a_id
        )
        item_b_id = (
            target_contact_item_id
            if association.item_b_id == source_contact_item_id
            else association.item_b_id
        )
        if item_a_id == item_b_id:
            await get_db().delete(association)
            continue
        duplicate = await get_db().scalar(
            select(MemoryAssociation).where(
                MemoryAssociation.id != association.id,
                MemoryAssociation.item_a_id == item_a_id,
                MemoryAssociation.item_b_id == item_b_id,
            )
        )
        if duplicate is not None:
            duplicate.score = max(duplicate.score, association.score)
            duplicate.observations += association.observations
            duplicate.last_observed_at = max(
                duplicate.last_observed_at, association.last_observed_at
            )
            await get_db().delete(association)
        else:
            association.item_a_id = item_a_id
            association.item_b_id = item_b_id


async def merge_messenger_contacts(
    *,
    source_contact_item_id: UUID,
    target_contact_item_id: UUID,
    rewire_references: ContactReferenceRewriter,
) -> tuple[MessengerContactRecord, dict[str, int]]:
    """Atomically merge a duplicate contact into the selected canonical item."""

    if source_contact_item_id == target_contact_item_id:
        raise service.MemoryConflictError("A contact cannot be merged into itself.")
    source = await _contact_item(source_contact_item_id, for_update=True)
    target = await _contact_item(target_contact_item_id, for_update=True)
    if source is None or target is None:
        raise service.MemoryNotFoundError("Source or target contact not found.")
    if source.owner_agent_id != target.owner_agent_id:
        raise service.MemoryConflictError(
            "Contacts owned by different agents cannot be merged."
        )

    external_counts = await rewire_references(
        source_contact_item_id, target_contact_item_id
    )
    await get_db().execute(
        update(MemoryContactIdentity)
        .where(MemoryContactIdentity.contact_item_id == source_contact_item_id)
        .values(contact_item_id=target_contact_item_id)
    )
    direct_memories = await get_db().execute(
        update(MemoryContactItem)
        .where(
            MemoryContactItem.contact_item_id == source_contact_item_id,
            MemoryContactItem.item_id != target_contact_item_id,
        )
        .values(contact_item_id=target_contact_item_id)
    )
    await get_db().execute(
        delete(MemoryContactItem).where(
            MemoryContactItem.contact_item_id == source_contact_item_id
        )
    )
    moved_scopes = await _move_topic_contact_scopes(
        source_contact_item_id, target_contact_item_id
    )
    moved_links = await _move_memory_links(
        source_contact_item_id, target_contact_item_id
    )
    await _move_legacy_associations(
        source_contact_item_id, target_contact_item_id
    )
    merged_ids = list(target.metadata_.get("merged_contact_item_ids", []))
    merged_ids.append(str(source_contact_item_id))
    target.metadata_ = {
        **target.metadata_,
        "merged_contact_item_ids": list(dict.fromkeys(merged_ids)),
    }
    source_ref = source.managed_source_ref
    if source_ref is None:
        raise service.MemoryConflictError("The source contact has no projection identity.")
    await service.forget_source_managed_item(
        source_kind=MESSENGER_CONTACT_SOURCE_KIND,
        source_ref=source_ref,
        item_id=source.id,
    )
    merged = await get_messenger_contact(target.id)
    if merged is None:
        raise service.MemoryNotFoundError("Merged contact not found.")
    counts = {
        **external_counts,
        "memories": int(getattr(direct_memories, "rowcount", 0) or 0),
        "topic_scopes": moved_scopes,
        "memory_links": moved_links,
    }
    return merged, counts


async def forget_messenger_contact(
    *,
    contact_item_id: UUID,
    clear_references: ContactReferenceCleaner,
) -> dict[str, int]:
    """Forget a contact, all memories sealed to it, and every external reference."""

    contact = await _contact_item(contact_item_id, for_update=True)
    if contact is None or contact.owner_agent_id is None:
        raise service.MemoryNotFoundError("Contact not found.")

    scoped_items = union_all(
        select(MemoryContactItem.item_id).where(
            MemoryContactItem.contact_item_id == contact_item_id
        ),
        select(MemoryTopicContactItem.item_id).join(
            MemoryTopicContactScope,
            MemoryTopicContactScope.id == MemoryTopicContactItem.scope_id,
        ).where(MemoryTopicContactScope.contact_item_id == contact_item_id),
    ).subquery()
    memory_ids = tuple(
        (
            await get_db().scalars(
                select(scoped_items.c.item_id).distinct()
            )
        ).all()
    )
    memories = tuple(
        (
            await get_db().scalars(
                select(MemoryItem).where(MemoryItem.id.in_(memory_ids))
            )
        ).all()
    ) if memory_ids else ()
    for memory in memories:
        if memory.owner_agent_id != contact.owner_agent_id:
            raise service.MemoryConflictError(
                "A linked memory is not owned by the contact's agent."
            )
        if memory.source_managed or memory.deletion_protected:
            raise service.MemoryConflictError(
                "A protected or source-managed linked memory cannot be forgotten."
            )

    cleared = await clear_references(contact_item_id)
    resources_deleted = 0
    for memory in memories:
        forgotten = await service.forget_item(
            memory.id,
            actor_agent_id=contact.owner_agent_id,
            administrative=True,
        )
        resources_deleted += forgotten.resources_deleted

    source_ref = contact.managed_source_ref
    if source_ref is None:
        raise service.MemoryConflictError("The contact has no projection identity.")
    forgotten_contact = await service.purge_source_managed_item(
        source_kind=MESSENGER_CONTACT_SOURCE_KIND,
        source_ref=source_ref,
        item_id=contact.id,
    )
    if forgotten_contact is None:
        raise service.MemoryNotFoundError("Contact not found.")
    return {
        **cleared,
        "memories": len(memories),
        "resources": resources_deleted + forgotten_contact.resources_deleted,
    }


__all__ = [
    "get_messenger_contact",
    "forget_messenger_contact",
    "list_messenger_contacts",
    "merge_messenger_contacts",
]
