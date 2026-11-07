"""Synthetic directory journeys: mixed identities, bounded discovery and live policy."""

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from fastmcp import Client
import pytest
from sqlalchemy import delete, select

from app.agent import list_team_directory, list_team_members
from app.agent.models import Agent, AgentTeam, Title
from app.tools import mandatory_tools, mcp_loader
from core.team import TeamModel, TeamUserModel
from core.user import UserModel


async def directory(db):
    manager = UserModel(id=40000, email="directory-manager@example.test", hashed_password="unused")
    human = UserModel(id=40001, email="private-login@example.test", display_name="Synthetic Member", hashed_password="unused")
    unnamed = UserModel(id=40002, email="private-fallback@example.test", hashed_password="unused")
    inactive = UserModel(email="inactive@example.test", display_name="Inactive", is_active=False, hashed_password="unused")
    title = Title(label="Synthetic directory", gender="F")
    team = TeamModel(name="Synthetic directory Alpha", description="A synthetic shared team")
    duplicate = TeamModel(name=team.name)
    empty = TeamModel(name="Synthetic directory Empty")
    literal = TeamModel(name="Synthetic directory 100%_team")
    retired = TeamModel(name="Synthetic directory Retired", deleted_at=datetime.now(timezone.utc))
    db.add_all([manager, human, unnamed, inactive, title, team, duplicate, empty, literal, retired])
    await db.flush()
    caller = Agent(id=40000, user_id=manager.id, title_id=title.id, code="synthetic-directory-caller",
                   first_name="Caller", last_name="", agent_driver="internal")
    # Human and agent IDs deliberately overlap; names can also coincide.
    peer = Agent(id=human.id, user_id=human.id, title_id=title.id, code="synthetic-directory-peer",
                 first_name="Synthetic", last_name="Member", job_title="Researcher", agent_driver="internal")
    deleted = Agent(user_id=manager.id, title_id=title.id, code="synthetic-directory-deleted",
                    first_name="Deleted", last_name="", deleted_at=datetime.now(timezone.utc))
    db.add_all([caller, peer, deleted])
    await db.flush()
    db.add_all([
        AgentTeam(agent_id=peer.id, team_id=team.id), AgentTeam(agent_id=peer.id, team_id=duplicate.id),
        AgentTeam(agent_id=deleted.id, team_id=team.id), AgentTeam(agent_id=caller.id, team_id=retired.id),
        TeamUserModel(user_id=human.id, team_id=team.id), TeamUserModel(user_id=human.id, team_id=duplicate.id),
        TeamUserModel(user_id=unnamed.id, team_id=team.id), TeamUserModel(user_id=inactive.id, team_id=team.id),
    ])
    await db.flush()
    return SimpleNamespace(caller=caller, peer=peer, human=human, unnamed=unnamed, team=team,
                           duplicate=duplicate, empty=empty, literal=literal, retired=retired)


@pytest.mark.asyncio
async def test_directory_lists_empty_teams_homonyms_and_live_mixed_memberships(db):
    from app.agent import AgentScopeDeniedError, require_agent_contact

    data = await directory(db)
    teams = await list_team_directory(search="  SYNTHETIC DIRECTORY  ", limit=500)
    assert {item.id for item in teams.items} == {data.team.id, data.duplicate.id, data.empty.id, data.literal.id}
    selected = next(item for item in teams.items if item.id == data.team.id)
    assert (selected.human_count, selected.agent_count) == (2, 1)
    assert [item.id for item in (await list_team_directory(search="%_")).items] == [data.literal.id]
    assert not (await list_team_directory(search="Unknown synthetic team")).items

    offset, identities = 0, []
    while True:
        page = await list_team_members(data.team.id, limit=1, offset=offset)
        assert page.team.id == data.team.id and page.team.name == data.team.name
        identities.extend((item.kind, item.id) for item in page.items)
        payload = page.model_dump_json()
        assert "@example.test" not in payload and "hashed_password" not in payload and "avatar" not in payload
        if page.next_offset is None:
            break
        offset = page.next_offset
    assert identities == [("agent", data.peer.id), ("user", data.human.id), ("user", data.unnamed.id)]
    humans = await list_team_members(data.team.id, kind="user")
    assert humans.items[-1].name == f"User {data.unnamed.id}"
    agents = await list_team_members(data.team.id, kind="agent", search="  SYNTHETIC MEMBER ")
    assert [item.id for item in agents.items] == [data.peer.id]
    assert agents.items[0].resource_uri == f"galaris://agent/{data.peer.id}"
    assert agents.items[0].job_title == "Researcher"
    assert not (await list_team_members(data.empty.id)).items
    assert not (await list_team_members(data.team.id, search="%_")).items
    with pytest.raises(AgentScopeDeniedError):
        await require_agent_contact(data.caller.id, peer_agent_id=data.peer.id)

    # Fresh calls reflect removals, account deactivation and team deletion.
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == data.peer.id, AgentTeam.team_id == data.team.id))
    data.human.is_active = False
    await db.flush()
    assert [(item.kind, item.id) for item in (await list_team_members(data.team.id)).items] == [("user", data.unnamed.id)]
    selected = next(item for item in (await list_team_directory(search="Alpha")).items if item.id == data.team.id)
    assert (selected.human_count, selected.agent_count) == (1, 0)
    assert [item.id for item in (await list_team_members(data.duplicate.id, kind="agent")).items] == [data.peer.id]
    data.team.soft_delete()
    await db.flush()
    for identity in (data.team.id, data.retired.id, 999999):
        with pytest.raises(LookupError, match="Team not found"):
            await list_team_members(identity)
    assert [item.id for item in (await list_team_directory(search="Alpha")).items] == [data.duplicate.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"offset": -1}, {"limit": 0}, {"limit": 501}, {"search": "x" * 201},
])
async def test_directory_rejects_invalid_pagination_before_reading(arguments, monkeypatch):
    import app.agent.team_directory as module

    def forbidden():
        pytest.fail("Invalid arguments must fail before querying")

    monkeypatch.setattr(module, "get_db", forbidden)
    for call in (list_team_directory, lambda **kw: list_team_members(1, **kw)):
        with pytest.raises(ValueError):
            await call(**arguments)
    for identity in (0, -1):
        with pytest.raises(ValueError):
            await list_team_members(identity)
    with pytest.raises(ValueError):
        await list_team_members(1, kind="invalid")


@pytest.mark.asyncio
async def test_long_directory_pages_survive_history_compaction_without_omissions(db):
    from app.harness.runtime import compact_agent_history
    from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

    data = await directory(db)
    teams = [TeamModel(name=f"Synthetic budget {index:03} " + "\x01" * 200, description="\x01" * 400)
             for index in range(16)]
    members = [UserModel(email=f"budget-{index}@example.test", display_name=f"Budget {index:03} " + "\x01" * 80,
                         hashed_password="unused") for index in range(63)]
    db.add_all([*teams, *members])
    await db.flush()
    data.team.name = "\x01" * 200
    db.add_all([TeamUserModel(team_id=data.team.id, user_id=human.id) for human in members])
    await db.flush()
    for function, expected in (
        (lambda offset: list_team_directory(search="Synthetic budget", offset=offset, limit=500),
         [(None, team.id) for team in teams]),
        (lambda offset: list_team_members(data.team.id, search="Budget", offset=offset, limit=500),
         [("user", human.id) for human in members]),
    ):
        seen, offset = [], 0
        while True:
            page = await function(offset)
            payload = page.model_dump_json()
            assert len(payload) <= 4000
            messages = [ModelResponse(parts=[ToolCallPart("directory", {}, "read")]),
                        ModelRequest(parts=[ToolReturnPart("directory", payload, "read")])]
            for index in range(8):
                messages.extend([ModelResponse(parts=[ToolCallPart("other", {}, str(index))]),
                                 ModelRequest(parts=[ToolReturnPart("other", "done", str(index))])])
            compacted = compact_agent_history(messages, max_chars=32000)
            assert compacted[1].parts[0].content == payload
            seen.extend((getattr(item, "kind", None), item.id) for item in page.items)
            if page.next_offset is None:
                assert not page.has_more
                break
            assert page.count > 0 and page.next_offset == offset + page.count
            offset = page.next_offset
        assert seen == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
async def test_real_mcp_directory_needs_no_admin_and_rechecks_revocation(inference_db, runtime):
    from app.connection import facade as connections
    from app.connection.models import Connection
    from app.tools.models import Tool
    from core.user import user_service

    db = inference_db
    data = await directory(db)
    await mandatory_tools.sync_integrated_tool_connections(data.caller.id)
    connection = await db.scalar(select(Connection).join(Tool).where(
        Connection.agent_id == data.caller.id, Tool.code == "galaris"))
    await db.commit()
    user_service.set_current_user(None)
    definitions = await mcp_loader.list_enabled_native_mcp_definitions(
        data.caller.id, runtime=runtime, conversation_only=True)
    assert {"team_list", "team_members"} <= {item.name for item in definitions}
    assert not any(item.tool_code == "agent_admin" for item in definitions)
    server = mcp_loader.build_galaris_fastmcp(data.caller.id, runtime=runtime, enabled_tool_codes={"galaris"})
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        for name in ("team_list", "team_members"):
            properties = tools[name].input_schema["properties"]
            assert "ctx" not in properties
            assert properties["limit"]["default"] == 50
            assert properties["limit"]["minimum"] == 1 and properties["limit"]["maximum"] == 500
            assert mcp_loader.execution_policy_for_tool(name) == ("read", "safe")
        result = await client.call_tool("team_list", {"search": "Alpha"})
        teams = json.loads(result.content[0].text)
        assert {item["id"] for item in teams["items"]} == {data.team.id, data.duplicate.id}
        result = await client.call_tool("team_members", {"team_id": data.team.id, "kind": "agent"})
        assert [item["id"] for item in json.loads(result.content[0].text)["items"]] == [data.peer.id]
        for arguments in ({"team_id": 0}, {"team_id": data.team.id, "limit": 501},
                          {"team_id": data.team.id, "kind": "human"}):
            assert (await client.call_tool("team_members", arguments, raise_on_error=False)).is_error
        missing = await client.call_tool("team_members", {"team_id": 999999}, raise_on_error=False)
        assert missing.is_error and "team_list" in missing.content[0].text
        await connections.set_connection_function_state(connection.id, "team_members", "disabled")
        await db.commit()
        assert "team_members" not in {tool.name for tool in await client.list_tools()}
        assert (await client.call_tool("team_members", {"team_id": data.team.id}, raise_on_error=False)).is_error
        assert not (await client.call_tool("team_list", {})).is_error
        await connections.set_connection_function_state(connection.id, "team_members", "enabled")
        await db.commit()
        assert "team_members" in {tool.name for tool in await client.list_tools()}
        assert not (await client.call_tool("team_members", {"team_id": data.empty.id})).is_error
        await connections.set_tool_function_state(connection.tool_id, "team_list", "disabled")
        await db.commit()
        assert "team_list" not in {tool.name for tool in await client.list_tools()}
        assert (await client.call_tool("team_list", {}, raise_on_error=False)).is_error
