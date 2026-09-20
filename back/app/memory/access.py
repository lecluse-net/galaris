"""ACL predicates shared by memory services and retrieval queries."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import exists, or_, select, and_, true, false, union_all
from app.agent import Agent, AgentTeamModel
from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery
from sqlalchemy.orm import aliased, InstrumentedAttribute

from .contracts import MemoryAccess
from .models import MemoryItem, MemoryItemGrant, DocumentUserGrant, DocumentTeamGrant, DocumentAttachment, DocumentTag, DocumentTagAssignment


def _direct_readable_item_clause(agent_id: int) -> ColumnElement[bool]:
    """Build the SQL predicate applied before ranking or reading payloads."""

    item_grant = exists(
        select(MemoryItemGrant.id).where(
            MemoryItemGrant.item_id == MemoryItem.id,
            MemoryItemGrant.agent_id == agent_id,
        )
    )
    return or_(
        MemoryItem.owner_agent_id == agent_id,
        MemoryItem.visibility == "public",
        MemoryItem.global_access >= 1,
        item_grant,
        agent_team_grant_clause(agent_id),
    )


def _direct_readable_item_for_agents_clause(
    agent_ids: Collection[int] | None,
) -> ColumnElement[bool]:
    """Build the union of every managed Agent's readable-item scope."""

    if agent_ids is None:
        granted_item = exists(
            select(MemoryItemGrant.id).where(
                MemoryItemGrant.item_id == MemoryItem.id
            )
        )
        return or_(
            MemoryItem.owner_agent_id.is_not(None),
            MemoryItem.global_access >= 1,
            MemoryItem.group_access >= 1,
            granted_item,
            exists(select(DocumentTeamGrant.id).join(TeamModel, TeamModel.id == DocumentTeamGrant.team_id).where(DocumentTeamGrant.item_id == MemoryItem.id, TeamModel.deleted_at.is_(None))),
        )
    normalized_ids = tuple(sorted(set(agent_ids)))
    if not normalized_ids:
        return MemoryItem.id.is_(None)
    granted_item_ids = select(MemoryItemGrant.item_id).where(
        MemoryItemGrant.agent_id.in_(normalized_ids)
    )
    return or_(
        MemoryItem.owner_agent_id.in_(normalized_ids),
        MemoryItem.visibility == "public",
        MemoryItem.global_access >= 1,
        MemoryItem.id.in_(granted_item_ids),
        agent_team_grant_clause(normalized_ids),
    )


def _structural_access(direct: ColumnElement[bool], *, write: bool = False, user_id: int | None = None) -> ColumnElement[bool]:
    """Attachment access is live parent access, never a copied grant snapshot."""
    parents = select(MemoryItem.id).where(
        MemoryItem.node_kind == "document", MemoryItem.deleted_at.is_(None), direct,
    ).correlate(None)
    attachment_ids = select(DocumentAttachment.memory_item_id).where(
        DocumentAttachment.active.is_(True), DocumentAttachment.document_id.in_(parents),
    ).correlate(None)
    folder_ids = select(DocumentTag.memory_item_id).where(
        DocumentTag.deleted_at.is_(None), DocumentTag.memory_item_id.is_not(None),
    ).correlate(None)
    if user_id is None:
        # Each authorized document exposes its effective folders and ancestors,
        # across personal trees. UNION deduplicates and terminates even on cycles.
        ancestry = select(DocumentTag.id, DocumentTag.parent_id, DocumentTag.memory_item_id).join(
            DocumentTagAssignment, DocumentTagAssignment.tag_id == DocumentTag.id,
        ).where(DocumentTag.deleted_at.is_(None), DocumentTagAssignment.document_id.in_(parents)).cte(recursive=True)
        parent = aliased(DocumentTag)
        ancestry = ancestry.union(select(parent.id, parent.parent_id, parent.memory_item_id).join(
            ancestry, parent.id == ancestry.c.parent_id,
        ).where(parent.deleted_at.is_(None)))
        folder_access = MemoryItem.id.in_(select(ancestry.c.memory_item_id))
    else:
        # Human classification stays private; only agent graph visibility derives
        # from readable documents. Folder grants never authorize either surface.
        folder_access = and_(direct, MemoryItem.owner_user_id == user_id, MemoryItem.id.in_(folder_ids))
    return or_(
        and_(MemoryItem.node_kind.not_in(("attachment", "folder")), direct),
        and_(MemoryItem.node_kind == "folder", folder_access) if not write else false(),
        and_(MemoryItem.node_kind == "attachment", MemoryItem.id.in_(attachment_ids)) if not write else false(),
    )


def readable_item_clause(agent_id: int) -> ColumnElement[bool]:
    return _structural_access(_direct_readable_item_clause(agent_id))


def readable_item_for_agents_clause(agent_ids: Collection[int] | None) -> ColumnElement[bool]:
    return _structural_access(_direct_readable_item_for_agents_clause(agent_ids))


async def managed_item_agent_ids(
    item: MemoryItem,
    agent_ids: Collection[int] | None,
    *, team_access: dict[int, bool] | None = None,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return managed Agent ids with read access and with write access."""

    if item.node_kind in {"attachment", "folder"}:
        query = select(Agent.id)
        if agent_ids is not None:
            query = query.where(Agent.id.in_(agent_ids))
        visible: list[int] = []
        for identity in await get_db().scalars(query):
            if (await effective_access(item, identity)).can_read:
                visible.append(identity)
        return tuple(visible), ()
    scoped_ids = None if agent_ids is None else set(agent_ids)
    candidates = {
        grant.agent_id
        for grant in item.grants
        if scoped_ids is None or grant.agent_id in scoped_ids
    }
    if item.owner_agent_id is not None and (
        scoped_ids is None or item.owner_agent_id in scoped_ids
    ):
        candidates.add(item.owner_agent_id)
    if (item.visibility == "public" or item.global_access >= 1) and scoped_ids is not None:
        candidates.update(scoped_ids)

    if team_access is None:
        team_access = (await document_team_agent_access([item.id])).get(item.id, {})
    candidates.update(agent for agent in team_access if scoped_ids is None or agent in scoped_ids)
    readable: list[int] = []
    writable: list[int] = []
    grants = {grant.agent_id: grant for grant in item.grants}
    for agent_id in sorted(candidates):
        owned = item.owner_agent_id == agent_id
        grant = grants.get(agent_id)
        if owned or item.visibility == "public" or item.global_access >= 1 or grant is not None or agent_id in team_access:
            readable.append(agent_id)
        if not item.read_only and not item.source_managed and (
            owned or item.global_access == 2 or (grant is not None and grant.can_write) or team_access.get(agent_id, False)
        ):
            writable.append(agent_id)
    return tuple(readable), tuple(writable)


async def effective_access(item: MemoryItem, agent_id: int | HumanActor) -> MemoryAccess:
    """Resolve item and space permissions without relying on lazy loading."""

    if isinstance(agent_id, HumanActor):
        return await human_item_access(item, agent_id.user_id)
    if item.node_kind in {"attachment", "folder"}:
        readable = await get_db().scalar(select(MemoryItem.id).where(
            MemoryItem.id == item.id, readable_item_clause(agent_id),
        ))
        return MemoryAccess(can_read=readable is not None, can_write=False)
    if item.owner_agent_id == agent_id:
        return MemoryAccess(can_read=True, can_write=not item.read_only)
    team_read = bool(await get_db().scalar(select(agent_team_grant_clause(agent_id, item_id=item.id))))
    team_write = bool(await get_db().scalar(select(agent_team_grant_clause(agent_id, item_id=item.id, write=True))))
    can_read = item.visibility == "public" or item.global_access >= 1

    item_grant = next(
        (grant for grant in item.grants if grant.agent_id == agent_id),
        None,
    )
    can_read = can_read or item_grant is not None or team_read
    can_write = bool(
        not item.read_only
        and not item.source_managed
        and (
            item.global_access == 2
            or team_write
            or (item_grant is not None and item_grant.can_write)
        )
    )
    return MemoryAccess(can_read=can_read, can_write=can_write)


__all__ = [
    "effective_access",
    "managed_item_agent_ids",
    "readable_item_clause",
    "readable_item_for_agents_clause",
]

def owner_team_clause(
    team_id: object, *, owner_agent_id: object = MemoryItem.owner_agent_id,
    owner_user_id: object = MemoryItem.owner_user_id,
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
    explicit = select(DocumentTeamGrant.item_id, DocumentTeamGrant.team_id, DocumentTeamGrant.can_write).join(
        TeamModel, TeamModel.id == DocumentTeamGrant.team_id,
    ).where(TeamModel.deleted_at.is_(None))
    inherited = select(
        MemoryItem.id.label("item_id"), TeamModel.id.label("team_id"),
        (MemoryItem.group_access == 2).label("can_write"),
    ).select_from(MemoryItem).join(TeamModel, owner_team_clause(TeamModel.id)).where(
        MemoryItem.group_access > 0, MemoryItem.deleted_at.is_(None), TeamModel.deleted_at.is_(None),
    )
    if item_ids is not None:
        explicit = explicit.where(DocumentTeamGrant.item_id.in_(item_ids))
        inherited = inherited.where(MemoryItem.id.in_(item_ids))
    return union_all(explicit, inherited).subquery()


def agent_team_grant_clause(
    agent_ids: int | Collection[int] | ColumnElement[int] | InstrumentedAttribute[int],
    *, item_id: object = MemoryItem.id, write: bool = False,
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
    direct = select(DocumentUserGrant.id).where(
        DocumentUserGrant.item_id == MemoryItem.id, DocumentUserGrant.user_id == user_id,
    )
    permissions = document_team_permissions()
    teams = select(permissions.c.item_id).join(
        TeamUserModel, TeamUserModel.team_id == permissions.c.team_id,
    ).where(permissions.c.item_id == MemoryItem.id, TeamUserModel.user_id == user_id)
    if write:
        direct = direct.where(DocumentUserGrant.can_write.is_(True))
        teams = teams.where(permissions.c.can_write.is_(True))
    return and_(
        exists(select(UserModel.id).where(UserModel.id == user_id, UserModel.is_active.is_(True))),
        or_(MemoryItem.owner_user_id == user_id, MemoryItem.global_access == 2 if write else or_(MemoryItem.global_access >= 1, MemoryItem.visibility == "public"), exists(direct), exists(teams)),
        ~MemoryItem.read_only if write else true(),
        ~MemoryItem.source_managed if write else true(),
    )


def human_item_clause(user_id: int, *, write: bool = False) -> ColumnElement[bool]:
    return _structural_access(_direct_human_item_clause(user_id, write=write), write=write, user_id=user_id)


def human_document_clause(user_id: int, *, write: bool = False) -> ColumnElement[bool]:
    return and_(MemoryItem.node_kind == "document", human_item_clause(user_id, write=write))


async def human_item_access(item: MemoryItem, user_id: int) -> MemoryAccess:
    readable = await get_db().scalar(select(MemoryItem.id).where(
        MemoryItem.id == item.id, human_item_clause(user_id),
    ))
    writable = await get_db().scalar(select(MemoryItem.id).where(
        MemoryItem.id == item.id, human_item_clause(user_id, write=True),
    ))
    return MemoryAccess(can_read=readable is not None, can_write=writable is not None)


async def human_document_access(item: MemoryItem, user_id: int) -> MemoryAccess:
    if item.node_kind != "document":
        return MemoryAccess(can_read=False, can_write=False)
    return await human_item_access(item, user_id)

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
