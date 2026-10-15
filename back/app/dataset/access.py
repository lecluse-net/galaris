"""Dataset ACL predicates, evaluated before listing, reading or writing."""

from sqlalchemy import and_, exists, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from app.agent import Agent, AgentManagementScope, AgentTeamModel
from core.database import get_db
from core.authorize import check_privilege
from core.team import TeamModel, TeamUserModel
from core.user import UserModel, get_user_record

from .contracts import DataActor, DatasetAccess
from .models import Dataset, DatasetGrant


def owner_clause(actor: DataActor) -> ColumnElement[bool]:
    if isinstance(actor, int):
        return Dataset.owner_agent_id == actor
    owned = Dataset.owner_user_id == actor.user_id
    if isinstance(actor, AgentManagementScope):
        managed = Dataset.owner_agent_id.is_not(None) if actor.agent_ids is None else Dataset.owner_agent_id.in_(actor.agent_ids)
        return or_(owned, managed)
    return owned


def _principal_clause(actor: DataActor, *, write: bool) -> ColumnElement[bool]:
    grants = select(DatasetGrant.id).where(DatasetGrant.dataset_id == Dataset.id)
    if write:
        grants = grants.where(DatasetGrant.can_write.is_(True))
    team_ids = select(TeamModel.id).where(TeamModel.deleted_at.is_(None))
    if isinstance(actor, int):
        team_ids = team_ids.join(AgentTeamModel, AgentTeamModel.team_id == TeamModel.id).where(AgentTeamModel.agent_id == actor)
        direct = DatasetGrant.agent_id == actor
        owner_teams = or_(
            exists(select(AgentTeamModel.id).where(AgentTeamModel.agent_id == Dataset.owner_agent_id, AgentTeamModel.team_id.in_(team_ids))),
            exists(select(TeamUserModel.id).where(TeamUserModel.user_id == Dataset.owner_user_id, TeamUserModel.team_id.in_(team_ids))))
    else:
        team_ids = team_ids.join(TeamUserModel, TeamUserModel.team_id == TeamModel.id).where(TeamUserModel.user_id == actor.user_id)
        direct = DatasetGrant.user_id == actor.user_id
        owner_teams = or_(
            exists(select(AgentTeamModel.id).where(AgentTeamModel.agent_id == Dataset.owner_agent_id, AgentTeamModel.team_id.in_(team_ids))),
            exists(select(TeamUserModel.id).where(TeamUserModel.user_id == Dataset.owner_user_id, TeamUserModel.team_id.in_(team_ids))))
        if isinstance(actor, AgentManagementScope):
            agent_ids = select(Agent.id) if actor.agent_ids is None else select(Agent.id).where(Agent.id.in_(actor.agent_ids))
            direct = or_(direct, DatasetGrant.agent_id.in_(agent_ids))
            managed_teams = select(AgentTeamModel.team_id).join(TeamModel, TeamModel.id == AgentTeamModel.team_id).where(AgentTeamModel.agent_id.in_(agent_ids), TeamModel.deleted_at.is_(None))
            team_ids = team_ids.union(select(TeamModel.id).where(TeamModel.id.in_(managed_teams), TeamModel.deleted_at.is_(None)))
            owner_teams = or_(owner_teams,
                exists(select(AgentTeamModel.id).where(AgentTeamModel.agent_id == Dataset.owner_agent_id, AgentTeamModel.team_id.in_(managed_teams))),
                exists(select(TeamUserModel.id).where(TeamUserModel.user_id == Dataset.owner_user_id, TeamUserModel.team_id.in_(managed_teams))))
    level = Dataset.group_access == 2 if write else Dataset.group_access >= 1
    return or_(exists(grants.where(or_(direct, DatasetGrant.team_id.in_(team_ids)))), and_(level, owner_teams))


def accessible_clause(actor: DataActor, *, write: bool = False, manage: bool = False) -> ColumnElement[bool]:
    allowed = owner_clause(actor) if manage else or_(owner_clause(actor),
        Dataset.global_access == 2 if write else Dataset.global_access >= 1, _principal_clause(actor, write=write))
    active = true() if isinstance(actor, int) else exists(select(UserModel.id).where(UserModel.id == actor.user_id, UserModel.is_active.is_(True)))
    return and_(active, allowed, ~Dataset.read_only if write else true())


async def access(dataset: Dataset, actor: DataActor) -> DatasetAccess:
    row = (await get_db().execute(select(
        exists(select(Dataset.id).where(Dataset.id == dataset.id, accessible_clause(actor))),
        exists(select(Dataset.id).where(Dataset.id == dataset.id, accessible_clause(actor, write=True))),
        exists(select(Dataset.id).where(Dataset.id == dataset.id, accessible_clause(actor, manage=True))),
    ))).one()
    manage = bool(row[2]) or (bool(row[0]) and await is_administrator(actor))
    return DatasetAccess(bool(row[0]), bool(row[1]), manage)


async def is_administrator(actor: DataActor) -> bool:
    return not isinstance(actor, int) and await check_privilege(await get_user_record(actor.user_id), "DATASET_ADMIN", get_db())
