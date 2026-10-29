"""Dataset ACL predicates, evaluated before listing, reading or writing."""

from app.share import sharing_permission_clause
from app.agent import sharing_principals, sharing_owner_teams

from sqlalchemy import and_, exists, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from app.agent import AgentManagementScope
from core.database import get_db
from core.authorize import check_privilege
from core.user import UserModel, get_user_record

from .contracts import DataActor, DatasetAccess
from .models import Dataset


def owner_clause(actor: DataActor) -> ColumnElement[bool]:
    if isinstance(actor, int):
        return Dataset.owner_agent_id == actor
    owned = Dataset.owner_user_id == actor.user_id
    if isinstance(actor, AgentManagementScope):
        managed = Dataset.owner_agent_id.is_not(None) if actor.agent_ids is None else Dataset.owner_agent_id.in_(actor.agent_ids)
        return or_(owned, managed)
    return owned


def _principal_clause(actor: DataActor, *, write: bool) -> ColumnElement[bool]:
    return sharing_permission_clause(Dataset.share_id, sharing_principals(actor),
        sharing_owner_teams(Dataset.owner_agent_id, Dataset.owner_user_id), write=write)


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
    return not isinstance(actor, int) and await check_privilege(await get_user_record(actor.user_id), ["DOCUMENT_ADMIN", "DATASET_ADMIN"], get_db())
