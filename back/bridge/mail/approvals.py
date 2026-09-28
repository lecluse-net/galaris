"""Per-message Mail approvals delivered through the canonical private Chat choices."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import or_, select, update

from app.agent import AgentManagementScope, management_scope_for
from app.messenger import (
    ChoiceOption, ChoiceRequest, ChoiceResolution, PendingChoice,
    expire_user_choice, register_choice_handler, request_user_choice,
)
from core.authorize import Privileges, check_privilege, role_id_ctx
from core.database import get_db
from core.i18n import t
from core.user import UserModel, user_service

from .models import MailOutboundDelivery


KIND = "mail_approval"


def _key(delivery_id: UUID) -> str:
    return f"mail-approval:{delivery_id}"


async def _review_scope(delivery: MailOutboundDelivery, user: UserModel) -> AgentManagementScope | None:
    if not user.is_active:
        return None
    # A notification or replay can run in another actor's context.
    token = role_id_ctx.set(None)
    try:
        if not await check_privilege(user, Privileges.CONNECTION_ACCESS, get_db()):
            return None
        scope = await management_scope_for(user, get_db())
        return scope if scope.allows(delivery.agent_id) else None
    finally:
        role_id_ctx.reset(token)


def _request(delivery: MailOutboundDelivery, language: str) -> ChoiceRequest:
    # JSON in a fence renders mail content as data, including HTML and Markdown.
    preview = json.dumps({
        t("mail_approval.sender", language): delivery.sender_address,
        t("mail_approval.to", language): delivery.to_addresses,
        t("mail_approval.cc", language): delivery.cc_addresses,
        t("mail_approval.bcc", language): delivery.bcc_addresses,
        t("mail_approval.subject", language): delivery.subject,
        t("mail_approval.body", language): delivery.body[:6000],
        t("mail_approval.html", language): delivery.html_body[:6000] if delivery.html_body else None,
        t("mail_approval.attachments", language): [
            {t("mail_approval.filename", language): attachment.get("filename"),
             t("mail_approval.size", language): attachment.get("size")}
            for attachment in delivery.attachment_metadata
        ],
    }, ensure_ascii=False, indent=2)
    fence = "`" * (max((len(part) for part in re.findall(r"`+", preview)), default=0) + 3)
    return ChoiceRequest(
        kind=KIND, title=t("mail_approval.title", language),
        body=f'{t("mail_approval.instructions", language)}\n\n{fence}json\n{preview}\n{fence}',
        options=[
            ChoiceOption(id="approve", label=t("mail_approval.approve", language)),
            ChoiceOption(id="reject", label=t("mail_approval.reject", language)),
        ],
        metadata={"delivery_id": str(delivery.id)}, timeout_seconds=604800, language=language,
    )


async def notify_approval(delivery_id: UUID) -> None:
    """Claim a bounded notification attempt; SMTP remains blocked on every failure."""
    db = get_db()
    now = datetime.now(timezone.utc)
    claimed = await db.scalar(update(MailOutboundDelivery).where(
        MailOutboundDelivery.id == delivery_id,
        MailOutboundDelivery.status == "pending_approval",
        MailOutboundDelivery.raw_message.is_not(None),
        MailOutboundDelivery.approval_notified_at.is_(None),
        or_(MailOutboundDelivery.approval_notification_after.is_(None),
            MailOutboundDelivery.approval_notification_after <= now),
    ).values(approval_notification_after=now + timedelta(seconds=60)).returning(MailOutboundDelivery.id))
    await db.commit()
    if claimed is None:
        return
    try:
        async with asyncio.timeout(20):
            delivery = await db.get(MailOutboundDelivery, delivery_id, populate_existing=True)
            if delivery is None or delivery.agent_id is None or delivery.approver_user_id is None:
                return
            user = await user_service.get_user_by_id(delivery.approver_user_id)
            if user is None or await _review_scope(delivery, user) is None:
                return
            await request_user_choice(
                agent_id=delivery.agent_id, user_id=user.id,
                request=_request(delivery, user.language or "en"), idempotency_key=_key(delivery.id),
            )
            await db.refresh(delivery)
            delivery.approval_notified_at = datetime.now(timezone.utc)
            delivery.approval_notification_after = datetime.now(timezone.utc) + timedelta(seconds=60)
            await db.commit()
            if delivery.status != "pending_approval":
                await close_approval(delivery)
    except Exception as exc:
        await db.rollback()
        logger.warning("Mail approval notification deferred: delivery={} error_type={}", delivery_id, type(exc).__name__)


async def retry_approval_notifications() -> None:
    now = datetime.now(timezone.utc)
    ids = list(await get_db().scalars(select(MailOutboundDelivery.id).where(
        MailOutboundDelivery.status == "pending_approval",
        MailOutboundDelivery.raw_message.is_not(None),
        MailOutboundDelivery.approval_notified_at.is_(None),
        or_(MailOutboundDelivery.approval_notification_after.is_(None),
            MailOutboundDelivery.approval_notification_after <= now),
    ).order_by(MailOutboundDelivery.created_at).limit(20)))
    for delivery_id in ids:
        await notify_approval(delivery_id)
    # Repair a crash between the durable SMTP/rejection outcome and prompt withdrawal.
    completed = list(await get_db().scalars(select(MailOutboundDelivery).where(
        MailOutboundDelivery.status != "pending_approval",
        MailOutboundDelivery.approval_notified_at.is_not(None),
        MailOutboundDelivery.approval_notification_after.is_not(None),
    ).order_by(MailOutboundDelivery.updated_at).limit(20)))
    for delivery in completed:
        await close_approval(delivery)


async def close_approval(delivery: MailOutboundDelivery) -> None:
    delivery_id, agent_id = delivery.id, delivery.agent_id
    try:
        if agent_id is not None:
            await expire_user_choice(agent_id=agent_id, kind=KIND, idempotency_key=_key(delivery_id))
        await get_db().execute(update(MailOutboundDelivery).where(
            MailOutboundDelivery.id == delivery_id,
        ).values(approval_notification_after=None))
        await get_db().commit()
    except Exception as exc:
        await get_db().rollback()
        logger.warning("Mail approval withdrawal deferred: delivery={} error_type={}", delivery_id, type(exc).__name__)


async def handle_approval(choice: PendingChoice, resolution: ChoiceResolution) -> None:
    from . import service

    if resolution.option_id not in {"approve", "reject"}:
        return
    delivery = await get_db().get(MailOutboundDelivery, UUID(str(choice.metadata["delivery_id"])), populate_existing=True)
    if delivery is None or delivery.status != "pending_approval":
        return  # A captured decision can be replayed after SMTP or a journal review.
    if (delivery.agent_id != choice.agent_id or delivery.approver_user_id is None
            or choice.user_id != f"user:{delivery.approver_user_id}"):
        return
    user = await user_service.get_user_by_id(delivery.approver_user_id)
    if user is None:
        return
    scope = await _review_scope(delivery, user)
    if scope is None:
        return
    try:
        if resolution.option_id == "approve":
            await service.approve_delivery(delivery.id, current_user_id=user.id, agent_ids=scope.agent_ids)
        else:
            await service.reject_delivery(delivery.id, current_user_id=user.id, agent_ids=scope.agent_ids, reason="")
    except service.MailDeliveryNotFoundError:
        return
    except service.MailDeliveryStateError:
        # A completed review or deleted connection cannot be resumed; transient failures retry.
        await get_db().refresh(delivery)
        if delivery.status == "pending_approval" and delivery.connection_id is not None:
            raise


register_choice_handler(KIND, handle_approval)
