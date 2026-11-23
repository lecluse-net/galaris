"""Agents maintain their own canonical contacts through the native MCP surface."""

from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.agent.models import Agent, AgentTeam, Title
from app.connection.facade import get_or_create_connection, set_connection_function_state, set_management_scope
from app.contact import service
from app.contact.facade import is_known_mail_contact
from app.contact.schemas import ContactCreate
from app.memory import ContactCoordinates, MemoryNotFoundError
from app.memory.tests.conftest import memory_storage as memory_storage
from app.services import McpToolContext
from app.services.mcp_loader import build_galaris_fastmcp, load_mcp_tools
from app.services.models import Service
from core.team import TeamModel


async def _connect(db, agent_id):
    service_id = await db.scalar(select(Service.id).where(Service.code == "contact"))
    assert service_id is not None
    return await get_or_create_connection(service_id, agent_id, active=True)


@pytest.mark.asyncio
async def test_contact_tools_are_discovered_mounted_and_scoped_by_the_server(db):
    title = Title(label="Synthetic contact tool discovery", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, first_name="Synthetic", last_name="Tool Discovery", code=uuid4().hex)
    db.add(agent)
    await db.flush()
    names = {"contact_list", "contact_get", "contact_create", "contact_update"}
    definitions = {item.name: item for item in load_mcp_tools() if item.name in names}
    assert definitions.keys() == names
    assert {item.service_code for item in definitions.values()} == {"contact"}
    assert all(item.conversation_policy == "short" for item in definitions.values())
    assert definitions["contact_update"].approval == "ask"
    server = build_galaris_fastmcp(agent.id, runtime="internal", enabled_service_codes={"contact"})
    tools = {item.name: item for item in await server.list_tools()}
    assert names <= tools.keys()
    for name in names:
        properties = tools[name].parameters["properties"]
        assert {"ctx", "agent_id", "management_scope"}.isdisjoint(properties)
        assert ("owner_agent_id" in properties) == (name in {"contact_list", "contact_create"})
    files = build_galaris_fastmcp(agent.id, runtime="internal", enabled_service_codes={"file_sharing"})
    file_tools = {item.name: item for item in await files.list_tools()}
    for name in ("file_write", "file_edit"):
        assert {"ctx", "agent_id", "actor_agent_id", "owner_agent_id", "management_scope"}.isdisjoint(
            file_tools[name].parameters["properties"])
    assert tools["contact_list"].parameters["properties"]["limit"]["maximum"] == 500
    other = build_galaris_fastmcp(agent.id, runtime="internal", enabled_service_codes={"memory"})
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
    for agent in agents:
        await _connect(db, agent.id)
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


@pytest.mark.asyncio
async def test_contact_mcp_checks_delegation_and_function_permissions_on_every_call(db, memory_storage):
    title = Title(label="Synthetic delegated contact operator", gender="X")
    team = TeamModel(name="Synthetic contact team")
    db.add_all([title, team])
    await db.flush()
    caller, teammate, outsider = [
        Agent(title_id=title.id, code=uuid4().hex, first_name="Synthetic", last_name=name, agent_driver="internal")
        for name in ("Caller", "Teammate", "Outsider")
    ]
    db.add_all([caller, teammate, outsider])
    await db.flush()
    db.add_all([AgentTeam(agent_id=agent.id, team_id=team.id) for agent in (caller, teammate)])
    await db.commit()
    connection = await _connect(db, caller.id)
    teammate_connection = await _connect(db, teammate.id)
    # A grant on the owner never authorizes the caller's write.
    await set_connection_function_state(connection.id, "contact_update", "disabled")
    await set_connection_function_state(teammate_connection.id, "contact_update", "enabled")
    contacts = [
        await service.create_contact(ContactCreate(agent_id=agent.id, display_name=name, email=email))
        for agent, name, email in [
            (caller, "Synthetic C", "caller@example.org"),
            (teammate, "Synthetic B", "teammate@example.org"),
            (outsider, "Synthetic A", "outsider@example.org"),
        ]
    ]
    own, peer, foreign = [str(contact.memory_item_id) for contact in contacts]
    server = build_galaris_fastmcp(caller.id, runtime="internal", enabled_service_codes={"contact"})

    async with Client(server) as client:
        async def call(name, **args):
            return await client.call_tool(f"contact_{name}", args, raise_on_error=False)

        async def page(**args):
            result = await call("list", query="Synthetic", **args)
            assert not result.is_error
            return result.structured_content

        assert [item["memory_item_id"] for item in (await page())["items"]] == [own]
        assert (await call("get", contact_id=peer)).is_error
        await set_management_scope(connection.id, "team", authorized=True)
        first = await page(limit=1)
        assert first["total"] == 2 and first["has_more"]
        assert [item["memory_item_id"] for item in first["items"]] == [peer]
        assert [item["memory_item_id"] for item in (await page(limit=1, offset=1))["items"]] == [own]
        assert [item["memory_item_id"] for item in (await page(owner_agent_id=teammate.id))["items"]] == [peer]
        assert (await call("list", owner_agent_id=outsider.id)).is_error
        assert (await call("get", contact_id=peer)).structured_content["owner_agent_id"] == teammate.id
        assert (await call("get", contact_id=foreign)).is_error
        assert (await call("update", contact_id=peer, display_name="Synthetic Denied")).is_error

        for name in ("contact_create", "contact_update"):
            await set_connection_function_state(connection.id, name, "enabled")
        assert (await call("update", contact_id=foreign, display_name="Synthetic Denied")).is_error
        assert (await call("create", owner_agent_id=outsider.id, display_name="Synthetic Denied",
                           email="denied@example.org")).is_error
        updated = await call("update", contact_id=peer, display_name="Synthetic Renamed")
        assert updated.structured_content["display_name"] == "Synthetic Renamed"
        created = await call("create", owner_agent_id=teammate.id, display_name="Synthetic New", email="new@example.org")
        assert created.structured_content["owner_agent_id"] == teammate.id
        assert await is_known_mail_contact(agent_id=teammate.id, address="new@example.org")
        assert not await is_known_mail_contact(agent_id=caller.id, address="new@example.org")
        await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == teammate.id, AgentTeam.team_id == team.id))
        await db.commit()
        assert (await page())["total"] == 1
        assert (await call("update", contact_id=peer, display_name="Synthetic Revoked")).is_error

        await set_management_scope(connection.id, "all", authorized=True)
        assert (await page())["total"] == 4
        assert (await call("get", contact_id=foreign)).structured_content["owner_agent_id"] == outsider.id
        await set_management_scope(connection.id, None, authorized=True)
        assert (await page())["total"] == 1
        assert (await call("get", contact_id=foreign)).is_error
        connection.active = False
        await db.commit()
        assert (await call("list")).is_error
