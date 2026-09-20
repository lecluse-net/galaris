from typing import Sequence, Optional
from sqlalchemy import select, update as sql_update
from loguru import logger

from core.database import get_db
from core.team import audit

from .models import AgentGroup, Agent
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
        (await db.scalars(select(Agent.id).where(Agent.group_id == id))).all()
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
    """Soft delete an agent group. Detaches its agents first. Returns True if deleted."""
    db = get_db()
    result = await db.execute(select(AgentGroup).where(AgentGroup.id == id))
    group = result.scalar_one_or_none()
    if group is None:
        return False

    agent_ids = list(
        (await db.scalars(select(Agent.id).where(Agent.group_id == id))).all()
    )
    # Detach agents from the group being deleted
    await db.execute(
        sql_update(Agent).where(Agent.group_id == id).values(group_id=None)
    )

    audit("team.delete", {"before": {"id": group.id, "name": group.name, "order": group.order}})
    group.soft_delete()
    await db.commit()
    logger.info(f"Agent group deleted: {id}")
    for agent_id in agent_ids:
        await notify_agent_profile(agent_id, "update")
    return True
