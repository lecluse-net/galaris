from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from starlette.requests import Request
from pydantic import ValidationError

from app.agent import active_run
from bridge.hermes.memory_provider import (
    bind_memory_context,
    clear_memory_context,
    get_memory_context,
    reset_memory_contexts,
)
from bridge.hermes.router import hermes_provider_search
from bridge.hermes.schemas import HermesMemoryRememberRequest, HermesMemorySearchRequest


def test_legacy_hermes_memory_transport_requires_an_atomic_fact() -> None:
    with pytest.raises(ValidationError, match="JSON atomic fact"):
        HermesMemoryRememberRequest(content="Nina told me yesterday she wants reports.")
    request = HermesMemoryRememberRequest(
        content='{"predicate":"report_frequency","value":"weekly"}'
    )
    assert '"value":"weekly"' in request.content


def test_bridge_routes_keep_configuration_and_memory_without_legacy_management() -> None:
    from bridge.hermes.router import router

    paths = {route.path for route in router.routes}
    assert "/hermes/reachable" not in paths
    assert "/hermes/agents" not in paths
    assert "/hermes/configurations" in paths
    assert "/hermes/configurations/{id}" in paths
    assert "/memory/provider/search" in paths
    assert "/memory/provider/remember" in paths


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/hermes/reachable", "/api/hermes/agents"])
async def test_removed_management_endpoints_return_not_found(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 404


def test_memory_context_handoff_is_task_scoped() -> None:
    reset_memory_contexts()
    task_id = uuid4()
    other_task_id = uuid4()
    bind_memory_context(agent_id=7, task_id=task_id, context="exact brief")

    prepared = get_memory_context(agent_id=7, task_id=task_id)
    assert prepared is not None and prepared.context == "exact brief"
    assert get_memory_context(agent_id=7, task_id=other_task_id) is None
    clear_memory_context(agent_id=7, task_id=other_task_id)
    assert get_memory_context(agent_id=7, task_id=task_id) is not None
    clear_memory_context(agent_id=7, task_id=task_id)
    assert get_memory_context(agent_id=7, task_id=task_id) is None


@pytest.mark.asyncio
async def test_provider_returns_only_the_prepared_active_task_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()

    async def authenticated_agent(_request: Request) -> int:
        return 7

    monkeypatch.setattr(
        "bridge.hermes.router._memory_provider_agent_id", authenticated_agent
    )
    request = Request({"type": "http", "headers": []})
    reset_memory_contexts()
    bind_memory_context(agent_id=7, task_id=task_id, context="ranked once")

    with pytest.raises(HTTPException) as direct:
        await hermes_provider_search(
            HermesMemorySearchRequest(query="different runtime query"), request
        )
    assert direct.value.status_code == 409

    active_run.push(7, task_id)
    try:
        scoped = await hermes_provider_search(
            HermesMemorySearchRequest(query="different runtime query"), request
        )
    finally:
        active_run.pop(7, task_id)
        clear_memory_context(agent_id=7, task_id=task_id)

    assert scoped.context == "ranked once"
    assert scoped.memories == []
