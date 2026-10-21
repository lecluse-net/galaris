"""Deterministic private-memory projection of human Messenger contacts."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import get_db

from . import service
from .contracts import MessengerContactIdentityInput, MessengerContactObservation, SourceMemoryDocument
from .models import MemoryContactIdentity, MemoryItem


MESSENGER_CONTACT_SOURCE_KIND = "messenger_contact"
MESSENGER_CONTACT_PROJECTION_VERSION = 1
_MAX_IDENTITY_LENGTH = 512
_MAX_DISPLAY_NAME_LENGTH = 500
_MARKDOWN_INLINE_CHARS = frozenset("\\`*_{}[]<>()#+-.!|")


def _validate_observation(
    observation: MessengerContactObservation,
) -> MessengerContactObservation:
    if observation.owner_agent_id <= 0:
        raise ValueError("A Messenger contact requires a positive owner agent.")
    if (
        not observation.messaging_id
        or not observation.messaging_id.strip()
        or observation.messaging_id != observation.messaging_id.strip()
    ):
        raise ValueError("A canonical Messenger messaging_id is required.")
    if len(observation.messaging_id) > _MAX_IDENTITY_LENGTH:
        raise ValueError("Messenger messaging_id exceeds the 512 character limit.")
    if not observation.user_id or not observation.user_id.strip():
        raise ValueError("A Messenger contact user_id is required.")
    if len(observation.user_id) > _MAX_IDENTITY_LENGTH:
        raise ValueError("Messenger user_id exceeds the 512 character limit.")
    return observation


def _projection_ref(observation: MessengerContactObservation) -> str:
    payload = json.dumps(
        [
            MESSENGER_CONTACT_PROJECTION_VERSION,
            observation.owner_agent_id,
            observation.messaging_id,
            observation.user_id,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bounded_display_name(value: str) -> str:
    return " ".join(value.split())[:_MAX_DISPLAY_NAME_LENGTH].strip()


def _plain_inline(value: str) -> str:
    return " ".join(value.split())[:_MAX_IDENTITY_LENGTH]


def _markdown_inline(value: str) -> str:
    bounded = _plain_inline(value)
    return "".join(
        f"\\{character}" if character in _MARKDOWN_INLINE_CHARS else character
        for character in bounded
    )


def contact_document(
    observation: MessengerContactObservation,
    *,
    source_ref: str,
    memory_item_id: UUID | None,
    display_name: str,
    display_name_override: str | None = None,
    previous_metadata: dict[str, object] | None = None,
    identities: tuple[MessengerContactIdentityInput, ...] | None = None,
) -> SourceMemoryDocument:
    observed_display_name = display_name
    display_name = display_name_override or display_name
    presentation_name = display_name or observation.user_id
    safe_name = _markdown_inline(presentation_name)
    safe_display_name = _markdown_inline(display_name or observation.user_id)
    safe_messaging_id = _plain_inline(observation.messaging_id)
    safe_user_id = _plain_inline(observation.user_id)
    content = "\n".join(
        (
            "# Contact Messenger",
            "",
            f"- Nom affiché : {safe_display_name}",
            f"- Messagerie : {safe_messaging_id}",
            f"- Identifiant utilisateur : {safe_user_id}",
            *(
                (f"- Compte Galaris : {observation.galaris_user_id}",)
                if observation.galaris_user_id is not None
                else ()
            ),
            "",
        )
    )
    keywords = [
        "contact",
        "messenger",
        f"messaging:{observation.messaging_id}",
        f"user:{observation.user_id}",
    ]
    if display_name:
        keywords.append(display_name)
    if observation.galaris_user_id is not None:
        keywords.append(f"galaris_user:{observation.galaris_user_id}")
    if observation.messaging_id == "internal" and observation.galaris_user_id is not None:
        content = "\n".join((
            "# Contact Messenger", "", f"- Nom affiché : {safe_display_name}",
            f"- Compte Galaris : {observation.galaris_user_id}", "",
        ))
        keywords = ["contact", "messenger", f"galaris_user:{observation.galaris_user_id}"]
        if display_name:
            keywords.append(display_name)
    if identities is not None:
        content = "\n".join((
            "# Contact Messenger", "", f"- Nom affiché : {safe_display_name}",
            *(f"- {_markdown_inline(identity.namespace)} : {_markdown_inline(identity.external_id)}"
              + (f" — {_markdown_inline(identity.display_name)}" if identity.display_name else "")
              for identity in identities), "",
        ))
        keywords = ["contact", "messenger", display_name]
        for identity in identities:
            keywords.extend((identity.namespace, identity.external_id, identity.display_name))
    metadata: dict[str, object] = {
        **(previous_metadata or {}),
        "projection_version": MESSENGER_CONTACT_PROJECTION_VERSION,
        "source_kind": MESSENGER_CONTACT_SOURCE_KIND,
        "messaging_id": observation.messaging_id,
        "user_id": observation.user_id,
        "display_name": observed_display_name,
    }
    if display_name_override:
        metadata["display_name_override"] = display_name_override
    if identities is not None:
        metadata["identities_managed"] = True
    if observation.galaris_user_id is not None:
        metadata["galaris_user_id"] = observation.galaris_user_id
    if identities is not None:
        metadata.pop("galaris_user_id", None)
    return SourceMemoryDocument(
        source_kind=MESSENGER_CONTACT_SOURCE_KIND,
        source_ref=source_ref,
        owner_agent_id=observation.owner_agent_id,
        memory_item_id=memory_item_id,
        title=f"Contact — {safe_name}",
        content=content,
        filename=f"messenger-contact-{source_ref}.md",
        keywords=tuple(keywords),
        metadata=metadata,
    )


async def _existing_projection(source_ref: str) -> MemoryItem | None:
    return await get_db().scalar(
        select(MemoryItem).where(
            MemoryItem.source_managed.is_(True),
            MemoryItem.managed_source_kind == MESSENGER_CONTACT_SOURCE_KIND,
            MemoryItem.managed_source_ref == source_ref,
        ).with_for_update().execution_options(populate_existing=True)
    )


async def _observe_once(
    observation: MessengerContactObservation,
    *, source_ref: str | None = None,
) -> UUID:
    source_ref = source_ref or _projection_ref(observation)
    existing = await _existing_projection(source_ref)
    while existing is not None and existing.metadata_.get("identities_managed"):
        # The old address no longer owns this manually managed contact. A new
        # observation may create a separate contact, without restoring the removed address.
        # A deterministic successor lets concurrent observations converge on the
        # same new projection before either has attached the strong identity.
        source_ref = hashlib.sha256(f"{source_ref}:{existing.id}".encode()).hexdigest()
        existing = await _existing_projection(source_ref)
    display_name = _bounded_display_name(observation.display_name)
    if not display_name and existing is not None:
        display_name = _bounded_display_name(
            str(existing.metadata_.get("display_name") or "")
        )
    document = contact_document(
        observation,
        source_ref=source_ref,
        memory_item_id=existing.id if existing is not None else None,
        display_name=display_name,
        display_name_override=(
            str(existing.metadata_.get("display_name_override") or "") or None
            if existing is not None else None
        ),
        previous_metadata=dict(existing.metadata_) if existing is not None else None,
    )
    item = await service.upsert_source_managed_item(document)
    return item.id


async def _identity_contact_item_id(
    *,
    owner_agent_id: int,
    identity_kind: str,
    namespace: str,
    external_id: str,
) -> UUID | None:
    return await get_db().scalar(
        select(MemoryContactIdentity.contact_item_id).where(
            MemoryContactIdentity.owner_agent_id == owner_agent_id,
            MemoryContactIdentity.identity_kind == identity_kind,
            MemoryContactIdentity.namespace == namespace,
            MemoryContactIdentity.external_id == external_id,
        )
    )


async def _ensure_identity(
    *,
    contact_item_id: UUID,
    owner_agent_id: int,
    identity_kind: str,
    namespace: str,
    external_id: str,
    display_name: str,
    galaris_user_id: int | None = None,
) -> None:
    contact = await get_db().scalar(
        select(MemoryItem).where(MemoryItem.id == contact_item_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if contact is not None and contact.metadata_.get("identities_managed"):
        return
    identity = await get_db().scalar(
        select(MemoryContactIdentity).where(
            MemoryContactIdentity.owner_agent_id == owner_agent_id,
            MemoryContactIdentity.identity_kind == identity_kind,
            MemoryContactIdentity.namespace == namespace,
            MemoryContactIdentity.external_id == external_id,
        )
    )
    if identity is not None:
        if identity.contact_item_id == contact_item_id and display_name:
            identity.display_name = display_name
        return
    get_db().add(
        MemoryContactIdentity(
            owner_agent_id=owner_agent_id,
            contact_item_id=contact_item_id,
            identity_kind=identity_kind,
            namespace=namespace,
            external_id=external_id,
            display_name=display_name,
            galaris_user_id=galaris_user_id,
        )
    )


async def _observe_and_attach_identities(
    observation: MessengerContactObservation,
) -> UUID:
    source_ref = _projection_ref(observation)
    channel_contact_id = await _identity_contact_item_id(
        owner_agent_id=observation.owner_agent_id,
        identity_kind="messenger",
        namespace=observation.messaging_id,
        external_id=observation.user_id,
    )
    existing_projection = await _existing_projection(source_ref)
    if existing_projection is not None and existing_projection.metadata_.get("identities_managed"):
        existing_projection = None
    user_contact_id = (
        await _identity_contact_item_id(
            owner_agent_id=observation.owner_agent_id,
            identity_kind="galaris_user",
            namespace="galaris",
            external_id=str(observation.galaris_user_id),
        )
        if observation.galaris_user_id is not None
        else None
    )
    contact_item_id = (
        channel_contact_id
        or (existing_projection.id if existing_projection is not None else None)
        or user_contact_id
    )
    if contact_item_id is None:
        contact_item_id = await _observe_once(observation)
    else:
        contact = await get_db().scalar(
            select(MemoryItem).where(MemoryItem.id == contact_item_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if contact is not None and contact.metadata_.get("identities_managed"):
            # An explicit human snapshot remains authoritative across inbound
            # messages and directory reconciliation, including names and removals.
            await get_db().commit()
            return contact_item_id
        # Preserve the historical rename behavior for the identity that owns the
        # source projection. Aliases attached after a merge must not recreate it.
        if contact is not None and (
            contact.metadata_.get("messaging_id") == observation.messaging_id
            and contact.metadata_.get("user_id") == observation.user_id
        ):
            contact_item_id = await _observe_once(observation, source_ref=contact.managed_source_ref)

    display_name = _bounded_display_name(observation.display_name)
    if observation.messaging_id != "internal" or observation.galaris_user_id is None:
        await _ensure_identity(
            contact_item_id=contact_item_id,
            owner_agent_id=observation.owner_agent_id,
            identity_kind="messenger",
            namespace=observation.messaging_id,
            external_id=observation.user_id,
            display_name=display_name,
        )
    if observation.galaris_user_id is not None:
        await _ensure_identity(
            contact_item_id=contact_item_id,
            owner_agent_id=observation.owner_agent_id,
            identity_kind="galaris_user",
            namespace="galaris",
            external_id=str(observation.galaris_user_id),
            display_name=display_name,
            galaris_user_id=observation.galaris_user_id,
        )
    await get_db().commit()
    return contact_item_id


async def observe_messenger_contact(
    observation: MessengerContactObservation,
) -> UUID:
    """Create or refresh one agent-private social memory from an inbound identity."""

    validated = _validate_observation(observation)
    try:
        return await _observe_and_attach_identities(validated)
    except IntegrityError:
        # First observations can race on either the source projection or one
        # strong identity. Re-read after rollback to converge on the winner.
        await get_db().rollback()
        return await _observe_and_attach_identities(validated)


__all__ = [
    "MESSENGER_CONTACT_PROJECTION_VERSION",
    "MESSENGER_CONTACT_SOURCE_KIND",
    "observe_messenger_contact",
]
