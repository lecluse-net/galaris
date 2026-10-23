"""Live management delegation, independent of editable connection parameters."""
from sqlalchemy import select
import pytest
from app.connection import Connection
from app.skill import interface
from app.skill.contracts import SkillScope
from app.skill.resource_facade import can_manage_skill_resources, require_skill_management_access
from .test_personal_packages import agents, set_scope


@pytest.mark.asyncio
async def test_management_requires_both_live_scope_and_active_connection(db, agents):
    a, b, _ = agents
    assert await can_manage_skill_resources(a.id)
    await require_skill_management_access(a.id)
    connection = await db.scalar(select(Connection).where(Connection.agent_id == a.id))
    connection.active = False
    await db.commit()
    assert not await can_manage_skill_resources(a.id)
    with pytest.raises(PermissionError):
        await require_skill_management_access(a.id)
    await set_scope(b.id, SkillScope.USAGE)
    assert not await can_manage_skill_resources(b.id)
