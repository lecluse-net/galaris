"""Process-owned ACLs for native definitions, including orphan recovery."""

from app.share import sharing_permission_clause
from app.agent import sharing_principals, sharing_owner_teams

from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from app.agent import Agent, AgentManagementScope
from core.authorize import privilege_clause
from core.user import UserModel

from .models import ProcessDefinition as Definition

ProcessActor = int | AgentManagementScope


def administrator(actor: ProcessActor) -> ColumnElement[bool]:
    return false() if isinstance(actor, int) else privilege_clause(actor.user_id, "PROCESS_ADMIN")


def owner_active() -> ColumnElement[bool]:
    return or_(exists(select(Agent.id).where(Agent.id == Definition.agent_id, Agent.deleted_at.is_(None))),
        exists(select(UserModel.id).where(UserModel.id == Definition.owner_user_id, UserModel.is_active.is_(True))))


def policy_clause(actor: ProcessActor) -> ColumnElement[bool]:
    return or_(owner_active(), administrator(actor))


def owner_clause(actor: ProcessActor) -> ColumnElement[bool]:
    if isinstance(actor, int):
        return Definition.agent_id == actor
    managed = Definition.agent_id.is_not(None) if actor.agent_ids is None else Definition.agent_id.in_(actor.agent_ids)
    return or_(Definition.owner_user_id == actor.user_id, managed)


def _principal_clause(actor: ProcessActor, *, write: bool) -> ColumnElement[bool]:
    return sharing_permission_clause(Definition.share_id, sharing_principals(actor),
        sharing_owner_teams(Definition.agent_id, Definition.owner_user_id), write=write)


def accessible_clause(actor: ProcessActor, *, write: bool = False, manage: bool = False) -> ColumnElement[bool]:
    owned = or_(owner_clause(actor), administrator(actor))
    allowed = owned if manage else or_(owned,
        Definition.global_access == 2 if write else Definition.global_access >= 1, _principal_clause(actor, write=write))
    active = true() if isinstance(actor, int) else exists(select(UserModel.id).where(UserModel.id == actor.user_id, UserModel.is_active.is_(True)))
    return and_(Definition.code.is_not(None), active, policy_clause(actor), allowed)
