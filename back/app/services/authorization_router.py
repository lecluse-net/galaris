"""Human-only approval API; runtime credentials cannot answer for a human."""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, or_

from app.agent import current_management_scope, authorization_policy
from core.authorize import Privileges, authorize
from core.database import get_db
from core.i18n import current_language
from core.user import require_web_session
from core.util import get_encryption_service

from .authorization import answer_action, can_remember_action, redacted_action_arguments
from .authorization_models import ActionAuthorization
from .authorization_presentation import present_action

router = APIRouter(prefix="/action-authorizations", tags=["permissions"], dependencies=[Depends(require_web_session)])


def projection(row: ActionAuthorization) -> dict[str, Any]:
    return {"id": str(row.id), "agent_id": row.agent_id, "approver_user_id": row.approver_user_id,
            "source": row.source, "capability_kind": row.capability_kind, "capability_name": row.capability_name,
            "runtime": row.runtime,
            "status": row.status, "preview": row.preview, "decision_source": row.decision_source,
            "remembered": row.runtime_permission_id is not None or (row.decision_source == "human" and row.policy_source == "connection" and row.mode in {"enabled", "disabled"}),
            "created_at": row.created_at, "expires_at": row.expires_at, "decided_at": row.decided_at,
            "claimed_at": row.claimed_at, "finished_at": row.finished_at,
            "notification_failed": row.notification_failed_at is not None}


@router.get("")
@authorize(privileges=[Privileges.PERMISSION_ACCESS, Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
async def list_requests(agent_id: int | None = None, status: str | None = None,
                        q: str = Query("", max_length=500),
                        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    scope = await current_management_scope()
    query = select(ActionAuthorization)
    if scope.agent_ids is not None:
        query = query.where(or_(ActionAuthorization.agent_id.in_(scope.agent_ids), ActionAuthorization.approver_user_id == scope.user_id))
    if agent_id is not None:
        query = query.where(ActionAuthorization.agent_id == agent_id)
    if q.strip():
        needle = q.strip().lower()
        query = query.where(or_(func.lower(ActionAuthorization.preview).contains(needle, autoescape=True),
            func.lower(ActionAuthorization.capability_name).contains(needle, autoescape=True),
            func.lower(ActionAuthorization.runtime).contains(needle, autoescape=True)))
    if status is not None:
        query = query.where(ActionAuthorization.status == status)
    if status == "pending":
        query = query.where(ActionAuthorization.expires_at > datetime.now(timezone.utc))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    rows = (await get_db().scalars(query.order_by(ActionAuthorization.created_at.desc()).offset(offset).limit(limit))).all()
    return {"items": [projection(row) for row in rows], "total": total or 0}


def redacted(value: Any) -> Any:
    return redacted_action_arguments(value)


@router.get("/runtime-permissions")
@authorize(privileges=[Privileges.PERMISSION_ACCESS, Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
async def list_runtime_permissions(agent_id: int | None = None,
                                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict[str, object]:
    from .runtime_permissions import list_permissions
    scope = await current_management_scope()
    return await list_permissions(scope, agent_id=agent_id, offset=offset, limit=limit)


@router.delete("/runtime-permissions/{identifier}")
@authorize(privileges=Privileges.PERMISSION_REVOKE)
async def delete_runtime_permission(identifier: UUID) -> dict[str, bool]:
    from .runtime_permissions import revoke_permission
    scope = await current_management_scope()
    if not await revoke_permission(identifier, user_id=scope.user_id):
        raise HTTPException(404, "Runtime permission not found")
    return {"revoked": True}


@router.get("/runtime-policies")
@authorize(privileges=[Privileges.PERMISSION_ACCESS, Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
async def read_runtime_policies(agent_id: int = Query(..., gt=0)) -> list[dict[str, object]]:
    from .runtime_permissions import list_policies
    try:
        return await list_policies(await current_management_scope(), agent_id)
    except (LookupError, PermissionError) as exc:
        raise HTTPException(404, "Agent not found") from exc


class RuntimePolicyUpdate(BaseModel):
    agent_id: int = Field(gt=0)
    runtime: str = Field(min_length=1, max_length=50)
    capability_name: str = Field(min_length=1, max_length=255)
    allowed: bool | None


@router.put("/runtime-policies")
@authorize(privileges=[Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
async def update_runtime_policy(data: RuntimePolicyUpdate) -> dict[str, bool]:
    from core.authorize import check_privilege
    from core.user import get_current_user
    from .runtime_permissions import set_policy
    scope = await current_management_scope()
    if not scope.allows(data.agent_id):
        raise HTTPException(404, "Agent not found")
    if data.allowed is not None and not await check_privilege(await get_current_user(), Privileges.PERMISSION_DECIDE, get_db()):
        raise HTTPException(403, "Missing permission decision privilege")
    try:
        accepted = await set_policy(data.agent_id, data.runtime, data.capability_name, allowed=data.allowed, user_id=scope.user_id)
    except PermissionError:
        accepted = False
    if not accepted:
        raise HTTPException(409, "Action type or Harness configuration changed; reload permissions")
    return {"accepted": True}


@router.get("/{identifier}")
@authorize(privileges=[Privileges.PERMISSION_ACCESS, Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
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
        result["presentation"] = present_action(name=row.capability_name, source=row.source,
            arguments=result["arguments"], language=await current_language(user_id=scope.user_id))
    return result


class ActionAnswer(BaseModel):
    approved: bool
    remember: bool = False


@router.post("/{identifier}/answer")
@authorize(privileges=Privileges.PERMISSION_DECIDE)
async def answer_request(identifier: UUID, data: ActionAnswer) -> dict[str, bool]:
    scope = await current_management_scope()
    row = await get_db().get(ActionAuthorization, identifier)
    if row is None or not (scope.allows(row.agent_id) or row.approver_user_id == scope.user_id):
        raise HTTPException(404, "Authorization not found")
    if not await answer_action(identifier, user_id=scope.user_id, approved=data.approved, remember=data.remember):
        raise HTTPException(409, "Authorization already closed or approver no longer authorized")
    return {"accepted": True}


@router.post("/{identifier}/cancel")
@authorize(privileges=Privileges.PERMISSION_REVOKE)
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
