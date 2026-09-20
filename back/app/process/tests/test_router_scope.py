"""Agent-scope guarantees for the human process API."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agent import AgentManagementScope
from app.process import router


@pytest.mark.asyncio
async def test_definition_agent_filter_accepts_only_managed_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_definitions = AsyncMock(return_value=[])
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(1, frozenset({7}))),
    )
    monkeypatch.setattr(router.process_service, "list_definitions", list_definitions)

    assert await router.read_definitions(agent_id=7) == []
    list_definitions.assert_awaited_once_with(
        agent_id=7,
        agent_ids=frozenset({7}),
    )

    list_definitions.reset_mock()
    with pytest.raises(HTTPException) as exc_info:
        await router.read_definitions(agent_id=8)

    assert exc_info.value.status_code == 404
    list_definitions.assert_not_awaited()


@pytest.mark.asyncio
async def test_operations_agent_filter_uses_selected_managed_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = object()
    get_operations = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(1, frozenset({7, 9}))),
    )
    monkeypatch.setattr(router.process_service, "get_operations", get_operations)

    assert await router.read_process_operations(agent_id=9) is expected
    get_operations.assert_awaited_once_with(agent_ids=frozenset({9}))


@pytest.mark.asyncio
async def test_global_agent_scope_can_filter_processes_for_any_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_definitions = AsyncMock(return_value=[])
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(1, None)),
    )
    monkeypatch.setattr(router.process_service, "list_definitions", list_definitions)

    assert await router.read_definitions(agent_id=42) == []
    list_definitions.assert_awaited_once_with(agent_id=42, agent_ids=None)


@pytest.mark.asyncio
async def test_export_cannot_cross_agent_scope(monkeypatch):
    from uuid import uuid4
    from types import SimpleNamespace
    from app.process import router
    from app.process import export
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, frozenset({7}))))
    monkeypatch.setattr(router.process_service, "get_run", AsyncMock(return_value=SimpleNamespace(launcher_agent_id=8)))
    operation = AsyncMock()
    monkeypatch.setattr(export, "export_run", operation)
    with pytest.raises(HTTPException) as denied:
        await router.export_process_run(uuid4(), after_event=0, page_size=50)
    assert denied.value.status_code == 404
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_requires_authenticated_admin(client):
    from uuid import uuid4
    from core.database import get_db_session
    from core.user.models import User
    from core.user.user_service import encrypt_password
    url = f"/api/processes/runs/{uuid4()}/export"
    assert (await client.get(url)).status_code == 401
    email = f"export-{uuid4()}@example.com"
    async with get_db_session() as db:
        db.add(User(email=email, hashed_password=encrypt_password("export-password"), is_active=True))
    login = await client.post('/api/auth/login-json', json={"email": email, "password": "export-password"})
    assert login.status_code == 200
    assert (await client.get(url, headers={"Authorization": f"Bearer {login.json()['access_token']}"})).status_code == 403
