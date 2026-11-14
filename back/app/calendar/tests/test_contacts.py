"""Event contact references remain private, local and durable across lifecycles."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent
from app.agent.task_port import task_port
from app.calendar import dispatch, ical, mcp, service, store
from app.calendar.models import CalendarEvent
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate
from app.contact import service as contacts
from app.contact.schemas import ContactCreate
from app.memory.tests.conftest import memory_storage as memory_storage
from app.task.models import Task
from app.tools import McpToolContext

NOW = datetime(2026, 12, 2, 10, tzinfo=timezone.utc)


async def contact(agent_id, name="Synthetic contact"):
    return await contacts.create_contact(ContactCreate(agent_id=agent_id, display_name=name,
        email=f"{uuid4().hex}@example.org"))


@pytest.mark.asyncio
async def test_agent_can_link_preserve_replace_and_remove_a_contact_with_history(db, agent, personal, memory_storage):
    _, feed = personal
    first, second = await contact(agent.id), await contact(agent.id, "Synthetic second")
    ctx = McpToolContext(agent_id=agent.id, runtime="internal")
    receipt = await mcp.calendar_create_event(ctx, feed.id, "Synthetic appointment", NOW.isoformat(),
        (NOW + timedelta(hours=1)).isoformat(), contact_id=first.memory_item_id)
    uid = receipt["uid"]
    assert receipt["contact_id"] == str(first.memory_item_id)
    detail = await service.event_detail(feed.id, uid)
    assert detail.contact_id == first.memory_item_id
    assert str(first.memory_item_id) not in detail.ical and "Synthetic contact" not in detail.ical
    await mcp.calendar_update_event(ctx, feed.id, uid, 1, location="Synthetic room")
    assert (await service.event_detail(feed.id, uid)).contact_id == first.memory_item_id
    await mcp.calendar_update_event(ctx, feed.id, uid, 2, contact_id=second.memory_item_id)
    assert (await service.event_detail(feed.id, uid)).contact_id == second.memory_item_id
    await mcp.calendar_update_event(ctx, feed.id, uid, 3, clear_contact=True)
    assert (await service.event_detail(feed.id, uid)).contact_id is None
    await service.update_calendar_event(feed.id, agent.id, uid, CalendarEventUpdate(expected_revision=4, contact_id=first.memory_item_id))
    await service.update_calendar_event(feed.id, agent.id, uid, CalendarEventUpdate(expected_revision=5, contact_id=None))
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).items[0].contact_id is None
    history = await service.event_history(feed.id, uid)
    assert [row.contact_id for row in history] == [None, first.memory_item_id, None, second.memory_item_id, first.memory_item_id, first.memory_item_id]


@pytest.mark.asyncio
async def test_contacts_must_exist_and_belong_to_calendar_agent(db, agent, personal, memory_storage):
    _, feed = personal
    other = Agent(title_id=agent.title_id, first_name="Synthetic", last_name="Other", code=f"foreign-{uuid4().hex[:12]}")
    db.add(other)
    await db.flush()
    foreign = await contact(other.id)
    for identifier in (foreign.memory_item_id, uuid4()):
        with pytest.raises(ValueError, match="Contact not found"):
            await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic", start=NOW,
                end=NOW + timedelta(hours=1), contact_id=identifier))
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic", start=NOW, end=NOW + timedelta(hours=1)))
    with pytest.raises(ValueError, match="Contact not found"):
        await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1, contact_id=foreign.memory_item_id))
    assert (await service.event_detail(feed.id, created.uid)).contact_id is None


@pytest.mark.asyncio
async def test_contact_survives_provider_refresh_and_follows_merge_and_forgetting(db, agent, personal, memory_storage):
    _, feed = personal
    first, second = await contact(agent.id), await contact(agent.id, "Synthetic merged")
    receipt = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic", start=NOW,
        end=NOW + timedelta(hours=1), contact_id=first.memory_item_id))
    event = await db.get(CalendarEvent, receipt.event_id)
    payload = ical.update_event(await store.resource_content(event), receipt.uid, CalendarEventUpdate(expected_revision=1, summary="Synthetic remote edit"))
    resource = ical.split_resources(payload, feed.timezone)[0]
    await store.save_resource(feed, resource, local=False, existing=event, known=True)
    await db.commit()
    assert (await service.event_detail(feed.id, receipt.uid)).contact_id == first.memory_item_id
    merged = await contacts.merge_contacts(source_contact_item_id=first.memory_item_id, target_contact_item_id=second.memory_item_id)
    assert merged.rewired["calendar_events"] == 1
    assert (await service.event_detail(feed.id, receipt.uid)).contact_id == second.memory_item_id
    assert all(row.contact_id == second.memory_item_id for row in await service.event_history(feed.id, receipt.uid))
    forgotten = await contacts.forget_contact(contact_item_id=second.memory_item_id)
    assert forgotten.cleared["calendar_events"] == 1
    assert (await service.event_detail(feed.id, receipt.uid)).contact_id is None
    assert all(row.contact_id is None for row in await service.event_history(feed.id, receipt.uid))


@pytest.mark.asyncio
async def test_event_contact_is_carried_to_due_task_without_becoming_requester_scope(db, agent, personal, memory_storage, monkeypatch):
    _, feed = personal
    linked = await contact(agent.id)
    monkeypatch.setattr(task_port, "schedule", lambda _: None)
    await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic follow-up", start=NOW,
        end=NOW + timedelta(hours=1), contact_id=linked.memory_item_id))
    assert await dispatch.dispatch_due(now=NOW) == 1
    task = (await db.scalars(select(Task))).one()
    assert task.data["contact_id"] == str(linked.memory_item_id)
    assert task.data["contact_uri"] == f"galaris://contact/{linked.memory_item_id}"
    assert task.contact_memory_item_id is None


@pytest.mark.asyncio
async def test_split_series_inherits_contact_and_occurrence_edits_cannot_change_the_series_link(db, agent, personal, memory_storage):
    _, feed = personal
    linked = await contact(agent.id)
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic recurring",
        start=NOW, end=NOW + timedelta(hours=1), rrule="FREQ=DAILY;COUNT=5", contact_id=linked.memory_item_id))
    occurrences = (await service.event_window(agent.id, NOW, NOW + timedelta(days=6))).items
    with pytest.raises(ValueError, match="whole event"):
        await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1,
            scope="occurrence", recurrence_key=occurrences[2].recurrence_key, clear_contact=True))
    following = await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1,
        scope="following", recurrence_key=occurrences[2].recurrence_key, rrule="FREQ=WEEKLY;COUNT=2"))
    assert following.event_id != created.event_id
    assert (await service.event_detail(feed.id, created.uid)).contact_id == linked.memory_item_id
    assert (await service.event_detail(feed.id, following.uid)).contact_id == linked.memory_item_id
