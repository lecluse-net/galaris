"""Management of remembered decisions, scoped to the user's managed agents."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent import current_management_scope
from core.authorize import Privileges, authorize
from core.user import require_web_session
from .permission_schemas import PermissionPage
from .permissions import answer_permission, delete_decision, list_decisions

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=PermissionPage)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_permissions(
    agent_id: int | None = Query(default=None, gt=0),
    allowed: bool | None = None,
    pending: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> PermissionPage:
    scope = await current_management_scope()
    return await list_decisions(managed_agent_ids=scope.agent_ids, agent_id=agent_id,
                                allowed=allowed, pending=pending, user_id=scope.user_id, offset=offset, limit=limit)


class PermissionAnswer(BaseModel):
    option_id: str = Field(min_length=1, max_length=100)


@router.post("/{permission_id}/answer", dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def answer_request(permission_id: UUID, data: PermissionAnswer) -> dict[str, bool]:
    scope = await current_management_scope()
    try:
        answered = await answer_permission(permission_id, user_id=scope.user_id, option_id=data.option_id)
    except (PermissionError, ValueError):
        answered = False
    if not answered:
        raise HTTPException(409, "Permission already answered or approver no longer authorized")
    return {"accepted": True}


@router.delete("/{permission_id}", status_code=204)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def delete_permission(permission_id: UUID) -> None:
    scope = await current_management_scope()
    if not await delete_decision(permission_id, managed_agent_ids=scope.agent_ids):
        raise HTTPException(404, "Permission not found")
