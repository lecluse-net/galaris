"""Agents maintain their own canonical contacts through the native MCP surface."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agent.models import Agent, Title
from app.memory import ContactCoordinates, MemoryNotFoundError
from app.memory.tests.conftest import memory_storage as memory_storage
from app.tools import McpToolContext
from app.tools.mcp_loader import build_galaris_fastmcp, load_mcp_tools


@pytest.mark.asyncio
async def test_contact_tools_are_discovered_mounted_and_scoped_by_the_server():
    names = {"contact_list", "contact_get", "contact_create", "contact_update"}
    definitions = {item.name: item for item in load_mcp_tools() if item.name in names}
    assert definitions.keys() == names
    assert {item.tool_code for item in definitions.values()} == {"galaris"}
    assert all(item.conversation_policy == "short" for item in definitions.values())
    assert definitions["contact_update"].approval == "ask"
    server = build_galaris_fastmcp(7, runtime="internal", enabled_tool_codes={"galaris"})
    tools = {item.name: item for item in await server.list_tools()}
    assert names <= tools.keys()
    for name in names:
        assert {"ctx", "agent_id", "owner_agent_id"}.isdisjoint(tools[name].parameters["properties"])
    files = build_galaris_fastmcp(7, runtime="internal", enabled_tool_codes={"file_sharing"})
    file_tools = {item.name: item for item in await files.list_tools()}
    for name in ("file_write", "file_edit"):
        assert {"ctx", "agent_id", "actor_agent_id", "owner_agent_id", "management_scope"}.isdisjoint(
            file_tools[name].parameters["properties"])
    assert tools["contact_list"].parameters["properties"]["limit"]["maximum"] == 500
    other = build_galaris_fastmcp(7, runtime="internal", enabled_tool_codes={"memory"})
    assert names.isdisjoint(item.name for item in await other.list_tools())


@pytest.mark.asyncio
async def test_agent_can_create_find_read_and_update_only_its_own_contacts(db, memory_storage):
    from app.contact import mcp

    title = Title(label="Synthetic contact MCP", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, first_name="Synthetic", last_name=f"Contacts {i}", code=uuid4().hex)
              for i in range(2)]
    db.add_all(agents)
    await db.flush()
    owner, other = [McpToolContext(agent_id=agent.id, runtime="internal") for agent in agents]
    coordinates = ContactCoordinates.model_validate({
        "phone_numbers": [{"label": "Work", "number": "+33 1 23 45 67 89", "country": "FR"}],
        "postal_addresses": [{"city": "Synthetic City", "country": "FR"}],
    })
    created = await mcp.mcp_contact_create(owner, "Synthetic Person", email="synthetic@example.org", coordinates=coordinates)
    identifier = UUID(created["memory_item_id"])
    await db.commit()
    db.expunge_all()
    page = await mcp.mcp_contact_list(owner, query="synthetic@example.org", limit=500)
    assert page["total"] == 1 and page["items"][0]["memory_item_id"] == str(identifier)
    assert (await mcp.mcp_contact_get(owner, identifier))["coordinates"] == coordinates.model_dump(mode="json")
    renamed = await mcp.mcp_contact_update(owner, identifier, "Renamed Person")
    assert renamed["coordinates"] == created["coordinates"]
    assert renamed["identities"] == created["identities"]
    assert (await mcp.mcp_contact_list(other))["total"] == 0
    for inaccessible in (identifier, uuid4()):
        with pytest.raises(MemoryNotFoundError, match="Contact not found"):
            await mcp.mcp_contact_get(other, inaccessible)
        with pytest.raises(MemoryNotFoundError, match="Contact not found"):
            await mcp.mcp_contact_update(other, inaccessible, "Unauthorized rename", ContactCoordinates())
    assert (await mcp.mcp_contact_get(owner, identifier))["display_name"] == "Renamed Person"
    replacement = ContactCoordinates.model_validate({
        "phone_numbers": [{"number": "+41 21 555 01 02", "country": "CH"}],
        "postal_addresses": [{"city": "Synthetic Replacement City", "country": "CH"}],
    })
    await mcp.mcp_contact_update(owner, identifier, "Renamed Person", replacement)
    await db.commit()
    db.expunge_all()
    reopened = await mcp.mcp_contact_get(owner, identifier)
    assert reopened["coordinates"] == replacement.model_dump(mode="json")
    assert reopened["identities"] == created["identities"]
    cleared = await mcp.mcp_contact_update(owner, identifier, "Renamed Person", ContactCoordinates())
    assert cleared["coordinates"] == {"phone_numbers": [], "postal_addresses": []}
    assert cleared["identities"] == created["identities"]
    with pytest.raises(ValidationError):
        await mcp.mcp_contact_create(owner, "Missing coordinates")
    with pytest.raises(ValidationError):
        await mcp.mcp_contact_create(owner, "Invalid email", email="invalid")
    for kwargs in ({"limit": 501}, {"offset": -1}, {"query": "x" * 501}):
        with pytest.raises(ValueError):
            await mcp.mcp_contact_list(owner, **kwargs)
