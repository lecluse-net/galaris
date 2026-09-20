"""Authenticated API routes for the operational dashboard."""

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope

from . import dashboard_service
from .schemas import DashboardResponse


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_dashboard(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
) -> DashboardResponse:
    """Return consolidated task, agent, and LLM indicators for one month."""

    try:
        scope = await current_management_scope()
        return await dashboard_service.get_dashboard(month, agent_ids=scope.agent_ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
