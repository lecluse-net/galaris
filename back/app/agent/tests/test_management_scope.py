"""Contract tests for the human Agent-management boundary."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.agent import management_scope as scope_service
from app.agent.models import Agent, Title
from app.agent.assertions import AgentManagerAssertion
from app.agent.management_scope import AgentManagementScope
from app.agent import openai_service
from core.authorize import AssertionContext
from core.authorize import request_privilege_cache, role_id_ctx
from core.authorize.models import Assignment, Privilege, Role
from core.user import UserModel as User


@pytest.mark.asyncio
async def test_local_manager_scope_contains_only_assigned_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = cast(User, SimpleNamespace(id=7))
    rows = MagicMock()
    rows.all.return_value = [11, 12]
    db = MagicMock()
    db.scalars = AsyncMock(return_value=rows)
    check_privilege = AsyncMock(return_value=False)
    monkeypatch.setattr(scope_service, "check_privilege", check_privilege)

    scope = await scope_service.management_scope_for(user, db)

    assert scope == AgentManagementScope(user_id=7, agent_ids=frozenset({11, 12}))
    statement = db.scalars.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "agents.user_id = 7" in compiled


@pytest.mark.asyncio
async def test_global_manager_scope_is_unrestricted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = cast(User, SimpleNamespace(id=7))
    db = MagicMock()
    db.scalars = AsyncMock()
    monkeypatch.setattr(
        scope_service,
        "check_privilege",
        AsyncMock(return_value=True),
    )

    scope = await scope_service.management_scope_for(user, db)

    assert scope.is_global
    assert scope.agent_ids is None
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_manager_assertion_accepts_global_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.scalar = AsyncMock(return_value=99)
    monkeypatch.setattr(
        "app.agent.assertions.check_privilege",
        AsyncMock(return_value=True),
    )

    allowed = await AgentManagerAssertion().assert_route(
        "update_agent",
        {"id": 42},
        AssertionContext(user=cast(User, SimpleNamespace(id=7)), db=db),
    )

    assert allowed


@pytest.mark.asyncio
async def test_openai_agent_catalog_applies_management_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(openai_service, "get_db", lambda: db)

    response = await openai_service.list_agent_models(agent_ids=frozenset({11, 12}))

    assert response.data == []
    statement = db.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "agents.id IN (11, 12)" in compiled


def test_empty_management_scope_denies_every_agent() -> None:
    scope = AgentManagementScope(user_id=7, agent_ids=frozenset())

    assert not scope.allows(None)
    assert not scope.allows(11)


@pytest_asyncio.fixture
async def scoped_manager(db):
    owner = User(email="scope-cache-owner@example.com", hashed_password="unused", is_active=True)
    other = User(email="scope-cache-other@example.com", hashed_password="unused", is_active=True)
    title = Title(label="Scope test", gender="M")
    global_privilege = await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL"))
    assert global_privilege is not None
    local = Role(code="scope-cache-local", privileges=[])
    global_role = Role(code="scope-cache-global", privileges=[global_privilege])
    db.add_all([owner, other, title, local, global_role])
    await db.flush()
    agent = Agent(code="scope-cache-agent", first_name="Scope", last_name="Test",
                  title_id=title.id, user_id=owner.id, agent_driver="internal")
    db.add_all([agent, Assignment(user_id=owner.id, role_id=local.id),
                Assignment(user_id=owner.id, role_id=global_role.id)])
    await db.commit()
    return owner, other, agent, local.id, global_role.id


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["pending", "bulk", "commit", "rollback", "savepoint"])
async def test_cached_scope_observes_reassignment_and_transaction_boundaries(db, scoped_manager, mutation):
    owner, other, agent, local_id, global_id = scoped_manager
    agent_id, owner_id, other_id = agent.id, owner.id, other.id
    token = role_id_ctx.set(local_id)
    try:
        with request_privilege_cache():
            assert (await scope_service.management_scope_for(owner, db)).allows(agent_id)
            assert not (await scope_service.management_scope_for(other, db)).allows(agent_id)
            role_id_ctx.set(global_id)
            assert (await scope_service.management_scope_for(owner, db)).is_global
            role_id_ctx.set(local_id)
            assert not (await scope_service.management_scope_for(owner, db)).is_global
            nested = await db.begin_nested() if mutation == "savepoint" else None
            if mutation == "pending":
                agent.user_id = other_id
            else:
                await db.execute(update(Agent).where(Agent.id == agent_id).values(user_id=other_id))
            assert not (await scope_service.management_scope_for(owner, db)).allows(agent_id)
            assert (await scope_service.management_scope_for(other, db)).allows(agent_id)
            if nested is not None:
                await nested.rollback()
            elif mutation == "rollback":
                await db.rollback()
                await db.refresh(owner)
            else:
                await db.commit()
                await db.execute(update(Agent).where(Agent.id == agent_id).values(user_id=owner_id))
                await db.commit()
            assert (await scope_service.management_scope_for(owner, db)).allows(agent_id)
    finally:
        role_id_ctx.reset(token)


@pytest.mark.asyncio
async def test_scope_context_expires_for_detached_tasks(db, scoped_manager):
    owner, other, agent, local_id, _ = scoped_manager
    agent_id = agent.id
    proceed = asyncio.Event()

    async def later():
        await proceed.wait()
        return await scope_service.management_scope_for(owner, db)

    token = role_id_ctx.set(local_id)
    try:
        with request_privilege_cache():
            assert (await scope_service.management_scope_for(owner, db)).allows(agent_id)
            task = asyncio.create_task(later())
        await db.execute(update(Agent).where(Agent.id == agent_id).values(user_id=other.id))
        await db.commit()
        proceed.set()
        assert not (await task).allows(agent_id)
        assert not (await scope_service.management_scope_for(owner, db)).allows(agent_id)
    finally:
        role_id_ctx.reset(token)
