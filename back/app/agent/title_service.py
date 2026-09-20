from typing import Sequence, Optional
from sqlalchemy import select

from core.database import get_db
from .models import Agent, Title
from .observers import notify_agent_profile
from .schemas import TitleCreate, TitleUpdate

from loguru import logger


async def get_all(skip: int = 0, limit: int = 50) -> Sequence[Title]:
    """Get all titles with pagination."""
    logger.info("Listing titles")
    db = get_db()
    query = select(Title).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get(id: int) -> Optional[Title]:
    """Get a title by ID."""
    db = get_db()
    result = await db.execute(select(Title).where(Title.id == id))
    return result.scalar_one_or_none()


async def create(title_data: TitleCreate) -> Title:
    """Create a new title."""
    db = get_db()
    new_title = Title(**title_data.model_dump())
    db.add(new_title)
    await db.commit()
    await db.refresh(new_title)
    logger.info(f"Title created: {new_title.label}")
    return new_title


async def update(id: int, title_update: TitleUpdate) -> Optional[Title]:
    """Update an existing title."""
    db = get_db()
    result = await db.execute(select(Title).where(Title.id == id))
    title = result.scalar_one_or_none()
    if title is None:
        return None

    agent_ids = list(
        (await db.scalars(select(Agent.id).where(Agent.title_id == id))).all()
    )
    update_data = title_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(title, key, value)

    await db.commit()
    await db.refresh(title)
    logger.info(f"Title updated: {title.label}")
    for agent_id in agent_ids:
        await notify_agent_profile(agent_id, "update")
    return title


async def delete(id: int) -> bool:
    """Delete a title. Returns True if deleted, False if not found."""
    db = get_db()
    result = await db.execute(select(Title).where(Title.id == id))
    title = result.scalar_one_or_none()
    if title is None:
        return False

    await db.delete(title)
    await db.commit()
    logger.info(f"Title deleted: {id}")
    return True
