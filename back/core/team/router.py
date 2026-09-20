from fastapi import APIRouter, HTTPException, Query

from core.authorize import RequireAllPrivilegesAssertion, authorize
from core.database import get_db
from . import service
from .contracts import HumanInfo, MembershipUpdate, TeamInfo, TeamMove, TeamWrite

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamInfo])
@authorize(privileges="TEAM_ACCESS")
async def list_teams() -> list[TeamInfo]:
    return await service.list_teams()


@router.get("/humans", response_model=list[HumanInfo])
@authorize(privileges="TEAM_ACCESS")
async def search_humans(search: str = Query(default="", max_length=200), limit: int = Query(default=500, ge=1, le=500)) -> list[HumanInfo]:
    return await service.search_humans(search, limit)


@router.post("", response_model=TeamInfo, status_code=201)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def create_team(data: TeamWrite) -> TeamInfo:
    try:
        result = await service.save_team(data)
        await get_db().commit()
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/{team_id}", response_model=TeamInfo)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def update_team(team_id: int, data: TeamWrite) -> TeamInfo:
    try:
        result = await service.save_team(data, team_id)
        await get_db().commit()
        return result
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{team_id}", status_code=204)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def delete_team(team_id: int) -> None:
    try:
        await service.delete_team(team_id)
        await get_db().commit()
        await service.notify_team_access_changed()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{team_id}/position", status_code=204)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def move_team(team_id: int, data: TeamMove) -> None:
    try:
        await service.move_team(team_id, data.target_team_id, after=data.after)
        await get_db().commit()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{team_id}/humans", response_model=list[HumanInfo])
@authorize(privileges="TEAM_ACCESS")
async def team_humans(team_id: int) -> list[HumanInfo]:
    try:
        return await service.team_humans(team_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{team_id}/humans/{user_id}", status_code=204)
@authorize(privileges="TEAM_MEMBERS_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_MEMBERS_EDIT"]})
async def set_human_membership(team_id: int, user_id: int, data: MembershipUpdate) -> None:
    try:
        await service.set_human_membership(team_id, user_id, data.present)
        await get_db().commit()
        await service.notify_team_access_changed()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
