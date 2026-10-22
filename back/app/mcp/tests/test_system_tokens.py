"""Runtime synchronization must preserve its principal across workers and failures."""

import asyncio
from uuid import uuid4

import pytest

from app.agent import Agent, Title
from app.mcp import mcp_token_service
from core.database import get_db_session
from core.user import UserModel


@pytest.mark.asyncio
async def test_concurrent_synchronizations_share_one_principal_until_deprovision(committed_database):
    async with get_db_session() as db:
        owner = UserModel(email=f"runtime-{uuid4().hex}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic", gender="X")
        db.add_all([owner, title])
        await db.flush()
        agent = Agent(user_id=owner.id, title_id=title.id, code=f"runtime-{uuid4().hex}",
                      first_name="Synthetic", last_name="Agent")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        _, external_bearer = await mcp_token_service.create_token_for_agent(agent_id)

    async def synchronize():
        async with get_db_session():
            return await mcp_token_service.ensure_system_token(agent_id)

    bearers = await asyncio.gather(*(synchronize() for _ in range(4)))
    assert len(set(bearers)) == 1
    async with get_db_session():
        principal = await mcp_token_service.get_enabled_system_token_by_value(bearers[0])
        assert principal is not None
        principal_id = principal.id
        assert await mcp_token_service.ensure_system_token(agent_id) == bearers[0]
        retained = await mcp_token_service.get_enabled_system_token_by_value(bearers[0])
        assert retained is not None and retained.id == principal_id
        assert await mcp_token_service.revoke_system_tokens(agent_id) == 1
        assert await mcp_token_service.get_enabled_system_token_by_value(bearers[0]) is None
        replacement = await mcp_token_service.ensure_system_token(agent_id)
        assert replacement != bearers[0]
        assert await mcp_token_service.get_enabled_token_by_value(agent_id, external_bearer) is not None


@pytest.mark.asyncio
async def test_corrupt_principal_is_not_silently_rotated(db):
    title = Title(label="Synthetic", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, code="corrupt-runtime-token", first_name="Synthetic", last_name="Agent")
    db.add(agent)
    await db.flush()
    bearer = await mcp_token_service.ensure_system_token(agent.id)
    principal = await mcp_token_service.get_enabled_system_token_by_value(bearer)
    assert principal is not None
    principal.token_hash = "0" * 64
    await db.commit()

    with pytest.raises(RuntimeError, match="token is inconsistent"):
        await mcp_token_service.ensure_system_token(agent.id)
    assert principal.token_hash == "0" * 64
