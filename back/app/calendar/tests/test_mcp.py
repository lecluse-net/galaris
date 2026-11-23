"""Agent scoping for the Calendar MCP family."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastmcp import Client
from sqlalchemy import delete, select

from app.agent.models import Agent, AgentTeam
from app.calendar import mcp
from app.calendar.crypto import decrypt
from app.calendar.models import CalendarFeed, CalendarTrigger
from app.calendar.resources import list_calendar_resources, read_calendar_resource
from app.calendar.schemas import CalendarAvailability, CalendarFeedRead
from app.connection.facade import set_connection_function_state, set_management_scope
from app.services import sync_integrated_service_connections
from app.services.mcp_loader import McpToolContext, build_agent_mcp
from app.services.permission_catalog import agent_permission_catalog
from core.team import TeamModel


@pytest.mark.asyncio
async def test_calendar_list_is_scoped_to_current_agent(monkeypatch) -> None:
    observed = []

    async def list_feeds(connection):
        observed.append((connection.agent_id, connection.id))
        return [SimpleNamespace(model_dump=lambda **_kwargs: {"agent_id": connection.agent_id})]

    monkeypatch.setattr(mcp.service, "list_tool_feeds", list_feeds)
    monkeypatch.setattr(mcp.service, "active_connection_for_agent", AsyncMock(return_value=SimpleNamespace(id=13, agent_id=42)))
    monkeypatch.setattr(mcp, "memory_read_enabled", AsyncMock(return_value=False))
    result = await mcp.calendar_list(McpToolContext(agent_id=42, runtime="internal"))
    assert result == [{"agent_id": 42}]
    assert observed == [(42, 13)]


@pytest.mark.asyncio
async def test_calendar_availability_is_scoped_to_current_agent(monkeypatch) -> None:
    observed = []

    async def availability(agent_id, start, end, *, calendar_ids=None, tool_connection=None):
        observed.append((agent_id, calendar_ids))
        return CalendarAvailability(start=start, end=end, available=True)

    monkeypatch.setattr(mcp.service, "availability_for_agent", availability)
    monkeypatch.setattr(mcp.service, "active_connection_for_agent", AsyncMock())
    result = await mcp.calendar_is_available(
        McpToolContext(agent_id=42, runtime="internal"),
        "2026-08-24T09:00:00Z",
        "2026-08-24T10:00:00Z",
        calendar_ids=[3],
    )

    assert result["available"] is True
    assert observed == [(42, [3])]


@pytest.mark.asyncio
async def test_calendar_scope_governs_live_mcp_reads_and_writes(db, agent, personal, calendar_connection):
    import json
    from datetime import datetime, timedelta, timezone

    from app.calendar import service
    from app.connection import Connection

    connection, own = personal
    peer, stranger = [Agent(title_id=agent.title_id, first_name=name, last_name="Synthetic",
        code=f"calendar-scope-{uuid4().hex}") for name in ("Peer", "Stranger")]
    team = TeamModel(name="Synthetic calendar team")
    db.add_all([peer, stranger, team])
    await db.flush()
    db.add_all([AgentTeam(agent_id=owner.id, team_id=team.id) for owner in (agent, peer)])
    await db.commit()

    async def personal_feed(owner: Agent) -> CalendarFeedRead:
        await sync_integrated_service_connections(owner.id)
        target = (await db.scalars(select(Connection).where(
            Connection.service_id == connection.service_id, Connection.agent_id == owner.id))).one()
        return (await service.list_feeds(connection_id=target.id))[0]

    peer_feed, stranger_feed = await personal_feed(peer), await personal_feed(stranger)
    peer_provider = Connection(service_id=calendar_connection.service_id, agent_id=peer.id, active=True)
    db.add(peer_provider)
    await db.flush()
    own_external = CalendarFeed(connection_id=calendar_connection.id, label="Synthetic own subscription",
        source_kind="ical", initialized=True, last_synced_at=datetime.now(timezone.utc))
    peer_external = CalendarFeed(connection_id=peer_provider.id, label="Synthetic peer subscription",
        source_kind="ical", initialized=True, last_synced_at=datetime.now(timezone.utc))
    db.add_all([own_external, peer_external])
    await db.commit()
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    end = start + timedelta(hours=1)
    window = {"start": start.isoformat(), "end": end.isoformat()}
    event_data = {**window, "summary": "Synthetic appointment"}
    for name in ("calendar_create_event", "calendar_update_event", "calendar_delete_event", "calendar_action_set"):
        await set_connection_function_state(connection.id, name, "enabled")

    catalogue = await agent_permission_catalog(agent.id, connection_id=connection.id)
    options = catalogue.connections[0].management_scope
    assert options is not None and options.value == "personal"
    assert {option.value for option in options.options} == {"personal", "team", "all"}
    server = await build_agent_mcp(agent.id)

    def values(result):
        return json.loads(result.content[0].text) if result.content else []

    async with Client(server) as client:
        async def visible_calendars(**arguments) -> set[int]:
            result = await client.call_tool("calendar_list", arguments)
            return {item["id"] for item in values(result) if item["id"] is not None}

        assert await visible_calendars() == {own.id}
        assert await visible_calendars(connection_id=calendar_connection.id) == {own_external.id}
        assert await read_calendar_resource(peer_feed.id, agent.id) is None
        assert (await client.call_tool("calendar_create_event", {**event_data, "calendar_id": peer_feed.id},
            raise_on_error=False)).is_error

        await set_management_scope(connection.id, "team", authorized=True)
        assert await visible_calendars() == {own.id, peer_feed.id, peer_external.id}
        assert {row["id"] for row in await list_calendar_resources(agent.id, "", 0, 10)} == {
            own.id, own_external.id, peer_feed.id, peer_external.id}
        created = values(await client.call_tool("calendar_create_event", {**event_data,
            "calendar_id": peer_feed.id, "reminder_minutes_before": 30}))
        target = {"calendar_id": peer_feed.id, "uid": created["uid"]}
        detail = values(await client.call_tool("calendar_event_get", target))
        assert detail["summary"] == event_data["summary"]
        trigger = (await db.scalars(select(CalendarTrigger).where(CalendarTrigger.calendar_id == peer_feed.id))).one()
        assert json.loads(decrypt(trigger.dispatch_encrypted))["agent_id"] == peer.id
        await client.call_tool("calendar_action_set", {**target, "instructions": "Synthetic reminder"})
        assert values(await client.call_tool("calendar_actions", target))[0]["instructions"] == "Synthetic reminder"

        page = values(await client.call_tool("calendar_events", {**window, "include_memory": False}))
        assert [item["calendar_id"] for item in page["items"]] == [peer_feed.id]
        availability = values(await client.call_tool("calendar_is_available", {**window, "calendar_ids": [peer_feed.id]}))
        assert availability["available"] is False
        assert not values(await client.call_tool("calendar_find_free_slots", {**window,
            "calendar_ids": [peer_feed.id], "duration_minutes": 30, "include_weekends": True}))
        assert (await client.call_tool("calendar_create_event", {**event_data, "calendar_id": stranger_feed.id},
            raise_on_error=False)).is_error
        await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == peer.id))
        await db.commit()
        assert await visible_calendars() == {own.id}
        assert (await client.call_tool("calendar_event_get", target, raise_on_error=False)).is_error

        await set_management_scope(connection.id, "all", authorized=True)
        assert await visible_calendars() == {own.id, peer_feed.id, peer_external.id, stranger_feed.id}
        await client.call_tool("calendar_create_event", {**event_data, "calendar_id": stranger_feed.id})
        assert (await client.call_tool("calendar_create_event", {**event_data, "calendar_id": peer_external.id},
            raise_on_error=False)).is_error
        assert (await client.call_tool("calendar_event_get", {**target, "connection_id": calendar_connection.id},
            raise_on_error=False)).is_error
        await set_connection_function_state(connection.id, "calendar_update_event", "disabled")
        assert (await client.call_tool("calendar_update_event", {**target, "expected_revision": detail["revision"],
            "summary": "Forbidden update"}, raise_on_error=False)).is_error
        await set_connection_function_state(connection.id, "calendar_update_event", "enabled")
        updated = values(await client.call_tool("calendar_update_event", {**target,
            "expected_revision": detail["revision"], "summary": "Synthetic updated appointment"}))
        await client.call_tool("calendar_delete_event", {**target, "expected_revision": updated["revision"]})

        await set_management_scope(connection.id, None, authorized=True)
        assert await visible_calendars() == {own.id}
        assert await read_calendar_resource(peer_feed.id, agent.id) is None
        assert (await client.call_tool("calendar_event_get", target, raise_on_error=False)).is_error
        page = values(await client.call_tool("calendar_events", {**window, "calendar_ids": [stranger_feed.id],
            "include_memory": False}))
        assert page["items"] == [] and not page["complete"]
        await client.call_tool("calendar_create_event", {**event_data, "calendar_id": own.id})
