"""Team catalogue and human memberships; callers own transaction completion."""

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from core.user import UserModel

from .contracts import HumanInfo, TeamInfo, TeamWrite
from .models import Team, TeamAudit, TeamUser


_access_observers: dict[str, Callable[[], Awaitable[None]]] = {}


def register_team_access_observer(key: str, callback: Callable[[], Awaitable[None]]) -> None:
    """Subscribe at bootstrap to committed changes affecting team-based access."""
    _access_observers[key] = callback


async def notify_team_access_changed() -> None:
    """Call only after the membership/deletion transaction has committed."""
    for callback in tuple(_access_observers.values()):
        await callback()


def audit(action: str, details: dict[str, object]) -> None:
    get_db().add(TeamAudit(action=action, details=details))


async def require_team(team_id: int) -> Team:
    team = await get_db().scalar(select(Team).where(Team.id == team_id).with_for_update())
    if team is None:
        raise LookupError("Team not found")
    return team


async def list_teams() -> list[TeamInfo]:
    teams = (await get_db().scalars(select(Team).order_by(Team.order, Team.name, Team.id))).all()
    return await _team_summaries(teams)


async def _team_summaries(teams: Sequence[Team]) -> list[TeamInfo]:
    if not teams:
        return []
    counts = dict((await get_db().execute(
        select(TeamUser.team_id, func.count()).join(UserModel, UserModel.id == TeamUser.user_id)
        .where(TeamUser.team_id.in_([team.id for team in teams]))
        .group_by(TeamUser.team_id)
    )).tuples().all())
    small_teams = [team.id for team in teams if 0 < counts.get(team.id, 0) <= 3]
    previews: dict[int, list[HumanInfo]] = {}
    if small_teams:
        rows = await get_db().execute(
            select(TeamUser.team_id, UserModel).join(UserModel, UserModel.id == TeamUser.user_id)
            .where(TeamUser.team_id.in_(small_teams)).order_by(UserModel.id)
        )
        for team_id, user in rows:
            previews.setdefault(team_id, []).append(_human_info(user))
    return [TeamInfo.model_validate(team).model_copy(update={
        "human_count": counts.get(team.id, 0), "human_members": previews.get(team.id, []),
    }) for team in teams]


def _human_info(user: UserModel) -> HumanInfo:
    return HumanInfo(id=user.id, label=user.display_name or user.email,
                     active=user.is_active, avatar_url=user.avatar_url)


async def save_team(data: TeamWrite, team_id: int | None = None) -> TeamInfo:
    values = data.model_dump()
    if "order" not in data.model_fields_set:
        del values["order"]
        if team_id is None:
            last_order = await get_db().scalar(select(func.max(Team.order)))
            values["order"] = (last_order if last_order is not None else -1) + 1
    values["name"] = data.name.strip()
    if not values["name"]:
        raise ValueError("Team name is required")
    team = await require_team(team_id) if team_id is not None else Team()
    summary_fields = {"human_count", "human_members"}
    before = TeamInfo.model_validate(team).model_dump(exclude=summary_fields) if team_id is not None else None
    for key, value in values.items():
        setattr(team, key, value)
    get_db().add(team)
    await get_db().flush()
    after = (await _team_summaries([team]))[0]
    audit("team.save", {"before": before, "after": after.model_dump(exclude=summary_fields)})
    return after


async def delete_team(team_id: int) -> None:
    team = await require_team(team_id)
    audit("team.delete", {"before": TeamInfo.model_validate(team).model_dump()})
    team.soft_delete()


async def move_team(team_id: int, target_team_id: int, *, after: bool) -> None:
    # Lock in primary-key order so simultaneous moves serialize without lock inversion.
    locked = (await get_db().scalars(select(Team).order_by(Team.id).with_for_update())).all()
    by_id = {team.id: team for team in locked}
    if team_id not in by_id or target_team_id not in by_id:
        raise LookupError("Team not found")
    if team_id == target_team_id:
        return
    ordered = list((await get_db().scalars(select(Team).order_by(Team.order, Team.name, Team.id))).all())
    before = [team.id for team in ordered]
    moved = by_id[team_id]
    target = by_id[target_team_id]
    ordered.remove(moved)
    ordered.insert(ordered.index(target) + int(after), moved)
    if before == [team.id for team in ordered]:
        return
    for position, team in enumerate(ordered):
        team.order = position
    audit("team.reorder", {"before": before, "after": [team.id for team in ordered]})


async def search_humans(search: str = "", limit: int = 500) -> list[HumanInfo]:
    statement = select(UserModel).order_by(UserModel.id).limit(limit)
    if search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(UserModel.display_name.ilike(term) | UserModel.email.ilike(term))
    return [_human_info(user)
            for user in (await get_db().scalars(statement)).all()]


async def human_memberships() -> dict[int, set[int]]:
    rows = await get_db().execute(select(TeamUser.user_id, TeamUser.team_id).join(Team, Team.id == TeamUser.team_id))
    result: dict[int, set[int]] = {}
    for user_id, team_id in rows:
        result.setdefault(user_id, set()).add(team_id)
    return result


async def team_humans(team_id: int) -> list[HumanInfo]:
    await require_team(team_id)
    rows = (await get_db().scalars(select(UserModel).join(TeamUser, TeamUser.user_id == UserModel.id)
                                  .where(TeamUser.team_id == team_id).order_by(UserModel.id))).all()
    return [_human_info(u) for u in rows]


async def set_human_membership(team_id: int, user_id: int, present: bool) -> None:
    await require_team(team_id)
    if await get_db().scalar(select(UserModel.id).where(UserModel.id == user_id)) is None:
        raise LookupError("User not found")
    before = await get_db().scalar(select(TeamUser.id).where(TeamUser.team_id == team_id, TeamUser.user_id == user_id))
    if present:
        await get_db().execute(insert(TeamUser).values(team_id=team_id, user_id=user_id).on_conflict_do_nothing())
    else:
        await get_db().execute(delete(TeamUser).where(TeamUser.team_id == team_id, TeamUser.user_id == user_id))
    audit("team.human", {"team": team_id, "user": user_id, "before": before is not None, "after": present})
