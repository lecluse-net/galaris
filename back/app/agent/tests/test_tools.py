import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart


@pytest.mark.asyncio
@pytest.mark.parametrize("size,limit,escaped", [
    (16, 50, False), (63, 50, False), (63, 2, False), (0, 50, False), (16, 500, True),
])
async def test_directory_can_be_enumerated_after_history_compaction(monkeypatch, size, limit, escaped):
    from app.agent import tools
    from app.harness.runtime import compact_agent_history

    agents = [
        SimpleNamespace(
            id=index + 1, code=f"synthetic-{index:03}",
            first_name=f"Synthetic {index:03}" + ("\x00" * 50 if escaped else ""),
            last_name="Example" + ('"' * 50 if escaped else ""),
            job_title="Research specialist " + ("\x00" * 200 if escaped else "domain " * 20),
            job_description="<p>Synthetic description</p>" * 100,
            personality="<p>Synthetic personality</p>" * 100,
            title=None,
        )
        for index in range(size)
    ]

    async def get_all(*, skip=0, limit=50):
        return agents[skip:skip + limit]

    monkeypatch.setattr(tools.agent_service, "get_all", get_all)
    resolve_llm = AsyncMock(return_value=None)
    monkeypatch.setattr(tools.llm_service, "get_llm_for_agent", resolve_llm)
    offset = 0
    seen = []
    while True:
        result = await tools.list_agents(
            limit=limit, language="fr", **({"offset": offset} if offset else {}),
        )
        # Other discovery tools in the same batch can age the directory before
        # the next model request. Every entry and the cursor must still be usable.
        messages = [
            ModelResponse(parts=[ToolCallPart("agent_list", {"offset": offset}, "directory")]),
            ModelRequest(parts=[ToolReturnPart("agent_list", result, "directory")]),
        ]
        for index in range(8):
            messages.extend([
                ModelResponse(parts=[ToolCallPart("discovery", {}, f"other-{index}")]),
                ModelRequest(parts=[ToolReturnPart("discovery", "done", f"other-{index}")]),
            ])
        compacted = compact_agent_history(messages, max_chars=32_000)
        part = compacted[1].parts[0]
        assert isinstance(part, ToolReturnPart)
        assert part.content == result
        page = json.loads(part.content)
        assert page["offset"] == offset
        assert page["limit"] == limit
        assert page["count"] == len(page["items"]) <= limit
        for item in page["items"]:
            agent = agents[item["id"] - 1]
            assert item["resource_uri"] == f"galaris://agent/{agent.id}"
            assert item["code"] == agent.code
            assert item["name"] == f"{agent.first_name} {agent.last_name}"
            assert item["job_title"].startswith("Research specialist")
            seen.append(item["id"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        assert page["count"] > 0
        assert page["next_offset"] == offset + page["count"]
        offset = page["next_offset"]

    assert seen == [agent.id for agent in agents]
    # Detailed profiles/model resolution belong to agent_get, so listing needs
    # no per-agent query on the context-bound AsyncSession.
    resolve_llm.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"offset": -1}, {"limit": 0}, {"limit": 501}])
async def test_directory_rejects_invalid_pagination_before_reading(monkeypatch, arguments):
    from app.agent import tools

    read = AsyncMock()
    monkeypatch.setattr(tools.agent_service, "get_all", read)
    with pytest.raises(ValueError):
        await tools.list_agents(**arguments)
    read.assert_not_awaited()
