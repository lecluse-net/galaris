from typing import Sequence, Optional
from sqlalchemy import delete as sql_delete, select
from loguru import logger

from core.database import get_db
from core.team import audit, lock_team_sharing, refresh_team_access

from .models import AgentGroup, AgentTeam
from .observers import notify_agent_profile
from .schemas import AgentGroupCreate, AgentGroupUpdate


async def get_all(skip: int = 0, limit: int = 50) -> Sequence[AgentGroup]:
    """Get all agent groups, ordered by display order then name."""
    db = get_db()
    query = select(AgentGroup).order_by(AgentGroup.order, AgentGroup.name).offset(skip).limit(limit)
    query = AgentGroup.histo_filter(query)
    result = await db.execute(query)
    return result.scalars().all()


async def get(id: int) -> Optional[AgentGroup]:
    """Get an agent group by ID."""
    db = get_db()
    query = select(AgentGroup).where(AgentGroup.id == id)
    query = AgentGroup.histo_filter(query)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create(group_data: AgentGroupCreate) -> AgentGroup:
    """Create a new agent group."""
    db = get_db()
    new_group = AgentGroup(**group_data.model_dump())
    db.add(new_group)
    await db.flush()
    audit("team.save", {"before": None, "after": {"id": new_group.id, "name": new_group.name, "order": new_group.order}})
    await db.commit()
    await db.refresh(new_group)
    logger.info(f"Agent group created: {new_group.name}")
    return new_group


async def update(id: int, group_update: AgentGroupUpdate) -> Optional[AgentGroup]:
    """Update an existing agent group."""
    db = get_db()
    result = await db.execute(select(AgentGroup).where(AgentGroup.id == id))
    group = result.scalar_one_or_none()
    if group is None:
        return None

    agent_ids = list(
        (await db.scalars(select(AgentTeam.agent_id).where(AgentTeam.team_id == id))).all()
    )
    update_data = group_update.model_dump(exclude_unset=True)
    before = {"id": group.id, "name": group.name, "order": group.order}
    for key, value in update_data.items():
        setattr(group, key, value)

    audit("team.save", {"before": before, "after": {"id": group.id, "name": group.name, "order": group.order}})
    await db.commit()
    await db.refresh(group)
    logger.info(f"Agent group updated: {group.name}")
    for agent_id in agent_ids:
        await notify_agent_profile(agent_id, "update")
    return group


async def delete(id: int) -> bool:
    """Archive the group, refresh affected rights, and detach its agents atomically."""
    db = get_db()
    await lock_team_sharing()
    result = await db.execute(select(AgentGroup).where(AgentGroup.id == id).with_for_update())
    group = result.scalar_one_or_none()
    if group is None:
        return False

    agent_ids = list(
        (await db.scalars(select(AgentTeam.agent_id).where(AgentTeam.team_id == id))).all()
    )
    audit("team.delete", {"before": {"id": group.id, "name": group.name, "order": group.order}})
    group.soft_delete()
    # Legacy owner-group rules still need the former member identities here.
    await refresh_team_access(id, None)
    await db.execute(
        sql_delete(AgentTeam).where(AgentTeam.team_id == id)
    )

    await db.commit()
    logger.info(f"Agent group deleted: {id}")
    for agent_id in agent_ids:
        await notify_agent_profile(agent_id, "update")
    return True
