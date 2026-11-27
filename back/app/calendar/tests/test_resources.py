"""Calendar identities survive edits and remain private, credential-free resources."""
import json

import pytest

from app.calendar import service
from app.calendar.resources import search_calendar_resources
from app.calendar.schemas import CalendarFeedUpdate
from app.file_share import ResourceContext, resource_info, resource_list, resource_read, resource_search
from app.file_share.resource_uri import ResourceUriError
from app.messenger.link_preview import preview_reference


@pytest.mark.asyncio
async def test_calendar_reference_resolves_lists_searches_and_previews_without_thumbnail(db, agent, personal):
    _, feed = personal
    uri = f"galaris://calendar/{feed.id}"
    ctx = ResourceContext(agent_id=agent.id, runtime="internal")
    assert service.serialize_feed(feed, agent.id).resource_uri == uri
    await service.update_feed(feed.id, CalendarFeedUpdate(label="Synthetic renamed calendar"))
    info = await resource_info(ctx, uri)
    assert info.uri == uri and info.metadata["label"] == "Synthetic renamed calendar"
    assert info.media_type == "application/vnd.galaris.calendar+json"
    payload = json.loads((await resource_read(ctx, uri)).content)
    assert payload["agent_id"] == agent.id and payload["uri"] == uri
    assert set(payload) == {"id", "uri", "agent_id", "label", "owner_label", "source_kind", "timezone", "active", "writable", "created_at", "updated_at"} - {"owner_label"}
    assert [entry.uri for entry in (await resource_list(ctx, "galaris://calendar/")).entries] == [uri]
    assert [hit.resource.uri for hit in (await resource_search(ctx, "galaris://calendar/", "renamed")).hits] == [uri]
    preview = await preview_reference(uri, agent_id=agent.id)
    assert preview is not None and preview.kind == "calendar" and preview.title == "Synthetic renamed calendar"
    assert not preview.image_available and not preview.download_available
    assert await search_calendar_resources([], "", 0, 50) == []
    assert [row["uri"] for row in await search_calendar_resources([agent.id], "renamed", 0, 50)] == [uri]


@pytest.mark.asyncio
async def test_calendar_references_do_not_grant_access_to_other_agents_or_inactive_connections(db, agent, personal):
    connection, feed = personal
    uri = f"galaris://calendar/{feed.id}"
    foreign = ResourceContext(agent_id=agent.id + 1000, runtime="internal")
    with pytest.raises(FileNotFoundError):
        await resource_info(foreign, uri)
    assert not (await resource_list(foreign, "galaris://calendar/")).entries
    connection.active = False
    await db.commit()
    with pytest.raises(FileNotFoundError):
        await resource_read(ResourceContext(agent_id=agent.id, runtime="internal"), uri)


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["0", "-1", "not-a-calendar", "1/events", "1/"])
async def test_calendar_uri_rejects_invalid_identity(identifier):
    with pytest.raises(ResourceUriError):
        await resource_info(ResourceContext(agent_id=1, runtime="internal"), f"galaris://calendar/{identifier}")


@pytest.mark.asyncio
@pytest.mark.parametrize("privilege", ["CALENDAR_ACCESS", "CALENDAR_EDIT", "CONNECTION_ACCESS"])
async def test_calendar_resource_http_reads_require_calendar_privilege_and_owner_scope(client, privilege):
    from core.database import get_db_session
    from core.authorize.tests.test_guard_policy_parameters import actor
    from core.authorize.tests.test_domain_authorization import owned_agent
    from app.connection import Connection
    from app.calendar.models import CalendarFeed
    from tests.protocol_tools import protocol_tool
    headers, user_id = await actor([privilege])
    own = await owned_agent(user_id)
    _, other_user = await actor([])
    other = await owned_agent(other_user)
    async with get_db_session() as db:
        tool = await protocol_tool(db, "calendar")
        connections = [Connection(agent_id=identity, service_id=tool.id, active=True) for identity in (own, other)]
        db.add_all(connections)
        await db.flush()
        feeds = [CalendarFeed(connection_id=connection.id, label="Synthetic resource calendar", source_kind="caldav") for connection in connections]
        db.add_all(feeds)
        await db.flush()
        own_feed, foreign_feed = [feed.id for feed in feeds]
    detail = await client.get(f"/api/calendars/{own_feed}", headers=headers)
    listing = await client.get("/api/calendars/resources", headers=headers, params={"query": "Synthetic resource", "limit": 1})
    if privilege == "CONNECTION_ACCESS":
        assert detail.status_code == listing.status_code == 403
        return
    assert detail.status_code == listing.status_code == 200
    assert detail.json()["resource_uri"] == f"galaris://calendar/{own_feed}"
    assert [row["id"] for row in listing.json()] == [own_feed]
    assert (await client.get(f"/api/calendars/{foreign_feed}", headers=headers)).status_code == 404
    assert (await client.get("/api/calendars/resources", headers=headers, params={"limit": 501})).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("can_launch", [False, True])
async def test_configuring_an_event_process_requires_both_calendar_and_process_rights(client, can_launch):
    from core.database import get_db_session
    from core.authorize.tests.test_guard_policy_parameters import actor
    from core.authorize.tests.test_domain_authorization import owned_agent
    from app.connection import Connection
    from app.calendar.models import CalendarFeed
    from app.process.bpmn import Flow, Node, Workflow
    from app.process.native_definitions import create
    from tests.protocol_tools import protocol_tool

    headers, user_id = await actor(["CALENDAR_EDIT", "PROCESS_LAUNCH"] if can_launch else ["CALENDAR_EDIT"])
    owner = await owned_agent(user_id)
    async with get_db_session() as db:
        calendar_tool = await protocol_tool(db, "calendar")
        connection = Connection(agent_id=owner, service_id=calendar_tool.id, active=True)
        db.add(connection)
        await db.flush()
        feed = CalendarFeed(connection_id=connection.id, label="Synthetic writable calendar",
            writable=True, source_kind="internal")
        db.add(feed)
        await db.flush()
        process = await create(actor_agent_id=owner, title="Synthetic workflow", graph=Workflow(
            nodes=[Node(id="start", kind="start"), Node(id="end", kind="end")],
            flows=[Flow(id="flow", source="start", target="end")]))
        feed_id, process_id = feed.id, process.id

    base = f"/api/calendars/{feed_id}"
    options = await client.get(f"{base}/process-options", headers=headers)
    assert options.status_code == (200 if can_launch else 403), options.text
    if can_launch:
        assert options.json() == [{"id": process_id, "label": "Synthetic workflow"}]
    data = {"summary": "Synthetic event", "start": "2026-12-01T09:00:00Z", "end": "2026-12-01T10:00:00Z"}
    created = await client.post(f"{base}/events", headers=headers, json={**data, "process_definition_id": process_id})
    assert created.status_code == (201 if can_launch else 403), created.text
    if not can_launch:
        created = await client.post(f"{base}/events", headers=headers, json=data)
        assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    detail = await client.get(f"{base}/events/{event_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["process_definition_id"] == (process_id if can_launch else None)
