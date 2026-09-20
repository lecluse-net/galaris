"""Callback acknowledgment only: authenticated provider polling owns transitions."""

import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.process import process_service
from app.agent import current_management_scope
from core.authorize import Privileges, authorize, independent_auth
from core.database import get_db
from sqlalchemy import select
from .models import MediaOutputReceipt
from .delivery import DeliveryRepair, repair_delivery

router = APIRouter(prefix="/multimedia", tags=["Multimedia"])


async def _scoped_run(run_id: UUID) -> int:
    scope = await current_management_scope()
    run = await process_service.get_run(run_id)
    if run is None or run.engine_code != "multimedia" or not scope.allows(run.launcher_agent_id):
        raise HTTPException(status_code=404)
    return scope.user_id


@router.get("/runs/{run_id}/deliveries")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def list_deliveries(run_id: UUID) -> list[dict[str, object]]:
    await _scoped_run(run_id)
    rows = await get_db().execute(select(
        MediaOutputReceipt.id, MediaOutputReceipt.ordinal, MediaOutputReceipt.media_type,
        MediaOutputReceipt.delivery_started, MediaOutputReceipt.delivery_attempts,
        MediaOutputReceipt.delivery_lease_until, MediaOutputReceipt.uri,
    ).where(MediaOutputReceipt.run_id == run_id).order_by(MediaOutputReceipt.ordinal).limit(4))
    return [dict(row) for row in rows.mappings()]


@router.post("/runs/{run_id}/deliveries/{receipt_id}/resolve")
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def resolve_delivery(run_id: UUID, receipt_id: UUID, repair: DeliveryRepair) -> dict[str, bool]:
    actor = await _scoped_run(run_id)
    try:
        await repair_delivery(run_id, receipt_id, repair, actor_user_id=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"resolved": True}


@router.post("/callback/{run_id}/{token}")
@independent_auth(reason="Per-run token; provider polling is authoritative")
async def acknowledge_callback(run_id: UUID, token: str) -> dict[str, bool]:
    run = await process_service.get_run(run_id)
    if run is None or run.engine_code != "multimedia" or not secrets.compare_digest(run.callback_token, token):
        raise HTTPException(status_code=404)
    # Never trust an unsigned vendor payload or consume its URLs. The periodic refresh
    # obtains authenticated task state and performs idempotent finalization.
    return {"received": True}
