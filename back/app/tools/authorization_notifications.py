"""Committed approval outbox; notification retries never dispatch the action."""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Literal, cast
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from sqlalchemy import or_, select, update, func

from app.messenger import ChoiceOption, ChoiceRequest, ChoiceResolution, PendingChoice, register_choice_handler, request_user_choice, expire_user_choice
from core.database import get_db, get_db_session
from core.i18n import current_language, render_prompt, t

from .authorization import answer_action, can_remember_action, wake_authorization_context, AuthorizationAction, resolve_action_mode
from .authorization import redacted_action_arguments
from .authorization_models import ActionAuthorization
from . import authorization_metrics as metrics

KIND = "tool_action_authorization"


async def _answer(interaction: PendingChoice, resolution: ChoiceResolution) -> None:
    if resolution.option_id not in {"allow", "deny", "allow_always"}:
        return
    identifier = UUID(str(interaction.metadata["authorization_request_id"]))
    row = await get_db().get(ActionAuthorization, identifier)
    if row is None or row.agent_id != interaction.agent_id or interaction.user_id != f"user:{row.approver_user_id}":
        return
    await answer_action(identifier, user_id=row.approver_user_id, approved=resolution.option_id != "deny",
                        remember=resolution.option_id == "allow_always")


register_choice_handler(KIND, _answer)


@asynccontextmanager
async def _isolated_delivery(identifier: UUID | None = None) -> AsyncGenerator[AsyncSession]:
    async with get_db_session() as db:
        try:
            yield db
        except Exception as error:
            await db.rollback()
            metrics.delivery_failures.add(1, {"error_type": type(error).__name__})
            logger.warning("Authorization outbox entry failed; the bounded lease will retry ({})", type(error).__name__)
            if identifier is not None:
                await db.execute(update(ActionAuthorization).where(ActionAuthorization.id == identifier,
                    ActionAuthorization.status == "pending").values(notification_failed_at=datetime.now(timezone.utc)))
                await db.commit()


async def _still_usable(row: ActionAuthorization) -> bool:
    from app.agent import authorization_policy
    from core.user import UserModel
    try:
        policy = await authorization_policy(row.agent_id)
        user = await get_db().get(UserModel, row.approver_user_id, populate_existing=True)
        if user is None or not user.is_active or (row.source != "domain" and row.approver_user_id != policy.manager_user_id):
            return False
        if row.decision_source == "agent_yolo" and (not policy.yolo or row.policy_version != policy.version):
            return False
        if row.runtime_grant_ref is not None and row.runtime_grant_id is None:
            return False
        mode, source = await resolve_action_mode(AuthorizationAction(agent_id=row.agent_id, runtime=row.runtime,
            context_key=row.context_key, callback_key="reconciliation", name=row.capability_name,
            arguments={}, configuration={}, tool_id=row.tool_id, connection_id=row.connection_id,
            runtime_grant_id=row.runtime_grant_id, policy_name=row.policy_name,
            kind=cast(Literal["tool", "resource", "prompt"], row.capability_kind),
            source=cast(Literal["mcp", "runtime", "domain"], row.source)), lock=False)
        return mode == row.mode and source == row.policy_source
    except (PermissionError, ValueError, LookupError):
        return False


async def deliver_authorization_notifications() -> None:
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        ids = list((await db.scalars(select(ActionAuthorization.id).where(
            ActionAuthorization.status == "pending", ActionAuthorization.expires_at > now,
            ActionAuthorization.notification_due_at <= now,
        ).order_by(ActionAuthorization.created_at).limit(20))).all())
    for identifier in ids:
        async with _isolated_delivery(identifier) as db:
            claimed = await db.scalar(update(ActionAuthorization).where(
                ActionAuthorization.id == identifier, ActionAuthorization.status == "pending",
                ActionAuthorization.notification_due_at <= now,
            ).values(notification_due_at=now + timedelta(seconds=60)).returning(ActionAuthorization.id))
            await db.commit()
            if claimed is None:
                continue
            row = await db.get(ActionAuthorization, identifier)
            if row is None:
                continue
            if not await _still_usable(row):
                row.status = "invalidated"
                row.encrypted_arguments = None
                row.finished_at = row.wake_due_at = now
                row.notification_due_at = None
                await db.commit()
                continue
            language = await current_language(user_id=row.approver_user_id)
            options = [ChoiceOption(id="allow", label=t("permissions.allow_once", language)),
                       ChoiceOption(id="deny", label=t("permissions.deny_once", language))]
            body = row.preview
            if row.encrypted_arguments is not None:
                import json
                from core.util import get_encryption_service
                arguments = redacted_action_arguments(json.loads(get_encryption_service().decrypt(row.encrypted_arguments)))
                body += "\n\n" + json.dumps(arguments, ensure_ascii=False)[:6000]
            if await can_remember_action(row):
                options.append(ChoiceOption(id="allow_always", label=t("permissions.allow_function", language)))
                body += "\n\n" + render_prompt(t("permissions.function_scope", language), function=row.capability_name)
            interaction = await request_user_choice(
                agent_id=row.agent_id, user_id=row.approver_user_id,
                request=ChoiceRequest(
                    kind=KIND, title=t("permissions.title", language),
                    body=body + f"\n\n/connection/permissions?request={row.id}",
                    options=options,
                    metadata={"authorization_request_id": str(row.id)},
                    timeout_seconds=max(1, int((row.expires_at - now).total_seconds())), language=language,
                ), idempotency_key=f"authorization:{row.id}",
            )
            attached = await db.scalar(update(ActionAuthorization).where(
                ActionAuthorization.id == identifier, ActionAuthorization.status == "pending",
            ).values(interaction_id=interaction.id, notification_due_at=None, notification_failed_at=None).returning(ActionAuthorization.id))
            await db.commit()
            if attached is None:
                await expire_user_choice(agent_id=row.agent_id, kind=KIND, idempotency_key=f"authorization:{identifier}")


async def reconcile_authorizations() -> None:
    """Expire bounded approvals and classify abandoned dispatches without resending them."""
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        unsettled = list((await db.scalars(select(ActionAuthorization.id).where(
            ActionAuthorization.status.in_(("pending", "approved"))).order_by(ActionAuthorization.created_at).limit(200))).all())
    for identifier in unsettled:
        async with _isolated_delivery() as db:
            row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier)
                .with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if row is not None and row.status in ("pending", "approved") and not await _still_usable(row):
                row.status = "invalidated"
                row.encrypted_arguments = None
                row.finished_at = row.wake_due_at = now
                row.notification_due_at = None
            await db.commit()
    async with get_db_session() as db:
        await db.execute(update(ActionAuthorization).where(
            ActionAuthorization.id.in_(select(ActionAuthorization.id).where(
                ActionAuthorization.status.in_(("pending", "approved")), ActionAuthorization.expires_at <= now,
            ).order_by(ActionAuthorization.expires_at).limit(200)),
        ).values(status="expired", encrypted_arguments=None, notification_due_at=None,
                 wake_due_at=now, finished_at=now))
        await db.execute(update(ActionAuthorization).where(
            ActionAuthorization.id.in_(select(ActionAuthorization.id).where(
                ActionAuthorization.status == "executing", ActionAuthorization.claimed_at < now - timedelta(hours=24),
            ).order_by(ActionAuthorization.claimed_at).limit(200)),
        ).values(status="outcome_unknown", finished_at=now))
        # Unknown outcomes retain their reconciliation evidence until resolved.
        # Closed requests keep only the minimal deduplication record after 90 days.
        await db.execute(update(ActionAuthorization).where(
            ActionAuthorization.id.in_(select(ActionAuthorization.id).where(
                ActionAuthorization.status.in_(("completed", "failed", "denied", "expired", "invalidated")),
                ActionAuthorization.finished_at < now - timedelta(days=90),
                or_(ActionAuthorization.encrypted_arguments.is_not(None), ActionAuthorization.encrypted_receipt.is_not(None), ActionAuthorization.preview != ""),
            ).order_by(ActionAuthorization.finished_at).limit(200)),
        ).values(encrypted_arguments=None, encrypted_receipt=None, preview=""))
        count = await db.scalar(select(func.count()).select_from(ActionAuthorization).where(
            ActionAuthorization.status.in_(("pending", "approved", "executing", "outcome_unknown"))))
        metrics.backlog.set(int(count or 0))
        await db.commit()
        wakes = (await db.execute(select(ActionAuthorization.id, ActionAuthorization.agent_id, ActionAuthorization.context_key).where(
            ActionAuthorization.wake_due_at <= now,
        ).order_by(ActionAuthorization.wake_due_at).limit(50))).all()
    for identifier, agent_id, context_key in wakes:
        async with _isolated_delivery() as db:
            claimed = await db.scalar(update(ActionAuthorization).where(
                ActionAuthorization.id == identifier, ActionAuthorization.wake_due_at <= now,
            ).values(wake_due_at=now + timedelta(seconds=60)).returning(ActionAuthorization.id))
            await db.commit()
            if claimed is None:
                continue
            await expire_user_choice(agent_id=agent_id, kind=KIND, idempotency_key=f"authorization:{identifier}")
            acknowledged = await wake_authorization_context(agent_id, context_key)
            await db.execute(update(ActionAuthorization).where(ActionAuthorization.id == identifier).values(
                wake_due_at=None if acknowledged else now + timedelta(seconds=5),
            ))
            await db.commit()
