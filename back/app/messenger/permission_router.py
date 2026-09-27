"""Management of remembered decisions, scoped to the user's managed agents."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.agent import current_management_scope
from core.authorize import Privileges, authorize
from .permission_schemas import PermissionPage
from .permissions import delete_decision, list_decisions

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=PermissionPage)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_permissions(
    agent_id: int | None = Query(default=None, gt=0),
    allowed: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> PermissionPage:
    scope = await current_management_scope()
    return await list_decisions(managed_agent_ids=scope.agent_ids, agent_id=agent_id,
                                allowed=allowed, offset=offset, limit=limit)


@router.delete("/{permission_id}", status_code=204)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def delete_permission(permission_id: UUID) -> None:
    scope = await current_management_scope()
    if not await delete_decision(permission_id, managed_agent_ids=scope.agent_ids):
        raise HTTPException(404, "Permission not found")
