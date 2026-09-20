"""Application service for bounded IMAP/SMTP Mail operations."""

from __future__ import annotations

import hashlib
import asyncio
import json
import mimetypes
import re
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Callable, Collection
from typing import Iterable, Literal, Sequence, TypeVar, cast
from urllib.parse import unquote
from uuid import UUID, uuid4

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import Text, cast as sql_cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.agent.contracts import RuntimeName
from app.file_share import ResourceContext, materialize_resource
from core.database import get_db
from core.user import UserModel

from .connection_service import resolve_connection, resolve_mail_connection
from .contracts import (
    MailConnectionConfig,
    MailConnectionStatus,
    MailDeliveryKind,
    MailDeliveryStatus,
    MailMessageDetail,
    MailMessageRef,
    MailMutationResult,
    MailSearchPage,
    MailSearchQuery,
    MailSendReceipt,
    MailboxInfo,
    OutgoingAttachment,
    OutgoingMail,
)
from .imap_client import ImapClient
from .mime import AI_DISCLOSURE_VERSION, build_message
from .models import MailOutboundDelivery
from .schemas import (
    MailApproverOption,
    MailDeliveryAgentOption,
    MailDeliveryDetail,
    MailDeliveryListItem,
    MailDeliveryPage,
)
from .smtp_client import SmtpClient


_EMAIL_ADAPTER: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)
_T = TypeVar("_T")
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_RECIPIENTS = 50
_MAX_SUBJECT = 998
_MAX_BODY = 500_000
_MAX_ATTACHMENTS = 20
_DELIVERY_STATUSES = {
    "pending_approval",
    "claimed",
    "submitting",
    "sent",
    "rejected",
    "uncertain",
    "error",
}


class MailDeliveryNotFoundError(LookupError):
    """Raised when an outbound journal row does not exist."""


class MailApprovalForbiddenError(PermissionError):
    """Raised when a user is not the configured reviewer for a delivery."""


class MailDeliveryStateError(ValueError):
    """Raised when a review targets a delivery that is no longer pending."""


async def _thread(callable_value: Callable[[], _T]) -> _T:
    return await asyncio.to_thread(callable_value)


def _detect_mailbox(
    mailboxes: Sequence[MailboxInfo],
    role: str,
    configured: str | None,
) -> str | None:
    if configured:
        return configured
    return next((item.name for item in mailboxes if item.role == role), None)


async def connection_status_for_config(config: MailConnectionConfig) -> MailConnectionStatus:
    imap = ImapClient(config)
    smtp = SmtpClient(config)
    mailboxes, count = await _thread(imap.status)
    await _thread(smtp.status)
    return MailConnectionStatus(
        connection_id=config.connection_id,
        email_address=config.email_address,
        imap_ok=True,
        smtp_ok=True,
        mailboxes=count,
        sent_mailbox=_detect_mailbox(mailboxes, "sent", config.sent_mailbox),
        trash_mailbox=_detect_mailbox(mailboxes, "trash", config.trash_mailbox),
    )


async def test_connection(connection_id: int) -> MailConnectionStatus:
    return await connection_status_for_config(await resolve_connection(connection_id))


async def connection_status(agent_id: int) -> MailConnectionStatus:
    return await connection_status_for_config(await resolve_mail_connection(agent_id))


async def list_mailboxes(agent_id: int) -> list[MailboxInfo]:
    config = await resolve_mail_connection(agent_id)
    mailboxes, _count = await _thread(ImapClient(config).status)
    return mailboxes


async def search(agent_id: int, query: MailSearchQuery) -> MailSearchPage:
    config = await resolve_mail_connection(agent_id)
    return await _thread(lambda: ImapClient(config).search(query))


async def get_message(
    agent_id: int,
    message_ref: str,
    *,
    body_offset: int = 0,
    body_limit: int = 20_000,
) -> MailMessageDetail:
    config = await resolve_mail_connection(agent_id)
    ref = MailMessageRef.decode(message_ref)
    return await _thread(
        lambda: ImapClient(config).get_message(
            ref,
            body_offset=max(0, body_offset),
            body_limit=max(1, min(body_limit, 50_000)),
        )
    )


async def set_flags(
    agent_id: int,
    message_ref: str,
    *,
    seen: bool | None,
    flagged: bool | None,
) -> MailMutationResult:
    config = await resolve_mail_connection(agent_id)
    ref = MailMessageRef.decode(message_ref)
    return await _thread(
        lambda: ImapClient(config).set_flags(ref, seen=seen, flagged=flagged)
    )


async def move(agent_id: int, message_ref: str, mailbox: str) -> MailMutationResult:
    config = await resolve_mail_connection(agent_id)
    ref = MailMessageRef.decode(message_ref)
    return await _thread(lambda: ImapClient(config).move(ref, mailbox))


async def trash(agent_id: int, message_ref: str) -> MailMutationResult:
    config = await resolve_mail_connection(agent_id)
    mailboxes, _count = await _thread(ImapClient(config).status)
    mailbox = _detect_mailbox(mailboxes, "trash", config.trash_mailbox)
    if mailbox is None:
        raise ValueError("No IMAP Trash mailbox is configured or advertised")
    ref = MailMessageRef.decode(message_ref)
    return await _thread(lambda: ImapClient(config).move(ref, mailbox))


def _validate_header(value: str, name: str, maximum: int) -> str:
    clean = value.strip()
    if re.search(r"[\x00-\x1f\x7f]", clean):
        raise ValueError(f"Invalid control character in {name}")
    if len(clean) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return clean


def _addresses(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(_EMAIL_ADAPTER.validate_python(raw))
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _validate_outgoing(outgoing: OutgoingMail) -> OutgoingMail:
    to = _addresses(outgoing.to)
    cc = _addresses(outgoing.cc)
    bcc = _addresses(outgoing.bcc)
    if not to and not cc and not bcc:
        raise ValueError("At least one Mail recipient is required")
    if len({address.casefold() for address in (*to, *cc, *bcc)}) > _MAX_RECIPIENTS:
        raise ValueError(f"A Mail message supports at most {_MAX_RECIPIENTS} recipients")
    subject = _validate_header(outgoing.subject, "subject", _MAX_SUBJECT)
    if len(outgoing.body) > _MAX_BODY:
        raise ValueError(f"Mail body exceeds {_MAX_BODY} characters")
    if outgoing.html_body is not None and len(outgoing.html_body) > _MAX_BODY:
        raise ValueError(f"HTML Mail body exceeds {_MAX_BODY} characters")
    if len(outgoing.attachments) > _MAX_ATTACHMENTS:
        raise ValueError(f"A Mail message supports at most {_MAX_ATTACHMENTS} attachments")
    return OutgoingMail(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=outgoing.body.replace("\x00", ""),
        html_body=(
            outgoing.html_body.replace("\x00", "")
            if outgoing.html_body is not None
            else None
        ),
        attachments=outgoing.attachments,
        reply_to=(
            str(_EMAIL_ADAPTER.validate_python(outgoing.reply_to))
            if outgoing.reply_to
            else None
        ),
        in_reply_to=(
            _validate_header(outgoing.in_reply_to, "In-Reply-To", 255)
            if outgoing.in_reply_to
            else None
        ),
        references=tuple(
            _validate_header(item, "References", 255) for item in outgoing.references[-50:]
        ),
    )


async def _attachments_from_uris(
    config: MailConnectionConfig,
    *,
    runtime: RuntimeName,
    task_id: UUID | None,
    uris: Sequence[str],
) -> tuple[OutgoingAttachment, ...]:
    if len(uris) > _MAX_ATTACHMENTS:
        raise ValueError(f"A Mail message supports at most {_MAX_ATTACHMENTS} attachments")
    attachments: list[OutgoingAttachment] = []
    total = 0
    resource_context = ResourceContext(
        agent_id=config.agent_id,
        runtime=runtime,
        task_id=task_id,
    )
    with TemporaryDirectory(prefix="galaris_mail_") as directory:
        root = Path(directory)
        for index, uri in enumerate(uris):
            destination = root / f"attachment-{index}"
            materialized = await materialize_resource(
                resource_context,
                uri,
                destination,
                max_bytes=config.max_attachment_bytes,
            )
            total += materialized.size
            if total > config.max_total_attachment_bytes:
                raise ValueError("Mail attachments exceed the configured total size limit")
            filename = re.sub(
                r"[/\\\x00-\x1f\x7f]+", "_", materialized.name
            )[:255]
            if filename in {"", ".", ".."}:
                filename = f"attachment-{index + 1}.bin"
            attachments.append(
                OutgoingAttachment(
                    filename=filename,
                    media_type=(
                        materialized.media_type
                        or mimetypes.guess_type(filename)[0]
                        or "application/octet-stream"
                    ),
                    content=destination.read_bytes(),
                )
            )
    return tuple(attachments)


def _fingerprint(outgoing: OutgoingMail) -> str:
    payload = {
        "to": outgoing.to,
        "cc": outgoing.cc,
        "bcc": outgoing.bcc,
        "subject": outgoing.subject,
        "body": outgoing.body,
        "html_body": outgoing.html_body,
        "reply_to": outgoing.reply_to,
        "in_reply_to": outgoing.in_reply_to,
        "references": outgoing.references,
        "attachments": [
            {
                "filename": item.filename,
                "media_type": item.media_type,
                "sha256": hashlib.sha256(item.content).hexdigest(),
            }
            for item in outgoing.attachments
        ],
        "ai_disclosure_version": AI_DISCLOSURE_VERSION,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _message_id(delivery_id: UUID, email_address: str) -> str:
    domain = email_address.rpartition("@")[2].lower() or "galaris.local"
    safe_domain = re.sub(r"[^a-z0-9.-]", "-", domain)[:200] or "galaris.local"
    return f"<galaris-{delivery_id}@{safe_domain}>"


async def _claim_delivery(
    config: MailConnectionConfig,
    *,
    idempotency_key: str,
    fingerprint: str,
    outgoing: OutgoingMail,
    delivery_kind: MailDeliveryKind,
) -> MailOutboundDelivery:
    if not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValueError(
            "idempotency_key must contain 1 to 128 letters, digits, dots, underscores, colons, or hyphens"
        )
    db = get_db()
    delivery_id = uuid4()
    statement = (
        insert(MailOutboundDelivery)
        .values(
            id=delivery_id,
            connection_id=config.connection_id,
            agent_id=config.agent_id,
            agent_label=config.agent_label,
            sender_address=str(config.email_address),
            delivery_kind=delivery_kind,
            to_addresses=list(outgoing.to),
            cc_addresses=list(outgoing.cc),
            bcc_addresses=list(outgoing.bcc),
            subject=outgoing.subject,
            body=outgoing.body,
            html_body=outgoing.html_body,
            attachment_metadata=[
                {
                    "filename": item.filename,
                    "media_type": item.media_type,
                    "size": len(item.content),
                }
                for item in outgoing.attachments
            ],
            idempotency_key=idempotency_key,
            payload_fingerprint=fingerprint,
            rfc_message_id=_message_id(delivery_id, str(config.email_address)),
            ai_disclosure_version=AI_DISCLOSURE_VERSION,
            status="pending_approval" if config.approval_required else "claimed",
            approval_required=config.approval_required,
            approver_user_id=config.approver_user_id,
        )
        .on_conflict_do_nothing(
            index_elements=["connection_id", "idempotency_key"]
        )
    )
    await db.execute(statement)
    await db.commit()
    result = await db.execute(
        select(MailOutboundDelivery).where(
            MailOutboundDelivery.connection_id == config.connection_id,
            MailOutboundDelivery.idempotency_key == idempotency_key,
        ).with_for_update()
    )
    delivery = result.scalar_one()
    if delivery.payload_fingerprint != fingerprint:
        raise ValueError("The Mail idempotency key is already used for a different message")
    return delivery


async def _store_message(
    config: MailConnectionConfig,
    delivery: MailOutboundDelivery,
    outgoing: OutgoingMail,
) -> None:
    if delivery.raw_message is not None:
        return
    delivery.raw_message = build_message(
        config,
        outgoing,
        message_id=delivery.rfc_message_id,
        now=datetime.now(timezone.utc),
    )
    # Keep the claim row lock until the caller either persists a pending
    # approval or marks the delivery as submitting. Otherwise, two concurrent
    # calls using the same idempotency key could both reach SMTP.
    await get_db().flush()


def _receipt(delivery: MailOutboundDelivery, detail: str = "") -> MailSendReceipt:
    status = delivery.status
    if status not in _DELIVERY_STATUSES:
        status = "error"
    return MailSendReceipt(
        delivery_id=delivery.id,
        status=cast(MailDeliveryStatus, status),
        message_id=delivery.rfc_message_id,
        accepted_recipients=delivery.accepted_recipients,
        rejected_recipients=delivery.rejected_recipients,
        disclosure_version=delivery.ai_disclosure_version,
        detail=detail,
    )


async def _reconcile_uncertain(
    config: MailConnectionConfig,
    delivery: MailOutboundDelivery,
) -> MailSendReceipt:
    try:
        mailboxes, _count = await _thread(ImapClient(config).status)
        sent = _detect_mailbox(mailboxes, "sent", config.sent_mailbox)
        if sent is None:
            return _receipt(
                delivery,
                "Submission outcome is uncertain; no Sent mailbox is available",
            )
        found = await _thread(
            lambda: ImapClient(config).message_id_exists(sent, delivery.rfc_message_id)
        )
    except Exception:
        return _receipt(delivery, "Submission outcome is uncertain; reconciliation failed")
    if found:
        delivery.status = "sent"
        delivery.sent_at = datetime.now(timezone.utc)
        await get_db().commit()
        return _receipt(delivery, "Recovered from the Sent mailbox")
    delivery.status = "uncertain"
    await get_db().commit()
    return _receipt(delivery, "Submission outcome remains uncertain; it was not retried")


async def _project_sent_recipient_contacts(
    config: MailConnectionConfig,
    delivery: MailOutboundDelivery,
    receipt: MailSendReceipt,
) -> MailSendReceipt:
    """Refresh private contact memories only after durable SMTP success."""

    if receipt.status != "sent":
        return receipt
    from app.messenger import observe_contact

    recipients = dict.fromkeys(
        address.casefold()
        for address in (
            *delivery.to_addresses,
            *delivery.cc_addresses,
            *delivery.bcc_addresses,
        )
    )
    for address in recipients:
        await observe_contact(
            owner_agent_id=config.agent_id,
            messaging_id="mail",
            user_id=address,
        )
    return receipt


async def _submit_delivery(
    config: MailConnectionConfig,
    delivery: MailOutboundDelivery,
) -> MailSendReceipt:
    if delivery.raw_message is None:
        delivery.status = "error"
        await get_db().commit()
        return _receipt(delivery, "The durable Mail payload is unavailable")
    raw_message = delivery.raw_message
    delivery.status = "submitting"
    await get_db().commit()
    recipients = tuple(
        dict.fromkeys(
            (
                *delivery.to_addresses,
                *delivery.cc_addresses,
                *delivery.bcc_addresses,
            )
        )
    )
    try:
        accepted, rejected = await _thread(
            lambda: SmtpClient(config).send(
                raw_message,
                sender=delivery.sender_address,
                recipients=recipients,
            )
        )
    except (
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPSenderRefused,
        smtplib.SMTPDataError,
    ) as exc:
        delivery.status = "error"
        delivery.smtp_response_code = int(getattr(exc, "smtp_code", 0) or 0) or None
        await get_db().commit()
        return _receipt(delivery, "The SMTP server definitively rejected the message")
    except Exception:
        delivery.status = "uncertain"
        await get_db().commit()
        return _receipt(delivery, "SMTP submission outcome is uncertain; it was not retried")
    delivery.status = "sent"
    delivery.accepted_recipients = accepted
    delivery.rejected_recipients = rejected
    delivery.smtp_response_code = 250
    delivery.sent_at = datetime.now(timezone.utc)
    await get_db().commit()
    return await _project_sent_recipient_contacts(
        config,
        delivery,
        _receipt(delivery, "Accepted by the SMTP submission server"),
    )


async def send_outgoing(
    config: MailConnectionConfig,
    outgoing: OutgoingMail,
    *,
    idempotency_key: str,
    delivery_kind: MailDeliveryKind = "send",
) -> MailSendReceipt:
    outgoing = _validate_outgoing(outgoing)
    total_attachment_bytes = sum(len(item.content) for item in outgoing.attachments)
    if any(
        len(item.content) > config.max_attachment_bytes for item in outgoing.attachments
    ):
        raise ValueError("A Mail attachment exceeds the configured size limit")
    if total_attachment_bytes > config.max_total_attachment_bytes:
        raise ValueError("Mail attachments exceed the configured total size limit")
    delivery = await _claim_delivery(
        config,
        idempotency_key=idempotency_key,
        fingerprint=_fingerprint(outgoing),
        outgoing=outgoing,
        delivery_kind=delivery_kind,
    )
    await _store_message(config, delivery, outgoing)
    if delivery.status == "pending_approval":
        await get_db().commit()
        return _receipt(delivery, "Waiting for human approval before SMTP submission")
    if delivery.status in {"sent", "error", "rejected"}:
        return await _project_sent_recipient_contacts(
            config,
            delivery,
            _receipt(delivery, "Existing idempotent Mail receipt"),
        )
    if delivery.status in {"submitting", "uncertain"}:
        return await _project_sent_recipient_contacts(
            config,
            delivery,
            await _reconcile_uncertain(config, delivery),
        )
    return await _submit_delivery(config, delivery)


async def send(
    agent_id: int,
    *,
    runtime: RuntimeName,
    task_id: UUID | None,
    to: Sequence[str],
    cc: Sequence[str],
    bcc: Sequence[str],
    subject: str,
    body: str,
    html_body: str | None,
    attachment_uris: Sequence[str],
    reply_to: str | None,
    idempotency_key: str,
) -> MailSendReceipt:
    config = await resolve_mail_connection(agent_id)
    attachments = await _attachments_from_uris(
        config,
        runtime=runtime,
        task_id=task_id,
        uris=attachment_uris,
    )
    return await send_outgoing(
        config,
        OutgoingMail(
            to=tuple(to),
            cc=tuple(cc),
            bcc=tuple(bcc),
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
            reply_to=reply_to,
        ),
        idempotency_key=idempotency_key,
        delivery_kind="send",
    )


def _reply_subject(subject: str) -> str:
    return subject if re.match(r"^\s*re\s*:", subject, re.IGNORECASE) else f"Re: {subject}"


def _forward_subject(subject: str) -> str:
    return subject if re.match(r"^\s*fwd?\s*:", subject, re.IGNORECASE) else f"Fwd: {subject}"


async def reply(
    agent_id: int,
    *,
    runtime: RuntimeName,
    task_id: UUID | None,
    message_ref: str,
    body: str,
    html_body: str | None,
    reply_all: bool,
    additional_to: Sequence[str],
    attachment_uris: Sequence[str],
    idempotency_key: str,
) -> MailSendReceipt:
    config = await resolve_mail_connection(agent_id)
    original = await _thread(
        lambda: ImapClient(config).get_message(
            MailMessageRef.decode(message_ref), body_offset=0, body_limit=50_000
        )
    )
    primary = original.reply_to_addresses or ([original.from_address] if original.from_address else [])
    recipients = [*primary, *additional_to]
    cc = original.to_addresses + original.cc_addresses if reply_all else []
    own = str(config.email_address).casefold()
    recipients = [item for item in recipients if item.casefold() != own]
    cc = [item for item in cc if item.casefold() != own]
    attachments = await _attachments_from_uris(
        config,
        runtime=runtime,
        task_id=task_id,
        uris=attachment_uris,
    )
    reference_values: list[str] = list(original.references)
    if original.message_id is not None:
        reference_values.append(original.message_id)
    references = tuple(reference_values)
    return await send_outgoing(
        config,
        OutgoingMail(
            to=tuple(recipients),
            cc=tuple(cc),
            bcc=(),
            subject=_reply_subject(original.subject),
            body=body,
            html_body=html_body,
            attachments=attachments,
            in_reply_to=original.message_id,
            references=references,
        ),
        idempotency_key=idempotency_key,
        delivery_kind="reply",
    )


async def forward(
    agent_id: int,
    *,
    runtime: RuntimeName,
    task_id: UUID | None,
    message_ref: str,
    to: Sequence[str],
    cc: Sequence[str],
    bcc: Sequence[str],
    body: str,
    html_body: str | None,
    include_original: bool,
    include_original_attachments: bool,
    attachment_uris: Sequence[str],
    idempotency_key: str,
) -> MailSendReceipt:
    config = await resolve_mail_connection(agent_id)
    ref = MailMessageRef.decode(message_ref)
    original = await _thread(
        lambda: ImapClient(config).get_message(ref, body_offset=0, body_limit=50_000)
    )
    suffix = ""
    if include_original:
        suffix = (
            "\n\n---------- Forwarded message ----------\n"
            f"From: {original.from_address}\n"
            f"Date: {original.date or ''}\n"
            f"Subject: {original.subject}\n"
            f"To: {', '.join(original.to_addresses)}\n\n"
            f"{original.body}"
        )
    attachments = list(
        await _attachments_from_uris(
            config,
            runtime=runtime,
            task_id=task_id,
            uris=attachment_uris,
        )
    )
    if include_original_attachments:
        for attachment in original.attachments:
            attachments.append(
                await _thread(
                    lambda part_id=attachment.part_id: ImapClient(config).get_attachment(
                        ref, part_id
                    )
                )
            )
    return await send_outgoing(
        config,
        OutgoingMail(
            to=tuple(to),
            cc=tuple(cc),
            bcc=tuple(bcc),
            subject=_forward_subject(original.subject),
            body=body + suffix,
            html_body=html_body,
            attachments=tuple(attachments),
        ),
        idempotency_key=idempotency_key,
        delivery_kind="forward",
    )


def _delivery_status(delivery: MailOutboundDelivery) -> MailDeliveryStatus:
    if delivery.status not in _DELIVERY_STATUSES:
        return "error"
    return cast(MailDeliveryStatus, delivery.status)


def _delivery_kind(delivery: MailOutboundDelivery) -> MailDeliveryKind:
    if delivery.delivery_kind not in {"send", "reply", "forward"}:
        return "send"
    return cast(MailDeliveryKind, delivery.delivery_kind)


async def _user_labels(
    deliveries: Sequence[MailOutboundDelivery],
) -> dict[int, str]:
    user_ids = {
        user_id
        for delivery in deliveries
        for user_id in (delivery.approver_user_id, delivery.reviewed_by_user_id)
        if user_id is not None
    }
    if not user_ids:
        return {}
    rows = (
        await get_db().execute(
            select(UserModel.id, UserModel.display_name, UserModel.email).where(
                UserModel.id.in_(user_ids)
            )
        )
    ).all()
    return {
        user_id: str(display_name or email)
        for user_id, display_name, email in rows
    }


def _list_item(
    delivery: MailOutboundDelivery,
    *,
    labels: dict[int, str],
    current_user_id: int,
) -> MailDeliveryListItem:
    preview = re.sub(r"\s+", " ", delivery.body).strip()[:240]
    return MailDeliveryListItem(
        id=delivery.id,
        connection_id=delivery.connection_id,
        agent_id=delivery.agent_id,
        agent_label=delivery.agent_label,
        sender_address=delivery.sender_address,
        delivery_kind=_delivery_kind(delivery),
        to_addresses=list(delivery.to_addresses),
        cc_addresses=list(delivery.cc_addresses),
        bcc_addresses=list(delivery.bcc_addresses),
        subject=delivery.subject,
        body_preview=preview,
        attachment_count=len(delivery.attachment_metadata),
        status=_delivery_status(delivery),
        approval_required=delivery.approval_required,
        approver_user_id=delivery.approver_user_id,
        approver_label=labels.get(delivery.approver_user_id or -1),
        reviewed_by_user_id=delivery.reviewed_by_user_id,
        reviewed_by_label=labels.get(delivery.reviewed_by_user_id or -1),
        reviewed_at=delivery.reviewed_at,
        rejection_reason=delivery.rejection_reason,
        accepted_recipients=delivery.accepted_recipients,
        rejected_recipients=delivery.rejected_recipients,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
        sent_at=delivery.sent_at,
        can_review=(
            delivery.status == "pending_approval"
            and delivery.approver_user_id == current_user_id
        ),
    )


async def list_deliveries(
    *,
    current_user_id: int,
    scope: Literal["pending", "history", "all"],
    agent_id: int | None,
    search_text: str,
    offset: int,
    limit: int,
    agent_ids: Collection[int] | None = None,
) -> MailDeliveryPage:
    query = select(MailOutboundDelivery)
    if scope == "pending":
        query = query.where(MailOutboundDelivery.status == "pending_approval")
    elif scope == "history":
        query = query.where(MailOutboundDelivery.status != "pending_approval")
    if agent_id is not None:
        query = query.where(MailOutboundDelivery.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(MailOutboundDelivery.agent_id.in_(agent_ids))
    search_value = search_text.strip()
    if search_value:
        pattern = f"%{search_value}%"
        query = query.where(
            or_(
                MailOutboundDelivery.agent_label.ilike(pattern),
                MailOutboundDelivery.sender_address.ilike(pattern),
                MailOutboundDelivery.subject.ilike(pattern),
                MailOutboundDelivery.body.ilike(pattern),
                sql_cast(MailOutboundDelivery.to_addresses, Text).ilike(pattern),
                sql_cast(MailOutboundDelivery.cc_addresses, Text).ilike(pattern),
                sql_cast(MailOutboundDelivery.bcc_addresses, Text).ilike(pattern),
            )
        )
    total = (
        await get_db().execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
    ).scalar_one()
    deliveries = list(
        (
            await get_db().execute(
                query.order_by(MailOutboundDelivery.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    labels = await _user_labels(deliveries)
    return MailDeliveryPage(
        items=[
            _list_item(item, labels=labels, current_user_id=current_user_id)
            for item in deliveries
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


async def list_delivery_agents(
    *, agent_ids: Collection[int] | None = None
) -> list[MailDeliveryAgentOption]:
    query = (
        select(
                MailOutboundDelivery.agent_id,
                func.max(MailOutboundDelivery.agent_label),
            )
            .where(MailOutboundDelivery.agent_id.is_not(None))
            .group_by(MailOutboundDelivery.agent_id)
            .order_by(func.max(MailOutboundDelivery.agent_label))
    )
    if agent_ids is not None:
        query = query.where(MailOutboundDelivery.agent_id.in_(agent_ids))
    rows = (await get_db().execute(query)).all()
    return [
        MailDeliveryAgentOption(id=agent_id, label=str(label or f"Agent {agent_id}"))
        for agent_id, label in rows
        if agent_id is not None
    ]


async def list_approvers() -> list[MailApproverOption]:
    rows = (
        await get_db().execute(
            select(UserModel)
            .where(UserModel.is_active.is_(True))
            .order_by(UserModel.display_name, UserModel.email)
            .limit(500)
        )
    ).scalars()
    return [
        MailApproverOption(
            id=user.id,
            label=str(user.display_name or user.email),
            email=user.email,
        )
        for user in rows
    ]


async def get_delivery(
    delivery_id: UUID,
    *,
    current_user_id: int,
    agent_ids: Collection[int] | None = None,
) -> MailDeliveryDetail:
    delivery = await get_db().get(MailOutboundDelivery, delivery_id)
    if delivery is None or (
        agent_ids is not None and delivery.agent_id not in agent_ids
    ):
        raise MailDeliveryNotFoundError
    await get_db().refresh(delivery)
    labels = await _user_labels([delivery])
    item = _list_item(delivery, labels=labels, current_user_id=current_user_id)
    return MailDeliveryDetail(
        **item.model_dump(),
        body=delivery.body,
        html_body=delivery.html_body,
        attachments=list(delivery.attachment_metadata),
        message_id=delivery.rfc_message_id,
        disclosure_version=delivery.ai_disclosure_version,
        smtp_response_code=delivery.smtp_response_code,
    )


async def approve_delivery(
    delivery_id: UUID,
    *,
    current_user_id: int,
    agent_ids: Collection[int] | None = None,
) -> MailSendReceipt:
    delivery = (
        await get_db().execute(
            select(MailOutboundDelivery)
            .where(MailOutboundDelivery.id == delivery_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if delivery is None or (
        agent_ids is not None and delivery.agent_id not in agent_ids
    ):
        raise MailDeliveryNotFoundError
    if delivery.approver_user_id != current_user_id:
        raise MailApprovalForbiddenError
    if delivery.status != "pending_approval":
        raise MailDeliveryStateError("This Mail delivery is no longer awaiting approval")
    if delivery.connection_id is None:
        raise MailDeliveryStateError("The Mail connection no longer exists")
    config = await resolve_connection(delivery.connection_id, require_active=True)
    delivery.reviewed_by_user_id = current_user_id
    delivery.reviewed_at = datetime.now(timezone.utc)
    delivery.rejection_reason = None
    delivery.status = "claimed"
    return await _submit_delivery(config, delivery)


async def reject_delivery(
    delivery_id: UUID,
    *,
    current_user_id: int,
    reason: str,
    agent_ids: Collection[int] | None = None,
) -> MailDeliveryDetail:
    delivery = (
        await get_db().execute(
            select(MailOutboundDelivery)
            .where(MailOutboundDelivery.id == delivery_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if delivery is None or (
        agent_ids is not None and delivery.agent_id not in agent_ids
    ):
        raise MailDeliveryNotFoundError
    if delivery.approver_user_id != current_user_id:
        raise MailApprovalForbiddenError
    if delivery.status != "pending_approval":
        raise MailDeliveryStateError("This Mail delivery is no longer awaiting approval")
    delivery.status = "rejected"
    delivery.reviewed_by_user_id = current_user_id
    delivery.reviewed_at = datetime.now(timezone.utc)
    delivery.rejection_reason = reason.strip() or None
    await get_db().commit()
    return await get_delivery(
        delivery_id,
        current_user_id=current_user_id,
        agent_ids=agent_ids,
    )


async def get_attachment(
    agent_id: int,
    message_ref: str,
    part_id: str,
    *, max_bytes: int | None = None,
) -> OutgoingAttachment:
    config = await resolve_mail_connection(agent_id)
    ref = MailMessageRef.decode(message_ref)
    from core.util import buffered_io_budget

    maximum = config.max_total_attachment_bytes + 1_000_000
    if max_bytes is not None:
        maximum = min(maximum, max_bytes * 2 + 1_000_000)
    async with buffered_io_budget.reserve(maximum * 6, owner=f"mail:{agent_id}"):
        pending = asyncio.create_task(_thread(lambda: ImapClient(config).get_attachment(ref, part_id, max_bytes=max_bytes)))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            # IMAP has a hard socket deadline; do not release admission while
            # its worker is still holding the MIME buffer.
            await pending
            raise


def parse_attachment_locator(locator: str) -> tuple[str, str, str]:
    segments = locator.strip("/").split("/")
    if len(segments) < 4 or segments[0] != "attachment":
        raise ValueError("Invalid mail:// attachment URI")
    message_ref, part_id = segments[1], segments[2]
    filename = unquote("/".join(segments[3:]))
    if not re.fullmatch(r"part-[1-9][0-9]*", part_id):
        raise ValueError("Invalid mail:// attachment part")
    return message_ref, part_id, filename


__all__ = [
    "MailApprovalForbiddenError",
    "MailDeliveryNotFoundError",
    "MailDeliveryStateError",
    "approve_delivery",
    "connection_status",
    "forward",
    "get_attachment",
    "get_delivery",
    "get_message",
    "list_deliveries",
    "list_approvers",
    "list_delivery_agents",
    "list_mailboxes",
    "move",
    "parse_attachment_locator",
    "reply",
    "reject_delivery",
    "search",
    "send",
    "set_flags",
    "test_connection",
    "trash",
]
