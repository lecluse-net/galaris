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
        connections = [Connection(agent_id=identity, tool_id=tool.id, active=True) for identity in (own, other)]
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
