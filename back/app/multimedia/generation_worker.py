"""Deferred execution and authorization receipts owned by multimedia."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, func, or_, select, update
from app.llm import LLMExecutionAuthority, MediaRequest, llm_execution_scope
from app.llm.facade import MediaProviderUnavailable, MediaRequestRejected
from app.services.facade import AuthorizationClosed, AuthorizationSuspended, continued_deferred_dispatch, claim_deferred_dispatch, finish_action
from core.database import get_db
from core.util import BufferedAdmissionDeferred
from .generation_contracts import MediaGenerationError, MediaGenerationSnapshot
from .generation_store import TERMINAL_STATUSES, publish, snapshot
from .models import MediaGeneration
from .generation_execution import MediaGenerationExecutor
from .provider_results import InvalidMediaOutput
from .service import authorize
from .video_frames import VideoFrameError


def _is_settled_result(result: MediaGenerationSnapshot) -> bool:
    return result.status in TERMINAL_STATUSES or (
        result.status == "unknown" and result.error is not None and result.error.code == "submission_unknown"
    )


async def settle_authorization(identifier: UUID, result: MediaGenerationSnapshot) -> None:
    db = get_db()
    row = await db.get(MediaGeneration, identifier, populate_existing=True)
    assert row is not None
    permit = row.dispatch.get("authorization_permit")
    await db.commit()
    if permit:
        await finish_action(UUID(str(permit)), receipt={"generation_id": str(identifier), **result.model_dump(mode="json")},
            outcome="completed" if result.status == "success" else "failed", deferred=True)
    await db.execute(update(MediaGeneration).where(MediaGeneration.id == identifier).values(authorization_settled=True))
    await db.commit()

async def advance(identifier: UUID) -> MediaGenerationSnapshot:
    """Recheck a deferred permit before each domain effect, including direct refreshes."""
    db = get_db()
    row = await db.get(MediaGeneration, identifier, populate_existing=True)
    if row is None:
        raise LookupError("multimedia operation not found")
    result = snapshot(row)
    if _is_settled_result(result):
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
            row = await db.get(MediaGeneration, identifier, populate_existing=True)
            assert row is not None
            row.dispatch = {**row.dispatch, "claimed": True}
            await db.commit()
        async with continued_deferred_dispatch(permit if not cancelled else None, agent_id=agent_id,
            payload={k: v for k, v in dispatch.items() if k not in {"authorization_permit", "claimed"}}):
            with llm_execution_scope(**asdict(LLMExecutionAuthority(**authority))):
                executor = MediaGenerationExecutor()
                await authorize(agent_id, MediaRequest.model_validate(row.input["request"]).operation)
                await executor.submit(identifier)
                result = await executor.advance(identifier)
        result = await publish(identifier, result)
    except AuthorizationSuspended:
        row = await db.get(MediaGeneration, identifier, populate_existing=True)
        assert row is not None
        result = snapshot(row)
        await db.commit()
    except (PermissionError, AuthorizationClosed):
        result = await publish(identifier, MediaGenerationSnapshot(status="error", error=MediaGenerationError(
            code="authorization_unavailable", message="The operation authorization is no longer available")))
    except BufferedAdmissionDeferred:
        await db.rollback()
        result = await publish(identifier, MediaGenerationSnapshot(status="waiting", error=MediaGenerationError(
            code="capacity_waiting", message="The operation is waiting for local media processing capacity.")))
    except (MediaProviderUnavailable, httpx.TransportError, TimeoutError):
        await db.rollback()
        result = await publish(identifier, MediaGenerationSnapshot(status="waiting", error=MediaGenerationError(
            code="provider_retrying", message="The provider result is temporarily unavailable. Tracking will retry automatically.")))
    except (InvalidMediaOutput, MediaRequestRejected) as exc:
        await db.rollback()
        result = await publish(identifier, MediaGenerationSnapshot(status="error", error=MediaGenerationError(
            code="provider_output_invalid" if isinstance(exc, InvalidMediaOutput) else "provider_status_refused",
            message=str(exc))))
    except VideoFrameError as exc:
        await db.rollback()
        result = await publish(identifier, MediaGenerationSnapshot(status="error", error=MediaGenerationError(
            code="invalid_video_frame", message=str(exc))))
    except ValueError:
        await db.rollback()
        result = await publish(identifier, MediaGenerationSnapshot(status="error", error=MediaGenerationError(
            code="generation_invalid", message="The admitted media request or provider configuration is no longer valid")))
    if _is_settled_result(result):
        await settle_authorization(identifier, result)
    return result

async def tick() -> None:
    """Advance one operation under an expiring lease shared by all scheduler workers."""
    db, now = get_db(), datetime.now(timezone.utc)
    settled = or_(
        MediaGeneration.status.in_(TERMINAL_STATUSES),
        and_(MediaGeneration.status == "unknown",
             func.coalesce(MediaGeneration.error["code"].astext, "") == "submission_unknown"),
    )
    row = await db.scalar(select(MediaGeneration).where(
        or_(~settled, and_(
            MediaGeneration.authorization_settled.is_(False),
            MediaGeneration.dispatch["authorization_permit"].astext.is_not(None))),
        or_(MediaGeneration.lease_expires_at.is_(None), MediaGeneration.lease_expires_at < now),
    ).order_by(MediaGeneration.updated_at, MediaGeneration.id).limit(1).with_for_update(skip_locked=True)
        .execution_options(populate_existing=True))
    if row is None:
        await db.commit()
        return
    identifier, lease = row.id, uuid4()
    row.lease_token, row.lease_expires_at = lease, now + timedelta(seconds=1500)
    await db.commit()
    next_check = None
    try:
        result = await advance(identifier)
        if result.status in {"running", "waiting", "unknown"} and not _is_settled_result(result):
            delay = 30 if result.error or result.status == "unknown" else 10
            next_check = datetime.now(timezone.utc) + timedelta(seconds=delay)
    finally:
        if not db.is_active:
            await db.rollback()
        await db.execute(update(MediaGeneration).where(MediaGeneration.id == identifier, MediaGeneration.lease_token == lease)
            .values(lease_token=None, lease_expires_at=next_check, updated_at=datetime.now(timezone.utc)))
        await db.commit()
