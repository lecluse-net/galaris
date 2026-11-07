"""Read-only shared-team directory for agents, independent of administration."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import String, func, literal, select, union_all

from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import UserModel

from .models import Agent, AgentTeam


# These JSON pages must survive the same ordinary history compaction as agent_list.
_PAGE_MAX_CHARS = 4_000


class TeamIdentity(BaseModel):
    id: int
    name: str


class TeamDirectoryEntry(TeamIdentity):
    description: str
    human_count: int
    agent_count: int


class TeamDirectoryMember(BaseModel):
    kind: Literal["agent", "user"]
    id: int
    name: str
    code: str | None = None
    job_title: str | None = None
    resource_uri: str | None = None


class DirectoryPage[T: BaseModel](BaseModel):
    items: list[T]
    count: int
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None


class TeamMembersPage(DirectoryPage[TeamDirectoryMember]):
    team: TeamIdentity


def _validate_page(search: str, offset: int, limit: int) -> str:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 500")
    if len(search) > 200:
        raise ValueError("search must contain at most 200 characters")
    return search.strip().lower()


def _preview(value: str, limit: int) -> str:
    value = " ".join(value.splitlines())
    return value if len(value) <= limit else value[:limit - 3].rstrip() + "..."


def _page[T: BaseModel](
    entries: list[T], *, offset: int, limit: int, max_chars: int = _PAGE_MAX_CHARS,
) -> DirectoryPage[T]:
    items: list[T] = []

    def result() -> DirectoryPage[T]:
        more = len(entries) > len(items)
        return DirectoryPage[T](items=items, count=len(items), offset=offset, limit=limit,
                                has_more=more, next_offset=offset + len(items) if more else None)

    for item in entries[:limit]:
        items.append(item)
        if len(result().model_dump_json()) > max_chars:
            items.pop()
            break
    return result()


async def list_team_directory(
    *, search: str = "", offset: int = 0, limit: int = 50,
) -> DirectoryPage[TeamDirectoryEntry]:
    """List active teams and current counts, without loading full profiles or avatars.

    This instance-wide discovery surface grants no contact, sharing or management
    rights. Humans with inactive accounts and soft-deleted agents are excluded.
    """
    search = _validate_page(search, offset, limit)
    humans = select(TeamUserModel.team_id, func.count().label("count")).join(
        UserModel, UserModel.id == TeamUserModel.user_id,
    ).where(UserModel.is_active.is_(True)).group_by(TeamUserModel.team_id).subquery()
    agents = select(AgentTeam.team_id, func.count().label("count")).join(
        Agent, Agent.id == AgentTeam.agent_id,
    ).where(Agent.deleted_at.is_(None)).group_by(AgentTeam.team_id).subquery()
    rows = await get_db().execute(select(
        TeamModel.id, TeamModel.name, TeamModel.description,
        func.coalesce(humans.c.count, 0), func.coalesce(agents.c.count, 0),
    ).outerjoin(humans, humans.c.team_id == TeamModel.id)
        .outerjoin(agents, agents.c.team_id == TeamModel.id)
        .where(TeamModel.deleted_at.is_(None), func.lower(TeamModel.name).contains(search, autoescape=True))
        .order_by(TeamModel.order, TeamModel.name, TeamModel.id).offset(offset).limit(limit + 1))
    return _page([
        TeamDirectoryEntry(id=identity, name=_preview(name, 200), description=_preview(description, 300),
                           human_count=human_count, agent_count=agent_count)
        for identity, name, description, human_count, agent_count in rows
    ], offset=offset, limit=limit)


async def list_team_members(
    team_id: int, *, kind: Literal["agent", "user"] | None = None,
    search: str = "", offset: int = 0, limit: int = 50,
) -> TeamMembersPage:
    """List one live team's humans and agents with an unambiguous (kind, id) identity.

    Human names use a neutral ID fallback instead of exposing login email addresses.
    Memberships and account state are read afresh on every call.
    """
    search = _validate_page(search, offset, limit)
    if team_id <= 0:
        raise ValueError("team_id must be positive")
    if kind not in (None, "agent", "user"):
        raise ValueError("kind must be agent or user")
    team = (await get_db().execute(select(TeamModel.id, TeamModel.name).where(
        TeamModel.id == team_id, TeamModel.deleted_at.is_(None),
    ))).one_or_none()
    if team is None:
        raise LookupError("Team not found")
    identity = TeamIdentity(id=team.id, name=_preview(team.name, 200))

    human_name = func.coalesce(func.nullif(func.trim(UserModel.display_name), ""),
                               literal("User ") + UserModel.id.cast(String))
    agent_name = func.coalesce(func.nullif(func.trim(Agent.first_name + " " + Agent.last_name), ""), Agent.code)
    members = union_all(
        select(literal("user").label("kind"), UserModel.id.label("id"), human_name.label("name"),
               literal(None, String).label("code"), literal(None, String).label("job_title"))
        .join(TeamUserModel, TeamUserModel.user_id == UserModel.id)
        .where(TeamUserModel.team_id == team_id, UserModel.is_active.is_(True)),
        select(literal("agent").label("kind"), Agent.id.label("id"), agent_name.label("name"),
               Agent.code.label("code"), Agent.job_title.label("job_title"))
        .join(AgentTeam, AgentTeam.agent_id == Agent.id)
        .where(AgentTeam.team_id == team_id, Agent.deleted_at.is_(None)),
    ).subquery()
    query = select(members).where(func.lower(members.c.name).contains(search, autoescape=True))
    if kind is not None:
        query = query.where(members.c.kind == kind)
    rows = await get_db().execute(query.order_by(func.lower(members.c.name), members.c.kind, members.c.id)
                                  .offset(offset).limit(limit + 1))
    page = _page([
        TeamDirectoryMember(kind=member_kind, id=identity, name=_preview(name, 200),
                            code=_preview(code, 100) if code else None, job_title=_preview(job, 100) if job else None,
                            resource_uri=f"galaris://agent/{identity}" if member_kind == "agent" else None)
        for member_kind, identity, name, code, job in rows
    ], offset=offset, limit=limit, max_chars=_PAGE_MAX_CHARS - len(identity.model_dump_json()) - 8)
    return TeamMembersPage(team=identity,
                           items=page.items, count=page.count, offset=page.offset, limit=page.limit,
                           has_more=page.has_more, next_offset=page.next_offset)
