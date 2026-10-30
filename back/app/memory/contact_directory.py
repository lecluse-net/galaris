"""Public contact-directory operations backed by canonical Memory items."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime, timezone
from uuid import uuid4

from uuid import UUID

from pydantic import EmailStr, TypeAdapter

from sqlalchemy import and_, delete, exists, func, or_, select, tuple_, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.user import get_user_record

from . import service
from .contact_coordinates import ContactCoordinates
from .contracts import (
    ContactReferenceCleaner,
    ContactReferenceRewriter,
    MessengerContactIdentity as ContactIdentityRecord,
    MessengerContactRecord,
    MessengerContactObservation,
    MessengerContactIdentityInput,
)
from .messenger_contact import MESSENGER_CONTACT_SOURCE_KIND, contact_document
from .models import (
    MemoryAssociation,
    MemoryContactIdentity,
    MemoryContactItem,
    MemoryItem,
    MemoryLink,
    MemoryTopicContactItem,
    MemoryTopicContactScope,
)

_EMAIL_ADAPTER: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


async def _contact_item(
    contact_item_id: UUID, *, for_update: bool = False
) -> MemoryItem | None:
    query = select(MemoryItem).where(
        MemoryItem.id == contact_item_id,
        MemoryItem.source_managed.is_(True),
        MemoryItem.managed_source_kind == MESSENGER_CONTACT_SOURCE_KIND,
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await get_db().scalar(query)


def _display_name(
    item: MemoryItem, identities: tuple[ContactIdentityRecord, ...]
) -> str:
    override = str(item.metadata_.get("display_name_override") or "").strip()
    if override:
        return override
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
    messenger_identities: Collection[tuple[str, str]] | None = None,
    galaris_user_ids: Collection[int] | None = None,
) -> tuple[tuple[MessengerContactRecord, ...], int]:
    """List active contacts; supplied identity collections select their union."""

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
    if messenger_identities is not None or galaris_user_ids is not None:
        identity_conditions: list[ColumnElement[bool]] = []
        if messenger_identities:
            identity_conditions.append(and_(
                MemoryContactIdentity.identity_kind == "messenger",
                tuple_(MemoryContactIdentity.namespace, MemoryContactIdentity.external_id).in_(messenger_identities),
            ))
        if galaris_user_ids:
            identity_conditions.append(and_(
                MemoryContactIdentity.identity_kind == "galaris_user",
                MemoryContactIdentity.galaris_user_id.in_(galaris_user_ids),
            ))
        if not identity_conditions:
            return (), 0
        filters.append(MemoryItem.id.in_(select(MemoryContactIdentity.contact_item_id).where(
            MemoryContactIdentity.owner_agent_id == owner_agent_id,
            or_(*identity_conditions),
        ).distinct()))
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                MemoryItem.title.ilike(pattern),
                MemoryItem.search_text.ilike(pattern),
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
                coordinates=ContactCoordinates.model_validate(item.metadata_.get("coordinates", {})),
            )
        )
    return tuple(records), total


async def contact_labels(*, owner_agent_id: int, contact_item_ids: Collection[UUID]) -> dict[UUID, str]:
    """Read authoritative contact labels in one owner-scoped query, without aliases."""
    if not contact_item_ids:
        return {}
    items = (await get_db().scalars(MemoryItem.histo_filter(select(MemoryItem).where(
        MemoryItem.id.in_(contact_item_ids),
        MemoryItem.owner_agent_id == owner_agent_id,
        MemoryItem.source_managed.is_(True),
        MemoryItem.managed_source_kind == MESSENGER_CONTACT_SOURCE_KIND,
    )))).all()
    return {item.id: _display_name(item, ()) for item in items}


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


async def has_mail_contact(*, owner_agent_id: int, address: str) -> bool:
    """A name or another agent's address book never grants email trust."""
    try:
        normalized = str(_EMAIL_ADAPTER.validate_python(address)).casefold()
    except ValueError:
        return False
    return await get_db().scalar(
        select(MemoryContactIdentity.id).join(
            MemoryItem, MemoryItem.id == MemoryContactIdentity.contact_item_id
        ).where(
            MemoryItem.owner_agent_id == owner_agent_id,
            MemoryContactIdentity.owner_agent_id == owner_agent_id,
            MemoryContactIdentity.identity_kind == "messenger",
            MemoryContactIdentity.namespace == "mail",
            func.lower(MemoryContactIdentity.external_id) == normalized,
        ).limit(1)
    ) is not None


async def create_address_book_contact(
    *, owner_agent_id: int, display_name: str, email: str | None = None,
    coordinates: ContactCoordinates | None = None,
) -> MessengerContactRecord:
    """Create a private contact with email and/or phone and postal coordinates."""
    name = " ".join(display_name.split())
    if not name or len(name) > 500:
        raise service.MemoryConflictError("A contact name must contain 1 to 500 characters.")
    address = str(_EMAIL_ADAPTER.validate_python(email)).casefold() if email else None
    if address is None and not (coordinates and (coordinates.phone_numbers or coordinates.postal_addresses)):
        raise service.MemoryConflictError("At least one email, phone number or postal address is required.")
    db = get_db()
    if address is not None and await db.scalar(select(MemoryContactIdentity.id).where(
        MemoryContactIdentity.owner_agent_id == owner_agent_id,
        MemoryContactIdentity.identity_kind == "messenger",
        MemoryContactIdentity.namespace == "mail",
        MemoryContactIdentity.external_id == address,
    )) is not None:
        raise service.MemoryConflictError("This email already belongs to a contact.")
    source_ref = f"address-book:{uuid4().hex}"
    identities = (MessengerContactIdentityInput(kind="messenger", namespace="mail", external_id=address),) if address else ()
    try:
        item = await service.upsert_source_managed_item(contact_document(
            MessengerContactObservation(owner_agent_id=owner_agent_id,
                messaging_id="mail" if address else "address_book", user_id=address or source_ref),
            source_ref=source_ref, memory_item_id=None,
            display_name=name, display_name_override=name, identities=identities,
            previous_metadata={"coordinates": coordinates.model_dump()} if coordinates is not None else None,
        ), defer_commit=True)
        if address is not None:
            db.add(MemoryContactIdentity(owner_agent_id=owner_agent_id, contact_item_id=item.id,
                identity_kind="messenger", namespace="mail", external_id=address))
        await service.commit_source_managed_items((item,))
    except IntegrityError as exc:
        await db.rollback()
        raise service.MemoryConflictError("This email already belongs to a contact.") from exc
    except Exception:
        await db.rollback()
        raise
    record = await get_messenger_contact(item.id)
    assert record is not None
    return record


async def create_mail_contact(
    *, owner_agent_id: int, display_name: str, email: str,
    coordinates: ContactCoordinates | None = None,
) -> MessengerContactRecord:
    return await create_address_book_contact(owner_agent_id=owner_agent_id, display_name=display_name,
        email=email, coordinates=coordinates)


async def split_messenger_contact(
    *, contact_item_id: UUID, identity_ids: tuple[UUID, ...],
    expected_identity_ids: tuple[UUID, ...], display_name: str,
    coordinates: ContactCoordinates | None = None,
) -> MessengerContactRecord:
    """Move selected addresses into separate contacts; retain history on the original."""
    name = " ".join(display_name.split())
    if not name or len(name) > 500:
        raise service.MemoryConflictError("A contact name must contain 1 to 500 characters.")
    db = get_db()
    source = await _contact_item(contact_item_id, for_update=True)
    if source is None or source.owner_agent_id is None:
        raise service.MemoryNotFoundError("Contact not found.")
    rows = tuple((await db.scalars(select(MemoryContactIdentity).where(
        MemoryContactIdentity.contact_item_id == contact_item_id,
    ).with_for_update())).all())
    current_ids = {row.id for row in rows}
    selected_ids = set(identity_ids)
    if set(expected_identity_ids) != current_ids:
        raise service.MemoryConflictError("Contact identities have changed. Reopen the contact before saving.")
    if (not selected_ids or len(selected_ids) != len(identity_ids)
        or not selected_ids < current_ids):
        raise service.MemoryConflictError("Split existing identities and retain at least one on the original contact.")
    if source.managed_source_ref is None:
        raise service.MemoryConflictError("The contact has no projection identity.")
    def identity_input(row: MemoryContactIdentity) -> MessengerContactIdentityInput:
        return MessengerContactIdentityInput(
            id=row.id, kind="galaris_user" if row.identity_kind == "galaris_user" else "messenger",
            namespace=row.namespace, external_id=row.external_id,
            display_name=row.display_name, galaris_user_id=row.galaris_user_id,
        )
    staged: list[MemoryItem] = []
    metadata = dict(source.metadata_)
    if coordinates is not None:
        metadata["coordinates"] = coordinates.model_dump()
    try:
        for row in rows:
            if row.id not in selected_ids:
                continue
            identity = identity_input(row)
            target = await service.upsert_source_managed_item(contact_document(
                MessengerContactObservation(owner_agent_id=source.owner_agent_id,
                    messaging_id="internal" if row.identity_kind == "galaris_user" else row.namespace,
                    user_id=row.external_id, galaris_user_id=row.galaris_user_id),
                source_ref=f"split-contact:{uuid4().hex}", memory_item_id=None,
                display_name=name, display_name_override=name, identities=(identity,),
            ), defer_commit=True)
            row.contact_item_id = target.id
            staged.append(target)
        remaining = tuple(identity_input(row) for row in rows if row.id not in selected_ids)
        source = await service.upsert_source_managed_item(contact_document(
            MessengerContactObservation(owner_agent_id=source.owner_agent_id,
                messaging_id=remaining[0].namespace, user_id=remaining[0].external_id),
            source_ref=source.managed_source_ref, memory_item_id=source.id,
            display_name=name, display_name_override=name,
            previous_metadata=metadata, identities=remaining,
        ), defer_commit=True)
        await service.commit_source_managed_items((*staged, source))
    except Exception:
        await db.rollback()
        raise
    record = await get_messenger_contact(contact_item_id)
    assert record is not None
    return record


async def update_messenger_contact(
    *, contact_item_id: UUID, display_name: str | None,
    identities: tuple[MessengerContactIdentityInput, ...] | None = None,
    expected_identities: tuple[ContactIdentityRecord, ...] | None = None,
    coordinates: ContactCoordinates | None = None,
    defer_commit: bool = False,
) -> MessengerContactRecord:
    """Atomically edit a private contact and its explicitly managed addresses."""

    name = " ".join(display_name.split()) if display_name is not None else None
    if name is not None and (not name or len(name) > 500):
        raise service.MemoryConflictError("A contact name must contain 1 to 500 characters.")
    item = await _contact_item(contact_item_id, for_update=True)
    if item is None or item.owner_agent_id is None:
        raise service.MemoryNotFoundError("Contact not found.")
    current = await get_messenger_contact(contact_item_id)
    assert current is not None
    rows = tuple((await get_db().scalars(
        select(MemoryContactIdentity).where(MemoryContactIdentity.contact_item_id == item.id)
    )).all())
    if identities is not None:
        if expected_identities is None or set(expected_identities) != set(current.identities):
            raise service.MemoryConflictError("Contact identities have changed. Reopen the contact before saving.")
        await _validate_identity_updates(item.owner_agent_id, item.id, rows, identities)
    projection_identities = identities
    if projection_identities is None and item.metadata_.get("identities_managed"):
        projection_identities = tuple(MessengerContactIdentityInput(
            id=identity.id, kind=identity.kind, namespace=identity.namespace,
            external_id=identity.external_id, display_name=identity.display_name,
            galaris_user_id=identity.galaris_user_id,
        ) for identity in current.identities)
    metadata = dict(item.metadata_)
    if coordinates is not None:
        metadata["coordinates"] = coordinates.model_dump()
    if not item.managed_source_ref:
        raise service.MemoryConflictError("The contact has no canonical source reference.")
    user_id = metadata.get("galaris_user_id")
    document = contact_document(
        MessengerContactObservation(
            owner_agent_id=item.owner_agent_id,
            messaging_id=str(metadata["messaging_id"]),
            user_id=str(metadata["user_id"]),
            display_name=str(metadata.get("display_name") or ""),
            galaris_user_id=user_id if isinstance(user_id, int) else None,
        ),
        source_ref=item.managed_source_ref,
        memory_item_id=item.id,
        display_name=str(metadata.get("display_name") or ""),
        display_name_override=name if name is not None else str(metadata.get("display_name_override") or "") or None,
        previous_metadata=dict(metadata),
        identities=projection_identities,
    )
    if identities is not None:
        db = get_db()
        try:
            async with db.begin_nested():
                await db.execute(delete(MemoryContactIdentity).where(MemoryContactIdentity.contact_item_id == item.id))
                db.add_all([MemoryContactIdentity(
                    id=identity.id or uuid4(), owner_agent_id=item.owner_agent_id,
                    contact_item_id=item.id, identity_kind=identity.kind,
                    namespace=identity.namespace, external_id=identity.external_id,
                    display_name=identity.display_name, galaris_user_id=identity.galaris_user_id,
                    created_at=next((row.created_at for row in rows if row.id == identity.id), datetime.now(timezone.utc)),
                ) for identity in identities])
                await db.flush()
        except IntegrityError as exc:
            raise service.MemoryConflictError("An identity is already linked to another contact or its user no longer exists.") from exc
    try:
        await service.upsert_source_managed_item(document, defer_commit=defer_commit)
    except Exception:
        # Projection preparation can fail before its own transaction guard.
        # Discard the identity writes as well, even when a caller handles the error.
        await get_db().rollback()
        raise
    record = await get_messenger_contact(contact_item_id)
    if record is None:
        raise service.MemoryNotFoundError("Contact not found.")
    return record


async def _validate_identity_updates(
    owner_agent_id: int, contact_item_id: UUID, rows: tuple[MemoryContactIdentity, ...],
    identities: tuple[MessengerContactIdentityInput, ...],
) -> None:
    ids = {row.id for row in rows}
    seen_ids: set[UUID] = set()
    addresses: set[tuple[str, str, str]] = set()
    for identity in identities:
        if identity.kind == "messenger" and identity.namespace == "internal":
            raise service.MemoryConflictError("Use a Galaris user identity for internal Chat.")
        if identity.id is not None:
            if identity.id not in ids or identity.id in seen_ids:
                raise service.MemoryConflictError("An identity does not belong to this contact or occurs twice.")
            seen_ids.add(identity.id)
        address = (identity.kind, identity.namespace, identity.external_id)
        if address in addresses:
            raise service.MemoryConflictError("Each identity must occur only once.")
        addresses.add(address)
        if identity.kind == "galaris_user":
            if identity.namespace != "galaris" or identity.galaris_user_id is None or identity.external_id != str(identity.galaris_user_id):
                raise service.MemoryConflictError("Invalid Galaris user identity.")
            if await get_user_record(identity.galaris_user_id) is None:
                raise service.MemoryConflictError("Galaris user not found.")
        elif identity.galaris_user_id is not None:
            raise service.MemoryConflictError("A messaging identity must not set a Galaris user.")
        if not identity.namespace.strip() or not identity.external_id.strip():
            raise service.MemoryConflictError("An identity requires a namespace and an identifier.")
        if (len(identity.namespace) > 512 or len(identity.external_id) > 512
            or len(identity.display_name) > 500 or len(identities) > 500):
            raise service.MemoryConflictError("Contact identity limits exceeded.")
        occupied = await get_db().scalar(select(MemoryContactIdentity.id).where(
            MemoryContactIdentity.owner_agent_id == owner_agent_id,
            MemoryContactIdentity.identity_kind == identity.kind,
            MemoryContactIdentity.namespace == identity.namespace,
            MemoryContactIdentity.external_id == identity.external_id,
            MemoryContactIdentity.contact_item_id != contact_item_id,
        ))
        if occupied is not None:
            raise service.MemoryConflictError("An identity is already linked to another contact. Merge the contacts to combine them.")


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

    try:
        coordinates = ContactCoordinates.model_validate(target.metadata_.get("coordinates", {})).merged_with(
            ContactCoordinates.model_validate(source.metadata_.get("coordinates", {}))
        )
    except ValueError as exc:
        raise service.MemoryConflictError("The merged contact exceeds the coordinate limit.") from exc

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
        "coordinates": coordinates.model_dump(),
        "merged_contact_item_ids": list(dict.fromkeys(merged_ids)),
        **({"identities_managed": True} if source.metadata_.get("identities_managed") else {}),
    }
    if coordinates.phone_numbers or coordinates.postal_addresses:
        await update_messenger_contact(contact_item_id=target.id, display_name=None,
            coordinates=coordinates, defer_commit=True)
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
        if memory.source_managed or memory.deletion_protected or memory.node_kind == "document":
            raise service.MemoryConflictError(
                "A protected, source-managed or document-linked memory cannot be forgotten."
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
    "contact_labels",
    "get_messenger_contact",
    "forget_messenger_contact",
    "list_messenger_contacts",
    "merge_messenger_contacts",
    "update_messenger_contact",
]
