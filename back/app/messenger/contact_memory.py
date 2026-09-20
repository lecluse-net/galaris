"""Project observed human senders from Messenger into governed Memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, cast
from uuid import UUID

from loguru import logger
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import exists, func, select, update
from sqlalchemy.sql.selectable import Subquery

from app.connection import Connection
from app.memory import MemoryItem, MessengerContactObservation, observe_messenger_contact
from app.tools import ToolModel
from core.database import get_db

from . import directory, facade
from .models import Message, MessengerUser


_BACKFILL_BATCH_SIZE = 500
_MAX_FAILURES = 100
_CONTACT_MESSAGING_KINDS = frozenset(
    {"mail", "matrix", "nextcloud_talk", "one_bot", "telegram", "whatsapp"}
)
_EMAIL_ADAPTER: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class MessengerContactRebuildResult:
    """Bounded and auditable summary of one canonical-journal replay."""

    rows_scanned: int = 0
    contacts_synced: int = 0
    ai_senders_skipped: int = 0
    invalid_senders_skipped: int = 0
    journal_rows_linked: int = 0
    output_messages_linked: int = 0
    conversation_rounds_linked: int = 0
    tasks_linked: int = 0
    failures: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


async def observe_incoming_contact(
    message: Message,
    *,
    owner_agent_id: int,
    messaging_id: str,
) -> UUID | None:
    """Fail-open runtime adapter from one canonical sender to Memory."""

    sender = message.sender
    if sender is None:
        return None
    return await observe_contact(
        owner_agent_id=owner_agent_id,
        messaging_id=messaging_id,
        user_id=sender.external_id,
        display_name=sender.display_name,
        is_ai=sender.is_ai,
        galaris_user_id=sender.galaris_user_id,
    )


def _canonical_contact_user_id(messaging_id: str, user_id: str) -> str:
    """Normalize identities only where the transport defines a canonical form."""

    if messaging_id == "mail":
        return str(_EMAIL_ADAPTER.validate_python(user_id)).casefold()
    return user_id


async def observe_contact(
    *,
    owner_agent_id: int,
    messaging_id: str,
    user_id: str,
    display_name: str = "",
    is_ai: bool = False,
    galaris_user_id: int | None = None,
) -> UUID | None:
    """Fail-open public projection of one observed account into private Memory."""

    if is_ai or not user_id.strip():
        return None
    try:
        canonical_user_id = _canonical_contact_user_id(messaging_id, user_id)
        return await observe_messenger_contact(
            MessengerContactObservation(
                owner_agent_id=owner_agent_id,
                messaging_id=messaging_id,
                user_id=canonical_user_id,
                display_name=display_name,
                galaris_user_id=galaris_user_id,
            )
        )
    except Exception as exc:
        logger.opt(exception=True).error(
            "Messenger contact projection failed: owner_agent_id={} "
            "messaging_id={} error_type={}",
            owner_agent_id,
            messaging_id,
            type(exc).__name__,
        )
        return None


def _messaging_kind(tool: ToolModel | None) -> str | None:
    if tool is None or not isinstance(tool.messenger_config, Mapping):
        return None
    config = cast(Mapping[str, Any], tool.messenger_config)
    service = config.get("service")
    kind = facade.normalize_kind(str(service)) if service is not None else None
    if kind not in _CONTACT_MESSAGING_KINDS:
        return None
    return kind


def _display_name(metadata: object, user_id: str) -> str:
    if isinstance(metadata, Mapping):
        mapping = cast(Mapping[str, object], metadata)
        value = str(mapping.get("sender_display_name") or "")
        if value:
            return value
    return user_id


def _latest_inbound_sender_rows() -> Subquery:
    row_number = func.row_number().over(
        partition_by=(
            Message.connection_id,
            Message.user_id,
        ),
        order_by=(
            Message.created_at.desc(),
            Message.id.desc(),
        ),
    )
    return (
        select(
            Message.id.label("id"),
            Message.connection_id.label("connection_id"),
            Message.user_id.label("user_id"),
            Message.metadata_.label("metadata"),
            Message.created_at.label("created_at"),
            row_number.label("sender_row_number"),
        )
        .where(
            Message.direction == "inbound",
            Message.user_id.is_not(None),
        )
        .subquery()
    )


def _bounded_failures(
    failures: list[str],
    *,
    failure_count: int,
) -> tuple[str, ...]:
    if failure_count <= len(failures):
        return tuple(failures)
    retained = failures[: _MAX_FAILURES - 1]
    retained.append(f"additional_failures={failure_count - len(retained)}")
    return tuple(retained)


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return value if isinstance(value, int) else 0


async def rebuild_messenger_contacts(
    *,
    batch_size: int = _BACKFILL_BATCH_SIZE,
) -> MessengerContactRebuildResult:
    """Replay the newest known inbound sender for each current connection."""

    safe_batch_size = max(1, min(int(batch_size), _BACKFILL_BATCH_SIZE))
    latest = _latest_inbound_sender_rows()
    db = get_db()
    offset = 0
    rows_scanned = 0
    contacts_synced = 0
    ai_senders_skipped = 0
    invalid_senders_skipped = 0
    failure_count = 0
    failures: list[str] = []
    synced_scopes: set[tuple[int, str, str]] = set()
    journal_rows_linked = 0

    while True:
        rows = (
            await db.execute(
                select(
                    latest.c.connection_id,
                    latest.c.user_id,
                    latest.c.metadata,
                )
                .where(latest.c.sender_row_number == 1)
                .order_by(latest.c.created_at.desc(), latest.c.id.desc())
                .offset(offset)
                .limit(safe_batch_size)
            )
        ).all()
        if not rows:
            break
        offset += len(rows)
        rows_scanned += len(rows)

        connection_ids = {int(row.connection_id) for row in rows}
        connections = {
            int(connection.id): connection
            for connection in (
                await db.scalars(
                    select(Connection).where(Connection.id.in_(connection_ids))
                )
            ).all()
        }
        tool_ids = {
            int(connection.tool_id)
            for connection in connections.values()
        }
        tools = {
            int(tool.id): tool
            for tool in (
                await db.scalars(
                    select(ToolModel).where(ToolModel.id.in_(tool_ids))
                )
            ).all()
        }

        for row in rows:
            connection_id = int(row.connection_id)
            connection = connections.get(connection_id)
            user_id = str(row.user_id or "")
            if connection is None or not user_id.strip() or len(user_id) > 512:
                invalid_senders_skipped += 1
                continue
            tool = tools.get(int(connection.tool_id))
            messaging_id = _messaging_kind(tool)
            if messaging_id is None:
                invalid_senders_skipped += 1
                continue
            resolved_sender = await directory.resolve_user(
                int(connection.tool_id),
                user_id,
            )
            if resolved_sender.is_ai:
                ai_senders_skipped += 1
                continue
            canonical_sender = await db.scalar(
                select(MessengerUser).where(
                    MessengerUser.tool_id == int(connection.tool_id),
                    MessengerUser.external_id == user_id,
                )
            )
            try:
                canonical_user_id = _canonical_contact_user_id(
                    messaging_id,
                    user_id,
                )
            except ValueError:
                invalid_senders_skipped += 1
                continue
            scope = (
                int(connection.agent_id),
                messaging_id,
                canonical_user_id,
            )
            if scope in synced_scopes:
                continue
            try:
                contact_item_id = await observe_messenger_contact(
                    MessengerContactObservation(
                        owner_agent_id=int(connection.agent_id),
                        messaging_id=messaging_id,
                        user_id=canonical_user_id,
                        display_name=_display_name(row.metadata, user_id),
                        galaris_user_id=(
                            canonical_sender.galaris_user_id
                            if canonical_sender is not None
                            else None
                        ),
                    )
                )
            except Exception as exc:
                failure_count += 1
                if len(failures) < _MAX_FAILURES:
                    failures.append(
                        f"connection_id={connection_id} "
                        f"messaging_id={messaging_id} "
                        f"error_type={type(exc).__name__}"
                    )
                logger.opt(exception=True).error(
                    "Messenger contact backfill failed: connection_id={} "
                    "owner_agent_id={} messaging_id={} error_type={}",
                    connection_id,
                    connection.agent_id,
                    messaging_id,
                    type(exc).__name__,
                )
                continue
            if await db.get(MemoryItem, contact_item_id) is not None:
                await db.execute(
                    update(Message)
                    .where(
                        Message.connection_id == connection_id,
                        Message.direction == "inbound",
                        Message.user_id == user_id,
                        Message.contact_memory_item_id.is_distinct_from(
                            contact_item_id
                        ),
                    )
                    .values(contact_memory_item_id=contact_item_id)
                )
                journal_rows_linked += int(
                    await db.scalar(
                        select(func.count(Message.id)).where(
                            Message.connection_id == connection_id,
                            Message.direction == "inbound",
                            Message.user_id == user_id,
                            Message.contact_memory_item_id
                            == contact_item_id,
                        )
                    )
                    or 0
                )
            synced_scopes.add(scope)
            contacts_synced += 1

    from app.conversation import (
        ConversationRound,
        ConversationRoundMessage,
        ConversationTaskLink,
    )
    from app.task import Task

    round_contact = (
        select(Message.contact_memory_item_id)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "input",
            Message.contact_memory_item_id.is_not(None),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    linked_rounds = await db.execute(
        update(ConversationRound)
        .where(
            ConversationRound.contact_memory_item_id.is_(None),
            exists(
                select(Message.id).where(
                    exists(
                        select(ConversationRoundMessage.message_id).where(
                            ConversationRoundMessage.round_id
                            == ConversationRound.id,
                            ConversationRoundMessage.message_id == Message.id,
                            ConversationRoundMessage.role == "input",
                        )
                    ),
                    Message.contact_memory_item_id.is_not(None),
                )
            ),
        )
        .values(contact_memory_item_id=round_contact)
    )
    output_contact = (
        select(ConversationRound.contact_memory_item_id)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.round_id == ConversationRound.id,
        )
        .where(
            ConversationRoundMessage.message_id == Message.id,
            ConversationRoundMessage.role == "output",
            ConversationRound.contact_memory_item_id.is_not(None),
        )
        .limit(1)
        .scalar_subquery()
    )
    linked_outputs = await db.execute(
        update(Message)
        .where(
            Message.contact_memory_item_id.is_(None),
            exists(
                select(ConversationRoundMessage.message_id)
                .join(
                    ConversationRound,
                    ConversationRound.id == ConversationRoundMessage.round_id,
                )
                .where(
                    ConversationRoundMessage.message_id == Message.id,
                    ConversationRoundMessage.role == "output",
                    ConversationRound.contact_memory_item_id.is_not(None),
                )
            ),
        )
        .values(contact_memory_item_id=output_contact)
    )
    task_contact = (
        select(ConversationRound.contact_memory_item_id)
        .join(
            ConversationTaskLink,
            ConversationTaskLink.round_id == ConversationRound.id,
        )
        .where(
            ConversationTaskLink.task_id == Task.id,
            ConversationRound.contact_memory_item_id.is_not(None),
        )
        .order_by(ConversationRound.created_at)
        .limit(1)
        .scalar_subquery()
    )
    linked_tasks = await db.execute(
        update(Task)
        .where(
            Task.contact_memory_item_id.is_(None),
            exists(
                select(ConversationTaskLink.id)
                .join(
                    ConversationRound,
                    ConversationRound.id == ConversationTaskLink.round_id,
                )
                .where(
                    ConversationTaskLink.task_id == Task.id,
                    ConversationRound.contact_memory_item_id.is_not(None),
                )
            ),
        )
        .values(contact_memory_item_id=task_contact)
    )
    await db.commit()

    return MessengerContactRebuildResult(
        rows_scanned=rows_scanned,
        contacts_synced=contacts_synced,
        ai_senders_skipped=ai_senders_skipped,
        invalid_senders_skipped=invalid_senders_skipped,
        journal_rows_linked=journal_rows_linked,
        output_messages_linked=_rowcount(linked_outputs),
        conversation_rounds_linked=_rowcount(linked_rounds),
        tasks_linked=_rowcount(linked_tasks),
        failures=_bounded_failures(failures, failure_count=failure_count),
    )


__all__ = [
    "MessengerContactRebuildResult",
    "observe_contact",
    "observe_incoming_contact",
    "rebuild_messenger_contacts",
]
