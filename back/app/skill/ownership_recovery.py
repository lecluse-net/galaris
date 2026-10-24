"""Recover filesystem ownership transitions using their transactional receipts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from core.util import complete_io

from . import storage
from .models import Skill, SkillOwnershipRelease


async def recover_pending_ownership(session: AsyncSession) -> None:
    """Caller holds the catalogue lock; serialize with personal owner mutations too."""
    await complete_io(storage.prune_incomplete_ownership_staging)
    for state in storage.pending_ownership_releases():
        owner = int(str(state["owner"]))
        source_owner = int(str(state["source_owner"])) if state.get("source_owner") is not None else None
        for agent in sorted({owner} | ({source_owner} if source_owner is not None else set())):
            await session.scalar(select(Agent.id).where(Agent.id == agent).with_for_update()
                                 .execution_options(include_historized=True))
        record = await session.scalar(select(Skill).where(Skill.id == int(str(state["skill_id"])))
            .with_for_update().execution_options(include_historized=True, populate_existing=True))
        if record is None:
            raise RuntimeError("Ownership recovery cannot find its package; originals retained")
        receipt = await session.get(SkillOwnershipRelease, UUID(str(state["operation"])))
        release = state.get("direction", "release") == "release"
        expected_owner = (None if release else owner) if receipt else (owner if release else source_owner)
        expected_code = state["target_code"] if receipt else state["code"]
        if record.owner_agent_id != expected_owner or record.code != expected_code:
            raise RuntimeError("Ownership recovery found conflicting identity; originals retained")
        await complete_io(storage.recover_ownership_release, str(state["operation"]),
                          committed=receipt is not None, deleted=record.is_historized)
