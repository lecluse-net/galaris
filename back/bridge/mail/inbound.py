"""Durable email admission, governed by the common per-connection authorization policy."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import defer

from app.connection import facade as connections
from app.contact.facade import is_known_mail_contact
from app.messenger import Message, dispatch_incoming, register_inbound_contact_authorizer
from app.tools.facade import (
    AuthorizationAction, AuthorizationClosed, AuthorizationRequired, AuthorizationReview,
    authorization_reviews, claim_action, finish_action, get_tool_by_id,
    register_authorization_context_guard, register_authorization_waker,
    register_runtime_authorization_waiter,
    tool_authorization_configuration, authorization_fingerprint, wake_authorization_context,
)
from app.tools.contracts import ToolCallRejectedError, current_tool_execution
from core.database import get_db

from .connection_service import resolve_connection
from .contracts import MailConnectionConfig, MailMessageDetail, MailMessageRef, MailMessageSummary
from .imap_client import ImapClient
from .models import MailInboundReceipt
from .schemas import MailInboundDetail, MailInboundItem, MailInboundPage

PROCESS_NAME = "mail_process"
PROCESS_REASON = "Email processing requires consent unless its sender is already a contact"
_CONTEXT_PREFIX = "mail-inbound"


def _require_inbox(message_ref: str) -> None:
    if MailMessageRef.decode(message_ref).mailbox.upper() != "INBOX":
        raise PermissionError("Only messages in INBOX can be processed")


async def record_receipt(
    config: MailConnectionConfig, summary: MailMessageSummary, *, dispatch: bool = False,
) -> MailInboundReceipt:
    """Deduplicate before the poll cursor advances; receipt does not read the message."""
    _require_inbox(summary.ref)
    db = get_db()
    await db.execute(insert(MailInboundReceipt).values(
        id=uuid4(), connection_id=config.connection_id, agent_id=config.agent_id,
        agent_label=config.agent_label, message_ref=summary.ref,
        sender_address=summary.from_address, subject=summary.subject,
        summary=summary.model_dump(mode="json"), dispatch_requested=dispatch,
        known_contact=False, status="received",
    ).on_conflict_do_nothing(constraint="uq_mail_inbound_connection_ref"))
    if dispatch:
        await db.execute(update(MailInboundReceipt).where(
            MailInboundReceipt.connection_id == config.connection_id,
            MailInboundReceipt.message_ref == summary.ref,
        ).values(dispatch_requested=True))
    await db.commit()
    row = await db.scalar(select(MailInboundReceipt).where(
        MailInboundReceipt.connection_id == config.connection_id,
        MailInboundReceipt.message_ref == summary.ref,
    ).execution_options(populate_existing=True))
    if row is None:
        raise RuntimeError("Mail receipt was not persisted")
    return row


async def _context(agent_id: int, key: str) -> dict[str, object] | None:
    try:
        identifier = UUID(key.split(":", 1)[1])
    except (ValueError, IndexError):
        return None
    row = await get_db().get(MailInboundReceipt, identifier, populate_existing=True)
    if row is None or row.agent_id != agent_id or row.connection_id is None:
        return None
    return {"receipt_id": str(row.id), "connection_id": row.connection_id, "summary": row.summary}


async def _runtime_waiter(agent_id: int, key: str, authorization_id: UUID, parent_context: str) -> bool:
    try:
        identifier = UUID(key.split(":", 1)[1])
    except (ValueError, IndexError):
        return False
    return bool(await get_db().scalar(select(MailInboundReceipt.id).where(
        MailInboundReceipt.id == identifier, MailInboundReceipt.agent_id == agent_id,
        MailInboundReceipt.authorization_id == authorization_id,
        MailInboundReceipt.waiting_contexts.contains([parent_context]),
    )))


async def authorize_receipt(row: MailInboundReceipt) -> None:
    """Grant this message only; explicit Ask/Blocked policies take precedence over contacts."""
    _require_inbox(row.message_ref)
    db = get_db()
    if row.connection_id is None or row.agent_id is None:
        raise PermissionError("Mail connection is no longer available")
    connection = await connections.get_connection(row.connection_id)
    if connection is None or not connection.active or connection.agent_id != row.agent_id:
        raise PermissionError("Mail connection is no longer available")
    policy = await connections.resolve_function(connection, PROCESS_NAME)
    tool = await get_tool_by_id(connection.tool_id)
    if tool is None:
        raise PermissionError("Mail tool is no longer available")
    _, params = await connections.get_params_as_dict(connection.id)
    configuration = {"tool": tool_authorization_configuration(tool), "params": params,
                     "classification": "ask", "reason": PROCESS_REASON}
    config_fingerprint = authorization_fingerprint(configuration)
    if policy["effective_state"] == "disabled":
        if row.authorized_at is None:
            row.status = "blocked"
            await db.commit()
        raise PermissionError("Mail processing is blocked")
    if row.status == "rejected":
        raise PermissionError("Mail processing was rejected")
    if row.authorized_at is not None:
        if row.configuration_fingerprint != config_fingerprint:
            raise PermissionError("Mail connection configuration changed after authorization")
        # Repair a crash after storing the local grant but before completing its receipt.
        await finish_action(row.authorization_id, receipt={"receipt_id": str(row.id), "message_ref": row.message_ref})
        return
    known = await is_known_mail_contact(agent_id=row.agent_id, address=row.sender_address)
    # An explicit per-agent or global Ask means every sender, including contacts.
    trusted_default = known and policy["policy_source"] == "software"
    row.known_contact = known
    await db.commit()  # claim_action uses independent short transactions.
    identifier: UUID | None = None
    if not trusted_default:
        action = AuthorizationAction(
            agent_id=row.agent_id, runtime="internal", source="mcp",
            context_key=f"{_CONTEXT_PREFIX}:{row.id}", callback_key=str(row.id),
            name=PROCESS_NAME, tool_id=connection.tool_id, connection_id=connection.id,
            arguments={"sender": row.sender_address, "subject": row.subject,
                       "message_ref": row.message_ref},
            configuration=configuration,
        )
        try:
            identifier = await claim_action(action)
        except (AuthorizationRequired, AuthorizationClosed) as decision:
            if isinstance(decision, AuthorizationClosed) and decision.status == "executing":
                # Recover a crash after the common claim but before the local grant commit.
                identifier = decision.request_id
            else:
                row.authorization_id = decision.request_id
                row.status = "pending_approval" if isinstance(decision, AuthorizationRequired) else "rejected"
                row.error = None if isinstance(decision, AuthorizationRequired) else decision.status
                await db.commit()
                raise
    row.authorization_id = identifier
    row.configuration_fingerprint = config_fingerprint
    row.authorized_at = datetime.now(timezone.utc)
    row.status, row.error = "authorized", None
    await db.commit()
    await finish_action(identifier, receipt={"receipt_id": str(row.id), "message_ref": row.message_ref})


async def ensure_readable(
    config: MailConnectionConfig, message_ref: str, *, parent_context: str | None = None,
) -> MailInboundReceipt:
    _require_inbox(message_ref)
    if parent_context is None and (execution := current_tool_execution()) is not None:
        # Covers generic file_* tools that materialize a Mail attachment.
        parent_context = execution.authorization_context
    row = await get_db().scalar(select(MailInboundReceipt).where(
        MailInboundReceipt.connection_id == config.connection_id,
        MailInboundReceipt.message_ref == message_ref,
    ).execution_options(populate_existing=True))
    if row is None:
        summary = await asyncio.to_thread(ImapClient(config).get_summary, MailMessageRef.decode(message_ref))
        row = await record_receipt(config, summary)
    if row.authorized_at is None and parent_context and parent_context.startswith(("task:", "round:")):
        # SQL concatenation preserves concurrent waiters; the wake deduplicates contexts.
        if parent_context not in row.waiting_contexts:
            registered = await get_db().scalar(update(MailInboundReceipt).where(
                MailInboundReceipt.id == row.id,
                func.jsonb_array_length(MailInboundReceipt.waiting_contexts) < 50,
            ).values(
                waiting_contexts=MailInboundReceipt.waiting_contexts + [parent_context]
            ).returning(MailInboundReceipt.id))
            await get_db().commit()
            if registered is None:
                raise ToolCallRejectedError("Too many contexts are waiting for this email")
    try:
        await authorize_receipt(row)
    except AuthorizationRequired as pending:
        # The enclosing Tool may be mail_get or file_read, whose continuation has a
        # different binding. Its retry reads this durable receipt after the wake.
        raise AuthorizationRequired(pending.request_id) from pending
    return row


async def record_read(row: MailInboundReceipt, detail: MailMessageDetail) -> None:
    # Preserve the initial bounded page; subsequent reads cannot replace it with a tail.
    previous_end = int(str((row.content or {}).get("body_end", 0)))
    if detail.body_start == 0 and detail.body_end >= previous_end:
        row.content = detail.model_dump(mode="json")
    row.read_at = datetime.now(timezone.utc)
    await get_db().commit()


async def process_receipt(identifier: UUID) -> None:
    db = get_db()
    row = await db.get(MailInboundReceipt, identifier, populate_existing=True)
    if row is None or row.admitted_at is not None or row.status == "rejected":
        return
    try:
        await authorize_receipt(row)
        if not row.dispatch_requested:
            return
        assert row.connection_id is not None
        connection = await connections.get_connection(row.connection_id)
        if connection is None:
            raise PermissionError("Mail connection was deleted")
        config = await resolve_connection(connection.id, require_active=True)
        if row.content is None:
            detail = await asyncio.to_thread(ImapClient(config).get_message,
                MailMessageRef.decode(row.message_ref), body_offset=0, body_limit=50_000)
            await record_read(row, detail)
        from .messenger import MailMessenger

        summary = MailMessageSummary.model_validate(row.summary)
        await dispatch_incoming(MailMessenger(config, tool_id=connection.tool_id).message(summary))
        row.status, row.error = "admitted", None
        row.admitted_at = datetime.now(timezone.utc)
        await db.commit()
    except (AuthorizationRequired, AuthorizationClosed):
        # A pending/closed decision must never stall the poll cursor or expose the body.
        return
    except (PermissionError, ToolCallRejectedError) as exc:
        await db.rollback()
        row = await db.get(MailInboundReceipt, identifier, populate_existing=True)
        if row is not None and row.admitted_at is None:
            row.status, row.error = "blocked", type(exc).__name__
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as exc:
        await db.rollback()
        row = await db.get(MailInboundReceipt, identifier, populate_existing=True)
        if row is not None:
            row.status, row.error = "error", type(exc).__name__
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()


async def receive(config: MailConnectionConfig, summary: MailMessageSummary) -> None:
    row = await record_receipt(config, summary, dispatch=True)
    await process_receipt(row.id)


async def resume_receipts(connection_id: int) -> None:
    identifiers = list(await get_db().scalars(select(MailInboundReceipt.id).where(
        MailInboundReceipt.connection_id == connection_id,
        MailInboundReceipt.admitted_at.is_(None),
        MailInboundReceipt.dispatch_requested.is_(True),
        MailInboundReceipt.status.in_(("received", "authorized", "error", "blocked")),
    ).order_by(MailInboundReceipt.updated_at).limit(50)))
    for identifier in identifiers:
        await process_receipt(identifier)


async def _wake(agent_id: int, key: str) -> bool:
    if not key.startswith(f"{_CONTEXT_PREFIX}:"):
        return False
    context = await _context(agent_id, key)
    if context is not None:
        await process_receipt(UUID(str(context["receipt_id"])))
        row = await get_db().get(MailInboundReceipt, UUID(str(context["receipt_id"])), populate_existing=True)
        if row is not None:
            for parent in set(row.waiting_contexts):
                if not await wake_authorization_context(agent_id, parent):
                    return False
    return True


async def list_receipts(
    *, current_user_id: int, agent_ids: Collection[int] | None,
    agent_id: int | None, search: str, offset: int, limit: int,
) -> MailInboundPage:
    query = select(MailInboundReceipt).options(defer(MailInboundReceipt.content))
    if agent_ids is not None:
        query = query.where(MailInboundReceipt.agent_id.in_(agent_ids))
    if agent_id is not None:
        query = query.where(MailInboundReceipt.agent_id == agent_id)
    if search:
        pattern = f"%{search.replace('%', r'\%').replace('_', r'\_')}%"
        query = query.where(or_(MailInboundReceipt.sender_address.ilike(pattern),
            MailInboundReceipt.subject.ilike(pattern), MailInboundReceipt.agent_label.ilike(pattern)))
    total = int(await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(await get_db().scalars(query.order_by(
        MailInboundReceipt.created_at.desc(), MailInboundReceipt.id.desc()
    ).offset(offset).limit(limit)))
    reviews = await authorization_reviews({row.authorization_id for row in rows if row.authorization_id})
    items = [_item(row, current_user_id, reviews.get(row.authorization_id) if row.authorization_id else None)
             for row in rows]
    return MailInboundPage(items=items, total=total, offset=offset, limit=limit)


def _item(row: MailInboundReceipt, current_user_id: int, review: AuthorizationReview | None) -> MailInboundItem:
    status = row.status
    if status == "pending_approval" and review:
        status = "rejected" if review.status in ("denied", "expired", "invalidated", "failed") else status
    return MailInboundItem(
            id=row.id, agent_id=row.agent_id, agent_label=row.agent_label,
            connection_id=row.connection_id, sender_address=row.sender_address,
            subject=row.subject, message_ref=row.message_ref,
            to_addresses=MailMessageSummary.model_validate(row.summary).to_addresses,
            known_contact=row.known_contact, status=status,
            authorization_id=row.authorization_id, authorization_status=review.status if review else None,
            can_review=bool(review and review.status == "pending" and review.approver_user_id == current_user_id),
            created_at=row.created_at, authorized_at=row.authorized_at,
            admitted_at=row.admitted_at, read_at=row.read_at, error=row.error,
        )


register_authorization_context_guard(_CONTEXT_PREFIX, _context)
register_authorization_waker(_CONTEXT_PREFIX, _wake)
register_runtime_authorization_waiter(_CONTEXT_PREFIX, _runtime_waiter)


async def _authorized_contact(agent_id: int, message: Message) -> bool:
    """A bridge payload or a forged metadata flag cannot grant email admission."""
    row = await get_db().scalar(select(MailInboundReceipt).where(
        MailInboundReceipt.connection_id == message.connection_id,
        MailInboundReceipt.agent_id == agent_id,
        MailInboundReceipt.message_ref == message.room_id,
        MailInboundReceipt.authorized_at.is_not(None),
    ))
    if row is None or message.sender is None:
        return False
    ref = MailMessageRef.decode(row.message_ref)
    if message.remote_message_id != f"{ref.uid_validity}:{ref.uid}":
        return False
    if message.sender.external_id.casefold() != row.sender_address.casefold():
        return False
    try:
        await authorize_receipt(row)
    except (PermissionError, ToolCallRejectedError):
        return False
    return True


register_inbound_contact_authorizer("mail", _authorized_contact)


async def get_receipt(
    identifier: UUID, *, current_user_id: int, agent_ids: frozenset[int] | None,
) -> MailInboundDetail | None:
    row = await get_db().get(MailInboundReceipt, identifier, populate_existing=True)
    if row is None or (agent_ids is not None and row.agent_id not in agent_ids):
        return None
    reviews = await authorization_reviews([row.authorization_id]) if row.authorization_id else {}
    item = _item(row, current_user_id, reviews.get(row.authorization_id) if row.authorization_id else None)
    return MailInboundDetail(**item.model_dump(), content=row.content)
