from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.agent import active_run
from bridge.hermes.memory_provider import (
    bind_memory_context,
    clear_memory_context,
    get_memory_context,
    reset_memory_contexts,
)
from bridge.hermes.router import hermes_provider_search
from bridge.hermes.schemas import HermesMemorySearchRequest


def test_memory_provider_routes_keep_their_existing_urls() -> None:
    from bridge.hermes.router import router

    paths = {route.path for route in router.routes}
    assert "/hermes/reachable" in paths
    assert "/hermes/agents" in paths
    assert "/memory/provider/search" in paths
    assert "/memory/provider/remember" in paths


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
