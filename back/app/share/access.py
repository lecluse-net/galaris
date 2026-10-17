"""One SQL grant evaluator, usable before counts and pagination."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, and_, exists, false, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from .models import ShareConfig, ShareGrant


@dataclass(frozen=True)
class Principals:
    agent_ids: Select[tuple[int]]
    team_ids: Select[tuple[int]]
    user_id: int | None


def permission_clause(
    share_id: ColumnElement[UUID] | InstrumentedAttribute[UUID],
    principals: Principals,
    owner_teams: Select[tuple[int]],
    *,
    write: bool = False,
) -> ColumnElement[bool]:
    # Correlate grants to the immediately enclosing policy, not a resource two
    # SELECT levels above (implicit correlation would add that resource locally).
    direct = select(ShareGrant.id).where(
        ShareGrant.share_id == ShareConfig.id,
        or_(
            ShareGrant.agent_id.in_(principals.agent_ids),
            ShareGrant.team_id.in_(principals.team_ids),
            ShareGrant.user_id == principals.user_id if principals.user_id is not None else false(),
        ),
    )
    if write:
        direct = direct.where(ShareGrant.can_write.is_(True))
    # Keep owner membership as a correlated SELECT. Turning it into a derived
    # table would detach its owner from the resource being authorized.
    shared_team = exists(
        owner_teams.where(owner_teams.selected_columns[0].in_(principals.team_ids))
    )
    return exists(
        select(ShareConfig.id).where(
            ShareConfig.id == share_id,
            or_(
                ShareConfig.global_access == 2 if write else ShareConfig.global_access >= 1,
                exists(direct),
                and_(
                    ShareConfig.group_access == 2 if write else ShareConfig.group_access >= 1,
                    shared_team,
                ),
            ),
        )
    )
