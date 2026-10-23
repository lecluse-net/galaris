"""Live document ACLs, independent of personal memory and its indexes."""
from __future__ import annotations
from collections.abc import Collection
from uuid import UUID
from sqlalchemy import and_, exists, false, or_, select, true, union_all
from sqlalchemy.orm import aliased, InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery
from app.agent import Agent, AgentManagementScope, AgentTeamModel
from app.share import ShareGrant
from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel
from core.authorize import privilege_clause
from .models import Document
from .contracts import DocumentAccess
from .document_policy import document_policy_clause, orphan_process_clause

def owner_team_clause(
    team_id: object, *, owner_agent_id: object = Document.owner_agent_id,
    owner_user_id: object = Document.owner_user_id,
) -> ColumnElement[bool]:
    agent_membership, human_membership = aliased(AgentTeamModel), aliased(TeamUserModel)
    return or_(
        exists(select(agent_membership.id).where(
            agent_membership.team_id == team_id, agent_membership.agent_id == owner_agent_id,
        )),
        exists(select(human_membership.id).where(
            human_membership.team_id == team_id, human_membership.user_id == owner_user_id,
        )),
    )

def document_team_permissions(item_ids: Collection[UUID] | None = None) -> Subquery:
    """Explicit teams plus live teams of the document's Agent or human owner."""
    explicit = select(Document.id.label("item_id"), ShareGrant.team_id, ShareGrant.can_write).join(ShareGrant, ShareGrant.share_id == Document.share_id).join(
        TeamModel, TeamModel.id == ShareGrant.team_id,
    ).where(TeamModel.deleted_at.is_(None))
    inherited = select(
        Document.id.label("item_id"), TeamModel.id.label("team_id"),
        (Document.group_access == 2).label("can_write"),
    ).select_from(Document).join(TeamModel, owner_team_clause(TeamModel.id)).where(
        Document.group_access > 0, Document.deleted_at.is_(None), TeamModel.deleted_at.is_(None),
    )
    if item_ids is not None:
        explicit = explicit.where(Document.id.in_(item_ids))
        inherited = inherited.where(Document.id.in_(item_ids))
    return union_all(explicit, inherited).subquery()

def agent_team_grant_clause(
    agent_ids: int | Collection[int] | ColumnElement[int] | InstrumentedAttribute[int],
    *, item_id: object = Document.id, write: bool = False,
) -> ColumnElement[bool]:
    member_agent = aliased(Agent)
    member = member_agent.id.in_(agent_ids) if isinstance(agent_ids, Collection) else member_agent.id == agent_ids
    teams = document_team_permissions()
    query = select(teams.c.item_id).join(
        AgentTeamModel, AgentTeamModel.team_id == teams.c.team_id,
    ).join(member_agent, member_agent.id == AgentTeamModel.agent_id).where(
        teams.c.item_id == item_id, member, member_agent.deleted_at.is_(None),
    )
    if write:
        query = query.where(teams.c.can_write.is_(True))
    return exists(query)

def _direct_human_item_clause(user_id: int, *, write: bool = False) -> ColumnElement[bool]:
    direct = select(ShareGrant.id).where(
        ShareGrant.share_id == Document.share_id, ShareGrant.user_id == user_id,
    )
    permissions = document_team_permissions()
    teams = select(permissions.c.item_id).join(
        TeamUserModel, TeamUserModel.team_id == permissions.c.team_id,
    ).where(permissions.c.item_id == Document.id, TeamUserModel.user_id == user_id)
    if write:
        direct = direct.where(ShareGrant.can_write.is_(True))
        teams = teams.where(permissions.c.can_write.is_(True))
    return and_(
        exists(select(UserModel.id).where(UserModel.id == user_id, UserModel.is_active.is_(True))),
        or_(Document.owner_user_id == user_id,
            and_(orphan_process_clause(), privilege_clause(user_id, "PROCESS_ADMIN")),
            and_(Document.source_managed.is_(True), Document.visibility == "public") if not write else false(),
            and_(Document.node_kind == "document", or_(Document.global_access == 2 if write else Document.global_access >= 1, exists(direct), exists(teams)))),
        ~Document.read_only if write else true(),
        ~Document.source_managed if write else true(),
    )

async def document_team_agent_access(item_ids: Collection[UUID]) -> dict[UUID, dict[int, bool]]:
    permissions = document_team_permissions(item_ids)
    rows = await get_db().execute(select(permissions.c.item_id, Agent.id, permissions.c.can_write).join(
        AgentTeamModel, AgentTeamModel.team_id == permissions.c.team_id,
    ).join(Agent, Agent.id == AgentTeamModel.agent_id).where(Agent.deleted_at.is_(None)))
    result: dict[UUID, dict[int, bool]] = {}
    for item_id, agent_id, can_write in rows:
        current = result.setdefault(item_id, {})
        current[agent_id] = current.get(agent_id, False) or can_write
    return result

def readable_item_clause(agent_id: int | InstrumentedAttribute[int]) -> ColumnElement[bool]:
    return and_(document_policy_clause(), or_(Document.owner_agent_id == agent_id, Document.global_access >= 1,
        exists(select(ShareGrant.id).where(ShareGrant.share_id == Document.share_id, ShareGrant.agent_id == agent_id)),
        agent_team_grant_clause(agent_id)))


def writable_item_clause(agent_id: int | InstrumentedAttribute[int]) -> ColumnElement[bool]:
    return and_(document_policy_clause(), ~Document.read_only, or_(Document.owner_agent_id == agent_id, Document.global_access == 2,
        exists(select(ShareGrant.id).where(ShareGrant.share_id == Document.share_id, ShareGrant.agent_id == agent_id, ShareGrant.can_write.is_(True))),
        agent_team_grant_clause(agent_id, write=True)))


def readable_item_for_agents_clause(agent_ids: Collection[int] | None) -> ColumnElement[bool]:
    if agent_ids is None:
        granted = exists(select(ShareGrant.id).where(
            ShareGrant.share_id == Document.share_id,
            or_(ShareGrant.agent_id.is_not(None), ShareGrant.team_id.is_not(None)),
        ))
        return and_(document_policy_clause(), or_(Document.owner_agent_id.is_not(None),
            Document.global_access >= 1, Document.group_access >= 1, granted))
    ids=tuple(sorted(set(agent_ids)))
    if not ids:
        return false()
    return and_(document_policy_clause(), or_(Document.owner_agent_id.in_(ids), Document.global_access >= 1,
        exists(select(ShareGrant.id).where(ShareGrant.share_id == Document.share_id, ShareGrant.agent_id.in_(ids))),
        agent_team_grant_clause(ids)))


def human_item_clause(user_id: int, *, write: bool = False) -> ColumnElement[bool]:
    return and_(_direct_human_item_clause(user_id, write=write), document_policy_clause(user_id))


human_document_clause=human_item_clause


async def effective_access(item: Document, actor: int | HumanActor, **_options: object) -> DocumentAccess:
    if isinstance(actor, HumanActor):
        return await human_item_access(item, actor.user_id)
    row=(await get_db().execute(select(readable_item_clause(actor), writable_item_clause(actor)).where(Document.id == item.id))).one_or_none()
    return DocumentAccess(can_read=bool(row and row[0]), can_write=bool(row and row[1]))


async def human_item_access(item: Document, user_id: int) -> DocumentAccess:
    row=(await get_db().execute(select(human_item_clause(user_id), human_item_clause(user_id, write=True)).where(Document.id == item.id))).one_or_none()
    return DocumentAccess(can_read=bool(row and row[0]), can_write=bool(row and row[1]))


human_document_access=human_item_access


async def managed_item_agent_ids(item: Document, agent_ids: Collection[int] | None, *, team_access: dict[int,bool] | None = None) -> tuple[tuple[int,...],tuple[int,...]]:
    if team_access is not None and agent_ids is not None:
        candidates = set(agent_ids)
        readable = candidates.copy() if item.global_access >= 1 else set[int]()
        writable = candidates.copy() if item.global_access == 2 else set[int]()
        if item.owner_agent_id is not None and item.owner_agent_id in candidates:
            readable.add(item.owner_agent_id)
            writable.add(item.owner_agent_id)
        for grant in item.grants:
            if grant.agent_id is not None and grant.agent_id in candidates:
                readable.add(grant.agent_id)
                if grant.can_write:
                    writable.add(grant.agent_id)
        for identity, can_write in team_access.items():
            if identity in candidates:
                readable.add(identity)
                if can_write:
                    writable.add(identity)
        return tuple(sorted(readable)), () if item.read_only else tuple(sorted(writable))
    # One correlated statement preserves live memberships and avoids per-agent reads.
    candidates=select(Agent.id, readable_item_clause(Agent.id), writable_item_clause(Agent.id)).select_from(Agent).join(Document, Document.id == item.id)
    if agent_ids is not None:
        candidates=candidates.where(Agent.id.in_(agent_ids))
    rows=(await get_db().execute(candidates)).all()
    return tuple(row[0] for row in rows if row[1]),tuple(row[0] for row in rows if row[2])


def readable_workflow_document_clause(actor: int | AgentManagementScope) -> ColumnElement[bool]:
    if isinstance(actor,int):
        return readable_item_clause(actor)
    return or_(human_item_clause(actor.user_id),readable_item_for_agents_clause(actor.agent_ids))
