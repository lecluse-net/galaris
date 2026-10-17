"""Application principal directory, independent of resource models."""

from sqlalchemy import select, Select, false, union
from sqlalchemy.orm import defer

from .models import Agent, AgentTeam as AgentTeamModel
from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import UserModel, HumanActor

from app.share.contracts import Collaborator, SharingState
from app.share import Principals
from .management_scope import AgentManagementScope


async def directory(*, owner_agent_id: int | None, owner_user_id: int | None) -> SharingState:
    agents = list(
        await get_db().scalars(select(Agent).options(defer(Agent.avatar)).order_by(Agent.id))
    )
    avatars = set(await get_db().scalars(select(Agent.id).where(Agent.avatar.is_not(None))))
    users = list(
        await get_db().scalars(
            select(UserModel).where(UserModel.is_active.is_(True)).order_by(UserModel.id)
        )
    )
    teams = list(await get_db().scalars(select(TeamModel).order_by(TeamModel.order, TeamModel.id)))
    agent_groups: dict[int, list[int]] = {}
    user_groups: dict[int, list[int]] = {}
    for agent, team in (
        await get_db().execute(select(AgentTeamModel.agent_id, AgentTeamModel.team_id))
    ).all():
        agent_groups.setdefault(agent, []).append(team)
    for user, team in (
        await get_db().execute(select(TeamUserModel.user_id, TeamUserModel.team_id))
    ).all():
        user_groups.setdefault(user, []).append(team)
    catalog = [
        *[
            Collaborator(
                kind="agent",
                id=a.id,
                label=f"{a.first_name} {a.last_name}".strip() or a.code,
                group_ids=agent_groups.get(a.id, []),
                has_avatar=a.id in avatars,
            )
            for a in agents
        ],
        *[
            Collaborator(
                kind="user",
                id=u.id,
                label=u.display_name or u.email,
                group_ids=user_groups.get(u.id, []),
                avatar_url=u.avatar_url,
                has_avatar=u.avatar_url is not None,
            )
            for u in users
        ],
        *[Collaborator(kind="team", id=t.id, label=t.name) for t in teams],
    ]
    owner = next(
        (
            p
            for p in catalog
            if (p.kind == "agent" and p.id == owner_agent_id)
            or (p.kind == "user" and p.id == owner_user_id)
        ),
        None,
    )
    memberships = set(
        agent_groups.get(owner_agent_id, [])
        if owner_agent_id is not None
        else user_groups.get(owner_user_id, [])
        if owner_user_id is not None
        else []
    )
    return SharingState(
        lock_version=1,
        can_manage=True,
        grants=[],
        level="private",
        can_write=False,
        owner=owner,
        options=[p for p in catalog if p != owner],
        owner_groups=[p for p in catalog if p.kind == "team" and p.id in memberships],
    )


def sharing_principals(actor: int | HumanActor | AgentManagementScope) -> Principals:
    teams = select(TeamModel.id).where(TeamModel.deleted_at.is_(None))
    if isinstance(actor, int):
        agents = select(Agent.id).where(Agent.id == actor)
        memberships = select(AgentTeamModel.team_id).where(AgentTeamModel.agent_id == actor)
        return Principals(agents, teams.where(TeamModel.id.in_(memberships)), None)
    agents = (
        select(Agent.id).where(false())
        if isinstance(actor, HumanActor)
        else (
            select(Agent.id)
            if actor.agent_ids is None
            else select(Agent.id).where(Agent.id.in_(actor.agent_ids))
        )
    )
    memberships = union(
        select(TeamUserModel.team_id).where(TeamUserModel.user_id == actor.user_id),
        select(AgentTeamModel.team_id).where(AgentTeamModel.agent_id.in_(agents)),
    )
    return Principals(agents, teams.where(TeamModel.id.in_(memberships)), actor.user_id)


def sharing_owner_teams(owner_agent_id: object, owner_user_id: object) -> Select[tuple[int]]:
    memberships = union(
        select(AgentTeamModel.team_id)
        .where(AgentTeamModel.agent_id == owner_agent_id)
        .correlate_except(AgentTeamModel),
        select(TeamUserModel.team_id)
        .where(TeamUserModel.user_id == owner_user_id)
        .correlate_except(TeamUserModel),
    )
    return select(TeamModel.id.label("team_id")).where(
        TeamModel.deleted_at.is_(None), TeamModel.id.in_(memberships)
    )
