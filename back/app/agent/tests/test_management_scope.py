"""Contract tests for the human Agent-management boundary."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import management_scope as scope_service
from app.agent.assertions import AgentManagerAssertion
from app.agent.management_scope import AgentManagementScope
from app.agent import openai_service
from core.authorize import AssertionContext
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
