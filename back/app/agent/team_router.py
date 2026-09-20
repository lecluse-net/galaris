"""Team membership administration without exposing agent configuration."""
from fastapi import APIRouter, HTTPException

from core.authorize import RequireAllPrivilegesAssertion, authorize
from core.database import get_db
from core.team import MembershipUpdate, notify_team_access_changed

from .dialogue_contracts import DialogueAgent
from .dialogue_service import policy_snapshot, set_agent_membership

router = APIRouter(prefix="/agents/teams", tags=["agent teams"])


@router.get("/agents", response_model=list[DialogueAgent])
@authorize(privileges="TEAM_ACCESS")
async def agents() -> list[DialogueAgent]:
    return list((await policy_snapshot()).agents.values())


@router.put("/{team_id}/members/{agent_id}", status_code=204)
@authorize(privileges="TEAM_MEMBERS_EDIT", assertion=RequireAllPrivilegesAssertion,
           params={"required_privileges": ["TEAM_ACCESS", "TEAM_MEMBERS_EDIT"]})
async def update_membership(team_id: int, agent_id: int, data: MembershipUpdate) -> None:
    try:
        await set_agent_membership(team_id, agent_id, data.present)
        await get_db().commit()
        await notify_team_access_changed()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
