"""Contact access derived exclusively from teams and agent management."""
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import check_privilege, role_id_ctx
from core.database import get_db
from core.team import TeamModel, audit, human_memberships, require_team
from core.user import UserModel, user_service

from .models import Agent, AgentTeam
from .dialogue_contracts import DialogueAgent, DialogueDecision, DialoguePolicy
from .management_scope import AgentManagementScope, AgentScopeDeniedError


async def policy_snapshot(db: AsyncSession | None = None) -> DialoguePolicy:
    session = db if db is not None else get_db()
    team_ids = set((await session.scalars(select(TeamModel.id))).all())
    agents = (await session.execute(select(Agent.id, Agent.first_name, Agent.last_name, Agent.code, Agent.user_id, Agent.group_id, Agent.avatar.is_not(None)))).all()
    memberships: dict[int, set[int]] = {}
    for agent_id, team_id in await session.execute(select(AgentTeam.agent_id, AgentTeam.team_id)):
        if team_id in team_ids:
            memberships.setdefault(agent_id, set()).add(team_id)
    policy = DialoguePolicy(humans=await human_memberships())
    for aid, first, last, code, manager, legacy_team, has_avatar in agents:
        teams = memberships.setdefault(aid, set())
        if legacy_team in team_ids:
            teams.add(legacy_team)
        policy.agents[aid] = DialogueAgent(id=aid, label=f"{first} {last}".strip(), code=code,
                                         manager_user_id=manager, team_ids=sorted(teams), has_avatar=has_avatar)
    return policy


async def dialogue_scope_for(user: UserModel, db: AsyncSession) -> AgentManagementScope:
    policy = await policy_snapshot(db)
    global_access = await check_privilege(user, "AGENT_MANAGE_ALL", db)
    return AgentManagementScope(user_id=user.id, agent_ids=frozenset(
        aid for aid in policy.agents if policy.human(user.id, aid, active=user.is_active, global_access=global_access).allowed
    ))


async def current_dialogue_scope() -> AgentManagementScope:
    user = await user_service.get_current_user()
    if user is None:
        raise AgentScopeDeniedError("An authenticated user is required")
    return await dialogue_scope_for(user, get_db())


async def require_agent_contact(agent_id: int, *, peer_agent_id: int | None = None, human_user_id: int | None = None) -> None:
    policy = await policy_snapshot()
    decision = DialogueDecision(allowed=False, source="default")
    if peer_agent_id is not None:
        decision = policy.peers(agent_id, peer_agent_id)
    elif human_user_id is not None:
        user = await get_db().scalar(select(UserModel).where(UserModel.id == human_user_id))
        if user is not None:
            token = role_id_ctx.set(None)
            try:
                global_access = await check_privilege(user, "AGENT_MANAGE_ALL", get_db())
            finally:
                role_id_ctx.reset(token)
            decision = policy.human(user.id, agent_id, active=user.is_active, global_access=global_access)
    if not decision.allowed:
        raise AgentScopeDeniedError("Contact is not authorized by the team dialogue policy")


async def set_agent_membership(team_id: int, agent_id: int, present: bool) -> None:
    await require_team(team_id)
    agent = await get_db().scalar(select(Agent).where(Agent.id == agent_id).with_for_update())
    if agent is None:
        raise LookupError("Agent not found")
    previous = await get_db().scalar(select(AgentTeam.id).where(AgentTeam.agent_id == agent_id, AgentTeam.team_id == team_id))
    before = previous is not None or agent.group_id == team_id
    if present:
        await get_db().execute(insert(AgentTeam).values(agent_id=agent_id, team_id=team_id).on_conflict_do_nothing())
    else:
        await get_db().execute(delete(AgentTeam).where(AgentTeam.agent_id == agent_id, AgentTeam.team_id == team_id))
        if agent.group_id == team_id:
            agent.group_id = None
    audit("team.agent", {"team": team_id, "agent": agent_id, "before": before, "after": present})
