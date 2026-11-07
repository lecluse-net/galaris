import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart


@pytest.mark.asyncio
async def test_directory_mcp_exposes_optional_bounded_team_filters():
    from fastmcp import FastMCP
    from app.tools.mcp_loader import add_galaris_tools

    server = FastMCP("Synthetic agent directory")
    add_galaris_tools(server, 1, runtime="internal", enabled_tool_codes={"galaris"})
    directory = next(tool for tool in await server.list_tools() if tool.name == "agent_list")
    properties = directory.parameters["properties"]
    assert "ctx" not in properties
    assert {"team_id", "team_name"}.isdisjoint(directory.parameters.get("required", []))
    identifier = next(option for option in properties["team_id"]["anyOf"] if option["type"] == "integer")
    name = next(option for option in properties["team_name"]["anyOf"] if option["type"] == "string")
    assert identifier["exclusiveMinimum"] == 0
    assert name["minLength"] == 1 and name["maxLength"] == 255


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

    async def get_all(*, skip=0, limit=50, team_id=None, team_name=None):
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
@pytest.mark.parametrize("arguments", [
    {"offset": -1}, {"limit": 0}, {"limit": 501}, {"team_id": 0},
    {"team_id": -1}, {"team_name": ""}, {"team_name": " \t"}, {"team_name": "x" * 256},
])
async def test_directory_rejects_invalid_arguments_before_reading(monkeypatch, arguments):
    from app.agent import tools

    read = AsyncMock()
    monkeypatch.setattr(tools.agent_service, "get_all", read)
    with pytest.raises(ValueError):
        await tools.list_agents(**arguments)
    read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["id", "name", "both"])
async def test_directory_filters_current_team_members_before_pagination(db, selector):
    from datetime import datetime, timezone

    from app.agent import agent_service, mcp
    from app.agent.models import Agent, AgentTeam, Title
    from app.tools.mcp_loader import McpToolContext
    from core.team import TeamModel
    from core.user import UserModel
    from sqlalchemy import delete

    title = Title(label="Synthetic colleague", gender="M")
    team = TeamModel(name="Synthetic Research")
    same_name = TeamModel(name=team.name)
    other = TeamModel(name="Synthetic Research Extended")
    retired = TeamModel(name="Synthetic Retired", deleted_at=datetime.now(timezone.utc))
    manager = UserModel(email="synthetic-directory@example.test", hashed_password="unused", is_active=True)
    db.add_all([title, team, same_name, other, retired, manager])
    await db.flush()
    agents = [
        Agent(user_id=manager.id, title_id=title.id, code=f"directory-team-{index}",
              first_name=f"Synthetic {index}", last_name="Example")
        for index in range(6)
    ]
    db.add_all(agents)
    await db.flush()
    # Non-members sort between members; one member belongs to multiple teams.
    db.add_all([
        AgentTeam(agent_id=agents[index].id, team_id=team.id) for index in (1, 3, 5)
    ] + [
        AgentTeam(agent_id=agents[1].id, team_id=other.id),
        AgentTeam(agent_id=agents[1].id, team_id=same_name.id),
        AgentTeam(agent_id=agents[0].id, team_id=other.id),
        AgentTeam(agent_id=agents[2].id, team_id=retired.id),
    ])
    agents[5].deleted_at = datetime.now(timezone.utc)
    await db.flush()
    ctx = McpToolContext(agents[0].id, "internal")
    filters = {}
    if selector in {"id", "both"}:
        filters["team_id"] = team.id
    if selector in {"name", "both"}:
        filters["team_name"] = "  SYNTHETIC research  "

    first = json.loads(await mcp.list_agents(ctx, limit=1, **filters))
    assert [item["id"] for item in first["items"]] == [agents[1].id]
    assert first["has_more"] and first["next_offset"] == 1
    second = json.loads(await mcp.list_agents(ctx, limit=1, offset=first["next_offset"], **filters))
    assert [item["id"] for item in second["items"]] == [agents[3].id]
    assert not second["has_more"] and second["next_offset"] is None

    # Existing caller scopes and driver selection still restrict the result.
    assert await agent_service.get_all(agent_ids=[agents[0].id], **filters) == []
    assert await agent_service.get_all(agent_driver="hermes", **filters) == []
    for missing in ({"team_id": retired.id}, {"team_name": retired.name},
                    {"team_id": team.id, "team_name": other.name},
                    {"team_name": "Unknown synthetic team"}, {"team_name": "Synthetic %"},
                    {"team_id": other.id + 100000}):
        page = json.loads(await mcp.list_agents(ctx, **missing))
        assert page["items"] == [] and page["next_offset"] is None

    # Membership changes take effect on the next call, without a cached directory.
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == agents[1].id))
    page = json.loads(await mcp.list_agents(ctx, **filters))
    assert [item["id"] for item in page["items"]] == [agents[3].id]
