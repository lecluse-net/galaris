"""Human contact access and connection-scoped peer dialogue decisions."""
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import check_privilege, role_id_ctx
from core.database import get_db
from core.i18n import tr
from core.params import Param, Params
from core.team import TeamModel, TeamUserModel, audit, human_memberships, lock_team_sharing, refresh_team_access, require_team
from core.user import UserModel, user_service

from .models import Agent, AgentTeam
from .dialogue_contracts import DialogueAgent, DialogueDecision, DialoguePolicy
from .management_scope import AgentManagementScope, AgentScopeDeniedError


class GalarisPeerContactDeniedError(AgentScopeDeniedError):
    """Model-safe explanation of the installed assistant's permanent peer isolation."""


async def policy_snapshot(db: AsyncSession | None = None) -> DialoguePolicy:
    session = db if db is not None else get_db()
    team_ids = set((await session.scalars(select(TeamModel.id))).all())
    agents = (await session.execute(
        select(Agent.id, Agent.first_name, Agent.last_name, Agent.code, Agent.user_id, Agent.avatar.is_not(None))
        .order_by(
            func.lower(Agent.first_name).collate("und-x-icu"),
            func.lower(Agent.last_name).collate("und-x-icu"),
            Agent.id,
        )
    )).all()
    memberships: dict[int, set[int]] = {}
    for agent_id, team_id in await session.execute(select(AgentTeam.agent_id, AgentTeam.team_id)):
        if team_id in team_ids:
            memberships.setdefault(agent_id, set()).add(team_id)
    policy = DialoguePolicy(humans=await human_memberships())
    for aid, first, last, code, manager, has_avatar in agents:
        teams = memberships.setdefault(aid, set())
        policy.agents[aid] = DialogueAgent(id=aid, label=f"{first} {last}".strip(), code=code,
                                         manager_user_id=manager, team_ids=sorted(teams), has_avatar=has_avatar)
    return policy


async def dialogue_scope_for(user: UserModel, db: AsyncSession, *, agent_id: int | None = None) -> AgentManagementScope:
    """Read the current human dialogue grants, optionally for just one agent."""
    if not user.is_active:
        return AgentManagementScope(user_id=user.id, agent_ids=frozenset())
    allowed = select(Agent.id).where(Agent.deleted_at.is_(None))
    if agent_id is not None:
        allowed = allowed.where(Agent.id == agent_id)
    if not await check_privilege(user, "AGENT_MANAGE_ALL", db):
        team_agents = (select(AgentTeam.agent_id)
            .join(TeamModel, TeamModel.id == AgentTeam.team_id)
            .join(TeamUserModel, TeamUserModel.team_id == TeamModel.id)
            .where(TeamUserModel.user_id == user.id, TeamModel.deleted_at.is_(None)))
        allowed = allowed.where(or_(Agent.user_id == user.id, Agent.id.in_(team_agents)))
    return AgentManagementScope(user_id=user.id, agent_ids=frozenset(await db.scalars(allowed)))


async def current_dialogue_scope(*, agent_id: int | None = None) -> AgentManagementScope:
    user = await user_service.get_current_user()
    if user is None:
        raise AgentScopeDeniedError("An authenticated user is required")
    return await dialogue_scope_for(user, get_db(), agent_id=agent_id)


async def require_peer_interaction(agent_id: int, peer_agent_id: int) -> None:
    """The identified Galaris assistant never participates in inter-agent exchanges."""
    if agent_id == peer_agent_id:
        return
    identity = await get_db().scalar(select(Param.value).where(Param.name == Params.GALARIS_AGENT_ID))
    if identity is not None and identity in {str(agent_id), str(peer_agent_id)}:
        raise GalarisPeerContactDeniedError(await tr("agent_dialogue.galaris_peer_forbidden"))


async def require_agent_contact(
    agent_id: int, *, peer_agent_id: int | None = None,
    human_user_id: int | None = None, peer_scope: str = "team",
) -> None:
    if peer_agent_id is not None:
        await require_peer_interaction(agent_id, peer_agent_id)
    decision = DialogueDecision(allowed=False, source="default")
    if peer_agent_id is not None:
        policy = await policy_snapshot()
        if peer_scope == "team":
            decision = policy.peers(agent_id, peer_agent_id)
        elif peer_scope == "all":
            decision = DialogueDecision(
                allowed=agent_id in policy.agents and peer_agent_id in policy.agents,
                source="global",
            )
    elif human_user_id is not None:
        user = await get_db().scalar(select(UserModel).where(UserModel.id == human_user_id))
        if user is not None:
            token = role_id_ctx.set(None)
            try:
                if (await dialogue_scope_for(user, get_db(), agent_id=agent_id)).allows(agent_id):
                    return
            finally:
                role_id_ctx.reset(token)
    if not decision.allowed:
        raise AgentScopeDeniedError("Contact is not authorized by the dialogue policy")


async def set_agent_membership(team_id: int, agent_id: int, present: bool) -> None:
    await lock_team_sharing()
    await require_team(team_id)
    agent = await get_db().scalar(select(Agent.id).where(Agent.id == agent_id).with_for_update())
    if agent is None:
        raise LookupError("Agent not found")
    if present:
        command = insert(AgentTeam).values(agent_id=agent_id, team_id=team_id).on_conflict_do_nothing()
    else:
        command = delete(AgentTeam).where(AgentTeam.agent_id == agent_id, AgentTeam.team_id == team_id)
    changed = await get_db().scalar(command.returning(AgentTeam.id)) is not None
    if changed:
        await refresh_team_access(team_id, ("agent", agent_id))
    audit("team.agent", {"team": team_id, "agent": agent_id, "before": not present if changed else present, "after": present})
