import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_list_agents_resolves_assigned_llms_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import tools

    agents = [
        SimpleNamespace(
            id=agent_id,
            first_name=f"Agent {agent_id}",
            last_name="Test",
            title=None,
            job_title="",
            job_description="",
            personality="",
        )
        for agent_id in range(1, 4)
    ]
    active_resolutions = 0
    max_active_resolutions = 0

    async def get_all(*, limit: int) -> list[SimpleNamespace]:
        assert limit == 50
        return agents

    async def resolve_llm(_agent: object) -> None:
        nonlocal active_resolutions, max_active_resolutions
        active_resolutions += 1
        max_active_resolutions = max(max_active_resolutions, active_resolutions)
        await asyncio.sleep(0)
        active_resolutions -= 1

    monkeypatch.setattr(tools.agent_service, "get_all", get_all)
    monkeypatch.setattr(tools.llm_service, "get_llm_for_agent", resolve_llm)

    result = await tools.list_agents(language="en")

    assert "Agent 1 Test" in result
    assert max_active_resolutions == 1
