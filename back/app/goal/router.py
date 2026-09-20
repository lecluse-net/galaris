"""Administration API for long-running Goals."""

from __future__ import annotations
from core.util import require_editorial_client
from fastapi import Depends

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import AgentManagementScope, current_management_scope

from . import goal_service
from .models import GoalStatus
from .schemas import (
    GoalCommand,
    GoalApiCreate,
    GoalApiUpdate,
    GoalCyclePage,
    GoalCreate,
    GoalDetail,
    GoalPage,
    GoalRead,
    GoalSettingsRead,
    GoalSettingsUpdate,
    GoalTreePage,
    GoalUpdate,
    MessengerReferrerOption,
)
from . import settings_service


router = APIRouter(prefix="/goals", tags=["goals"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Goal not found")


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


async def _goal_scope_or_404(
    goal_id: UUID,
) -> tuple[GoalDetail, AgentManagementScope]:
    scope = await current_management_scope()
    goal = await goal_service.get_detail(goal_id)
    if (
        goal is None
        or not scope.allows(goal.agent_id)
        or (
            goal.referrer is not None
            and goal.referrer.type == "AGENT"
            and not scope.allows(goal.referrer.agent_id)
        )
    ):
        raise _not_found()
    return goal, scope


def _require_goal_agents(
    scope: AgentManagementScope,
    data: GoalApiCreate | GoalApiUpdate,
) -> None:
    if data.agent_id is not None and not scope.allows(data.agent_id):
        raise _not_found()


async def _require_parent_scope(
    scope: AgentManagementScope,
    parent_goal_id: UUID | None,
) -> None:
    if parent_goal_id is None:
        return
    parent = await goal_service.get_read(parent_goal_id)
    if parent is None or not scope.allows(parent.agent_id):
        raise _not_found()


@router.get("", response_model=GoalPage)
@authorize(privileges=[Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT])
async def read_goals(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    agent_id: int | None = None,
    goal_status: GoalStatus | None = Query(default=None, alias="status"),
    q: str | None = None,
) -> GoalPage:
    scope = await current_management_scope()
    return await goal_service.list_page(
        skip=skip,
        limit=limit,
        agent_id=agent_id,
        status=goal_status,
        search=q,
        agent_ids=scope.agent_ids,
    )


@router.get("/referrers/messenger", response_model=list[MessengerReferrerOption])
@authorize(privileges=Privileges.GOAL_EDIT)
async def search_messenger_referrers(
    agent_id: int = Query(gt=0),
    q: str = Query(default="", max_length=200),
) -> list[MessengerReferrerOption]:
    try:
        scope = await current_management_scope()
        if not scope.allows(agent_id):
            raise _not_found()
        return await goal_service.search_messenger_referrers(agent_id, q)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/settings", response_model=GoalSettingsRead)
@authorize(privileges=[Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT])
async def read_goal_settings() -> GoalSettingsRead:
    return await settings_service.get_settings()


@router.patch("/settings", response_model=GoalSettingsRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def update_goal_settings(data: GoalSettingsUpdate) -> GoalSettingsRead:
    try:
        scope = await current_management_scope()
        if not scope.is_global:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global Agent management is required",
            )
        return await settings_service.update_settings(data)
    except HTTPException:
        raise
    except settings_service.GoalSettingsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/tree", response_model=GoalTreePage)
@authorize(privileges=[Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT])
async def read_goal_tree() -> GoalTreePage:
    scope = await current_management_scope()
    return await goal_service.list_tree(agent_ids=scope.agent_ids)


@router.get("/{goal_id}", response_model=GoalDetail)
@authorize(privileges=[Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT])
async def read_goal(goal_id: UUID) -> GoalDetail:
    goal, _ = await _goal_scope_or_404(goal_id)
    return goal


@router.get("/{goal_id}/cycles", response_model=GoalCyclePage)
@authorize(privileges=[Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT])
async def read_goal_cycles(
    goal_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> GoalCyclePage:
    await _goal_scope_or_404(goal_id)
    cycles = await goal_service.list_cycles(
        goal_id,
        page=page,
        page_size=page_size,
    )
    if cycles is None:
        raise _not_found()
    return cycles


@router.post("", dependencies=[Depends(require_editorial_client)], response_model=GoalRead, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.GOAL_EDIT)
async def create_goal(data: GoalApiCreate) -> GoalRead:
    try:
        scope = await current_management_scope()
        _require_goal_agents(scope, data)
        await _require_parent_scope(scope, data.parent_goal_id)
        return await goal_service.create(GoalCreate.model_validate(data.model_dump()))
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{goal_id}", dependencies=[Depends(require_editorial_client)], response_model=GoalRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def update_goal(goal_id: UUID, data: GoalApiUpdate) -> GoalRead:
    try:
        _, scope = await _goal_scope_or_404(goal_id)
        _require_goal_agents(scope, data)
        if "parent_goal_id" in data.model_fields_set:
            await _require_parent_scope(scope, data.parent_goal_id)
        goal = await goal_service.update(
            goal_id,
            GoalUpdate.model_validate(data.model_dump(exclude_unset=True)),
        )
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if goal is None:
        raise _not_found()
    return goal


@router.post("/{goal_id}/pause", response_model=GoalRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def pause_goal(goal_id: UUID, command: GoalCommand) -> GoalRead:
    try:
        await _goal_scope_or_404(goal_id)
        goal = await goal_service.pause(goal_id, command)
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    if goal is None:
        raise _not_found()
    return goal


@router.post("/{goal_id}/resume", response_model=GoalRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def resume_goal(goal_id: UUID, command: GoalCommand) -> GoalRead:
    try:
        await _goal_scope_or_404(goal_id)
        goal = await goal_service.resume(goal_id, command)
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    if goal is None:
        raise _not_found()
    return goal


@router.post("/{goal_id}/complete", response_model=GoalRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def complete_goal(goal_id: UUID, command: GoalCommand) -> GoalRead:
    try:
        await _goal_scope_or_404(goal_id)
        goal = await goal_service.complete(goal_id, command)
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    if goal is None:
        raise _not_found()
    return goal


@router.post("/{goal_id}/run-now", response_model=GoalRead)
@authorize(privileges=Privileges.GOAL_EDIT)
async def run_goal_now(goal_id: UUID, command: GoalCommand) -> GoalRead:
    try:
        await _goal_scope_or_404(goal_id)
        goal = await goal_service.run_now(goal_id, command)
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    if goal is None:
        raise _not_found()
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.GOAL_EDIT)
async def delete_goal(goal_id: UUID) -> None:
    try:
        await _goal_scope_or_404(goal_id)
        deleted = await goal_service.delete(goal_id)
    except goal_service.GoalConflictError as exc:
        raise _conflict(exc) from exc
    if not deleted:
        raise _not_found()
