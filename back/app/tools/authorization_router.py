"""Human-only approval API; runtime credentials cannot answer for a human."""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, or_

from app.agent import current_management_scope, authorization_policy
from core.authorize import Privileges, authorize
from core.database import get_db
from core.user import require_web_session
from core.util import get_encryption_service

from .authorization import answer_action, can_remember_action, redacted_action_arguments
from .authorization_models import ActionAuthorization

router = APIRouter(prefix="/action-authorizations", tags=["permissions"], dependencies=[Depends(require_web_session)])


def projection(row: ActionAuthorization) -> dict[str, Any]:
    return {"id": str(row.id), "agent_id": row.agent_id, "approver_user_id": row.approver_user_id,
            "source": row.source, "capability_kind": row.capability_kind, "capability_name": row.capability_name,
            "status": row.status, "preview": row.preview, "decision_source": row.decision_source,
            "created_at": row.created_at, "expires_at": row.expires_at, "decided_at": row.decided_at,
            "claimed_at": row.claimed_at, "finished_at": row.finished_at,
            "notification_failed": row.notification_failed_at is not None}


@router.get("")
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_requests(agent_id: int | None = None, status: str | None = None,
                        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    scope = await current_management_scope()
    query = select(ActionAuthorization)
    if scope.agent_ids is not None:
        query = query.where(or_(ActionAuthorization.agent_id.in_(scope.agent_ids), ActionAuthorization.approver_user_id == scope.user_id))
    if agent_id is not None:
        query = query.where(ActionAuthorization.agent_id == agent_id)
    if status is not None:
        query = query.where(ActionAuthorization.status == status)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    rows = (await get_db().scalars(query.order_by(ActionAuthorization.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [projection(row) for row in rows], "total": total or 0}


def redacted(value: Any) -> Any:
    return redacted_action_arguments(value)


@router.get("/{identifier}")
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def get_request(identifier: UUID) -> dict[str, Any]:
    scope = await current_management_scope()
    row = await get_db().get(ActionAuthorization, identifier)
    if row is None or not (scope.allows(row.agent_id) or row.approver_user_id == scope.user_id):
        raise HTTPException(404, "Authorization not found")
    result = projection(row)
    try:
        policy = await authorization_policy(row.agent_id)
    except PermissionError:
        result.update(can_answer=False, can_remember=False, can_cancel=False)
        return result
    can_answer = row.approver_user_id == scope.user_id and (row.source == "domain" or row.approver_user_id == policy.manager_user_id)
    from datetime import datetime, timezone
    result["can_answer"] = can_answer and row.status == "pending" and row.expires_at > datetime.now(timezone.utc)
    result["can_remember"] = result["can_answer"] and await can_remember_action(row)
    result["can_cancel"] = scope.allows(row.agent_id) and row.status in ("pending", "approved")
    if can_answer and row.encrypted_arguments is not None:
        result["arguments"] = redacted(json.loads(get_encryption_service().decrypt(row.encrypted_arguments)))
    return result


class ActionAnswer(BaseModel):
    approved: bool
    remember: bool = False


@router.post("/{identifier}/answer")
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def answer_request(identifier: UUID, data: ActionAnswer) -> dict[str, bool]:
    scope = await current_management_scope()
    row = await get_db().get(ActionAuthorization, identifier)
    if row is None or not (scope.allows(row.agent_id) or row.approver_user_id == scope.user_id):
        raise HTTPException(404, "Authorization not found")
    if not await answer_action(identifier, user_id=scope.user_id, approved=data.approved, remember=data.remember):
        raise HTTPException(409, "Authorization already closed or approver no longer authorized")
    return {"accepted": True}


@router.post("/{identifier}/cancel")
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def cancel_request(identifier: UUID) -> dict[str, bool]:
    """Management may stop an unconsumed action, but cannot approve for its reviewer."""
    from datetime import datetime, timezone
    from core.database import get_db_session
    scope = await current_management_scope()
    identity = await get_db().scalar(select(ActionAuthorization.agent_id).where(ActionAuthorization.id == identifier))
    if identity is None or not scope.allows(identity):
        raise HTTPException(404, "Authorization not found")
    async with get_db_session() as db:
        try:
            await authorization_policy(identity, lock=True)
        except PermissionError as error:
            raise HTTPException(409, "The agent is no longer available") from error
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier).with_for_update())
        if row is None or row.status not in ("pending", "approved"):
            raise HTTPException(409, "The action is already closed or dispatched")
        now = datetime.now(timezone.utc)
        row.status = "invalidated"
        row.cancelled_by_user_id = scope.user_id
        row.cancelled_at = row.finished_at = row.wake_due_at = now
        row.encrypted_arguments = None
        row.notification_due_at = None
        await db.commit()
    return {"cancelled": True}
