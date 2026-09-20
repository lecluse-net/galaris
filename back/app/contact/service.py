"""Contact administration over Memory and canonical conversation references."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import update

from app.conversation import ConversationRound
from app.memory import (
    MessengerContactRecord,
    forget_messenger_contact,
    list_messenger_contacts,
    merge_messenger_contacts,
)
from app.messenger import Message, search_agent_users
from app.task import Task
from core.database import get_db

from .contracts import ReachableHumanContact
from .schemas import (
    ContactIdentityRead,
    ContactForgetResult,
    ContactMergeResult,
    ContactPage,
    ContactRead,
)


async def _canonical_contact_index(
    owner_agent_id: int,
) -> tuple[
    dict[tuple[str, str], MessengerContactRecord],
    dict[int, MessengerContactRecord],
]:
    """Index all canonical contacts by their strong Messenger and user identities."""

    by_messenger: dict[tuple[str, str], MessengerContactRecord] = {}
    by_galaris_user: dict[int, MessengerContactRecord] = {}
    offset = 0
    while True:
        records, _total = await list_messenger_contacts(
            owner_agent_id=owner_agent_id,
            limit=500,
            offset=offset,
        )
        for record in records:
            for identity in record.identities:
                if identity.kind == "messenger":
                    by_messenger[(identity.namespace, identity.external_id)] = record
                elif identity.galaris_user_id is not None:
                    by_galaris_user[identity.galaris_user_id] = record
        if len(records) < 500:
            break
        offset += len(records)
    return by_messenger, by_galaris_user


async def list_reachable_humans(
    *, agent_id: int, query: str = ""
) -> tuple[ReachableHumanContact, ...]:
    """List reachable humans and collapse routes belonging to one canonical contact."""

    identities = await search_agent_users(agent_id, query)
    by_messenger, by_galaris_user = await _canonical_contact_index(agent_id)
    contacts: dict[tuple[str, object], ReachableHumanContact] = {}
    for connection_id, tool_id, platform, user in identities:
        if user.is_ai or user.agent_id is not None:
            continue
        canonical = by_messenger.get((platform, user.external_id))
        if canonical is None and user.galaris_user_id is not None:
            canonical = by_galaris_user.get(user.galaris_user_id)
        if canonical is not None:
            key: tuple[str, object] = ("contact", canonical.memory_item_id)
        elif user.galaris_user_id is not None:
            key = ("galaris_user", user.galaris_user_id)
        else:
            key = ("messenger_user", user.id)
        contacts.setdefault(
            key,
            ReachableHumanContact(
                connection_id=connection_id,
                tool_id=tool_id,
                platform=platform,
                user_id=user.external_id,
                display_name=(
                    canonical.display_name
                    if canonical is not None
                    else (user.display_name or user.external_id)
                ),
                contact_item_id=(
                    canonical.memory_item_id if canonical is not None else None
                ),
                galaris_user_id=user.galaris_user_id,
            ),
        )
    return tuple(
        sorted(
            contacts.values(),
            key=lambda contact: (
                contact.display_name.casefold(),
                contact.platform,
                contact.connection_id,
                contact.user_id,
            ),
        )
    )


def _read(record: MessengerContactRecord) -> ContactRead:
    return ContactRead(
        memory_item_id=record.memory_item_id,
        owner_agent_id=record.owner_agent_id,
        display_name=record.display_name,
        memory_title=record.title,
        identities=[
            ContactIdentityRead(
                id=identity.id,
                kind=identity.kind,
                namespace=identity.namespace,
                external_id=identity.external_id,
                display_name=identity.display_name,
                galaris_user_id=identity.galaris_user_id,
            )
            for identity in record.identities
        ],
        linked_memory_count=record.linked_memory_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def list_contacts(
    *, agent_id: int, query: str, limit: int, offset: int
) -> ContactPage:
    records, total = await list_messenger_contacts(
        owner_agent_id=agent_id,
        query=query,
        limit=limit,
        offset=offset,
    )
    return ContactPage(
        items=[_read(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(records) < total,
    )


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return value if isinstance(value, int) else 0


async def _rewire_conversation_references(
    source_contact_item_id: UUID, target_contact_item_id: UUID
) -> dict[str, int]:
    messages = await get_db().execute(
        update(Message)
        .where(Message.contact_memory_item_id == source_contact_item_id)
        .values(contact_memory_item_id=target_contact_item_id)
    )
    rounds = await get_db().execute(
        update(ConversationRound)
        .where(
            ConversationRound.contact_memory_item_id == source_contact_item_id
        )
        .values(contact_memory_item_id=target_contact_item_id)
    )
    tasks = await get_db().execute(
        update(Task)
        .where(Task.contact_memory_item_id == source_contact_item_id)
        .values(contact_memory_item_id=target_contact_item_id)
    )
    return {
        "messages": _rowcount(messages),
        "conversation_rounds": _rowcount(rounds),
        "tasks": _rowcount(tasks),
    }


async def _clear_conversation_references(
    contact_item_id: UUID,
) -> dict[str, int]:
    messages = await get_db().execute(
        update(Message)
        .where(Message.contact_memory_item_id == contact_item_id)
        .values(contact_memory_item_id=None)
    )
    rounds = await get_db().execute(
        update(ConversationRound)
        .where(ConversationRound.contact_memory_item_id == contact_item_id)
        .values(contact_memory_item_id=None)
    )
    tasks = await get_db().execute(
        update(Task)
        .where(Task.contact_memory_item_id == contact_item_id)
        .values(contact_memory_item_id=None)
    )
    return {
        "messages": _rowcount(messages),
        "conversation_rounds": _rowcount(rounds),
        "tasks": _rowcount(tasks),
    }


async def merge_contacts(
    *, source_contact_item_id: UUID, target_contact_item_id: UUID
) -> ContactMergeResult:
    merged, rewired = await merge_messenger_contacts(
        source_contact_item_id=source_contact_item_id,
        target_contact_item_id=target_contact_item_id,
        rewire_references=_rewire_conversation_references,
    )
    return ContactMergeResult(contact=_read(merged), rewired=rewired)


async def forget_contact(*, contact_item_id: UUID) -> ContactForgetResult:
    cleared = await forget_messenger_contact(
        contact_item_id=contact_item_id,
        clear_references=_clear_conversation_references,
    )
    return ContactForgetResult(
        forgotten_contact_item_id=contact_item_id,
        forgotten_memories=cleared.pop("memories", 0),
        resources_deleted=cleared.pop("resources", 0),
        cleared=cleared,
    )


__all__ = [
    "forget_contact",
    "list_contacts",
    "list_reachable_humans",
    "merge_contacts",
]
