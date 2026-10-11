"""Deferred execution and authorization receipts owned by lab."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlalchemy import and_, or_, select, update
from app.llm import LLMExecutionAuthority, llm_execution_scope
from app.tools.facade import AuthorizationClosed, AuthorizationSuspended, continued_deferred_dispatch, claim_deferred_dispatch, finish_action
from core.database import get_db
from .operation_contracts import LabOperationError, LabOperationSnapshot
from .operation_store import TERMINAL_STATUSES, publish, snapshot
from .operation_models import LabOperation
from .operation_execution import LabOperationExecutor

async def settle_authorization(identifier: UUID, result: LabOperationSnapshot) -> None:
    db = get_db()
    row = await db.get(LabOperation, identifier, populate_existing=True)
    assert row is not None
    permit = row.dispatch.get("authorization_permit")
    await db.commit()
    if permit:
        await finish_action(UUID(str(permit)), receipt={"operation_id": str(identifier), **result.model_dump(mode="json")},
            outcome="completed" if result.status == "success" else "failed", deferred=True)
    await db.execute(update(LabOperation).where(LabOperation.id == identifier).values(authorization_settled=True))
    await db.commit()

async def advance(identifier: UUID) -> LabOperationSnapshot:
    """Recheck a deferred permit before each domain effect, including direct refreshes."""
    db = get_db()
    row = await db.get(LabOperation, identifier, populate_existing=True)
    if row is None:
        raise LookupError("lab operation not found")
    if row.status in TERMINAL_STATUSES:
        result = snapshot(row)
        await db.commit()
        await settle_authorization(identifier, result)
        return result
    dispatch, authority, agent_id = dict(row.dispatch), dict(row.authority), row.agent_id
    cancelled = bool(row.checkpoint.get("cancel_requested"))
    permit = UUID(str(dispatch["authorization_permit"])) if dispatch.get("authorization_permit") else None
    await db.commit()
    try:
        if permit and not cancelled and not dispatch.get("claimed"):
            await claim_deferred_dispatch(permit, agent_id=agent_id,
                payload={k: v for k, v in dispatch.items() if k not in {"authorization_permit", "claimed"}},
                continuation=False)
            row = await db.get(LabOperation, identifier, populate_existing=True)
            assert row is not None
            row.dispatch = {**row.dispatch, "claimed": True}
            await db.commit()
        async with continued_deferred_dispatch(permit if not cancelled else None, agent_id=agent_id,
            payload={k: v for k, v in dispatch.items() if k not in {"authorization_permit", "claimed"}}):
            with llm_execution_scope(**asdict(LLMExecutionAuthority(**authority))):
                executor = LabOperationExecutor()
                result = await executor.advance(identifier)
        result = await publish(identifier, result)
    except AuthorizationSuspended:
        row = await db.get(LabOperation, identifier, populate_existing=True)
        assert row is not None
        result = snapshot(row)
        await db.commit()
    except (PermissionError, AuthorizationClosed):
        result = await publish(identifier, LabOperationSnapshot(status="error", error=LabOperationError(
            code="authorization_unavailable", message="The operation authorization is no longer available")))
    if result.status in TERMINAL_STATUSES:
        await settle_authorization(identifier, result)
    return result

async def tick() -> None:
    """Advance one operation under an expiring lease shared by all scheduler workers."""
    db, now = get_db(), datetime.now(timezone.utc)
    row = await db.scalar(select(LabOperation).where(
        or_(LabOperation.status.not_in(TERMINAL_STATUSES), and_(
            LabOperation.authorization_settled.is_(False),
            LabOperation.dispatch["authorization_permit"].astext.is_not(None))),
        or_(LabOperation.lease_expires_at.is_(None), LabOperation.lease_expires_at < now),
    ).order_by(LabOperation.updated_at, LabOperation.id).limit(1).with_for_update(skip_locked=True)
        .execution_options(populate_existing=True))
    if row is None:
        await db.commit()
        return
    identifier, lease = row.id, uuid4()
    row.lease_token, row.lease_expires_at = lease, now + timedelta(seconds=1500)
    await db.commit()
    try:
        await advance(identifier)
    finally:
        if not db.is_active:
            await db.rollback()
        await db.execute(update(LabOperation).where(LabOperation.id == identifier, LabOperation.lease_token == lease)
            .values(lease_token=None, lease_expires_at=None, updated_at=datetime.now(timezone.utc)))
        await db.commit()
