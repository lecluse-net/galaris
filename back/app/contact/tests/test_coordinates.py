from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.models import Agent, Title
from app.contact import service
from app.contact.countries import country_from_localization
from app.contact.schemas import ContactCreate, ContactUpdate
from app.memory import (
    ContactCoordinates,
    MessengerContactObservation,
    get_messenger_contact,
    list_messenger_contacts,
    observe_messenger_contact,
)
from app.memory.models import MemoryItem
from app.memory.tests.conftest import memory_storage as memory_storage
from core.params import runtime_settings


@pytest.mark.parametrize("location,expected", [
    ("Lyon, France", "FR"), ("France", "FR"), ("  fr  ", "FR"),
    ("Genève, Suisse", "CH"), ("Berlin (Allemagne)", "DE"),
    ("Oxford, United Kingdom", "GB"), ("北京，中国", "CN"), ("中国", "CN"),
    ("", ""), ("Lyon", ""), ("Unknown place", ""),
])
def test_default_country_requires_an_explicit_country(location, expected):
    assert country_from_localization(location) == expected


@pytest.mark.asyncio
async def test_coordinates_persist_search_merge_and_remain_on_the_original_when_split(db, memory_storage, monkeypatch):
    title = Title(label="Synthetic contact coordinates", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, first_name="Synthetic", last_name="Coordinates", code=uuid4().hex)
    db.add(agent)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")

    created = await service.create_contact(ContactCreate.model_validate({
        "agent_id": agent.id, "display_name": "Synthetic postal contact",
        "coordinates": {"phone_numbers": [{"label": "Work", "number": "01 23 45 67 89"}],
                        "postal_addresses": [{"street": "12 rue Synthétique", "postal_code": "69000", "city": "Lyon"}]},
    }))
    assert created.identities == []
    assert created.coordinates.phone_numbers[0].country == "FR"
    assert created.coordinates.postal_addresses[0].country == "FR"
    reopened = await get_messenger_contact(created.memory_item_id)
    assert reopened.coordinates == created.coordinates
    for query in ("01 23 45 67 89", "Synthétique", "69000"):
        records, total = await list_messenger_contacts(owner_agent_id=agent.id, query=query)
        assert total == 1 and records[0].memory_item_id == created.memory_item_id
    assert await list_messenger_contacts(owner_agent_id=agent.id + 1000000, query="69000") == ((), 0)

    # Missing coordinate fields preserve existing data and never reapply new defaults.
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Genève, Suisse")
    renamed = await service.update_contact(contact_item_id=created.memory_item_id, data=ContactUpdate(display_name="Renamed"))
    assert renamed.coordinates == created.coordinates

    identity_id = await observe_messenger_contact(MessengerContactObservation(
        owner_agent_id=agent.id, messaging_id="matrix", user_id="@synthetic:example.test", display_name="Synthetic alias"))
    email = await service.create_contact(ContactCreate(agent_id=agent.id, display_name="Synthetic email", email="synthetic@example.org"))
    await service.merge_contacts(source_contact_item_id=email.memory_item_id, target_contact_item_id=identity_id)
    donor = await service.update_contact(contact_item_id=identity_id, data=ContactUpdate.model_validate({
        "display_name": "Alias", "coordinates": {"phone_numbers": [{"number": "+41 21 555 01 02", "country": "CH"}]},
    }))
    merged = await service.merge_contacts(source_contact_item_id=donor.memory_item_id, target_contact_item_id=created.memory_item_id)
    assert len(merged.contact.coordinates.phone_numbers) == 2
    assert merged.contact.coordinates.postal_addresses == created.coordinates.postal_addresses
    memory = await db.get(MemoryItem, created.memory_item_id)
    assert "01 23 45 67 89" in memory.memory_content
    assert "+41 21 555 01 02" in memory.memory_content

    # An incoming observation cannot discard explicitly maintained coordinates.
    assert await observe_messenger_contact(MessengerContactObservation(owner_agent_id=agent.id,
        messaging_id="matrix", user_id="@synthetic:example.test", display_name="Remote rename")) == created.memory_item_id
    assert (await get_messenger_contact(created.memory_item_id)).coordinates == merged.contact.coordinates

    split_id = next(identity.id for identity in merged.contact.identities if identity.namespace == "mail")
    split = await service.update_contact(contact_item_id=created.memory_item_id, data=ContactUpdate(
        display_name="Renamed", split_identity_ids=[split_id],
        expected_identity_ids=[identity.id for identity in merged.contact.identities]))
    assert split.coordinates == merged.contact.coordinates
    records, _ = await list_messenger_contacts(owner_agent_id=agent.id)
    detached = next(record for record in records if record.memory_item_id != created.memory_item_id)
    assert detached.coordinates == ContactCoordinates()
    cleared = await service.update_contact(contact_item_id=created.memory_item_id,
        data=ContactUpdate(display_name="Renamed", coordinates=ContactCoordinates()))
    assert cleared.coordinates == ContactCoordinates()
    assert await list_messenger_contacts(owner_agent_id=agent.id, query="69000") == ((), 0)


@pytest.mark.asyncio
async def test_explicit_country_and_explicit_empty_country_override_the_default(db, memory_storage, monkeypatch):
    title = Title(label="Synthetic explicit country", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, first_name="Synthetic", last_name="Country", code=uuid4().hex)
    db.add(agent)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    contact = await service.create_contact(ContactCreate.model_validate({
        "agent_id": agent.id, "display_name": "Explicit countries", "coordinates": {
            "phone_numbers": [{"number": "+44 20 7946 0000", "country": "GB"}, {"number": "123456", "country": ""}],
            "postal_addresses": [{"city": "Synthetic City"}],
        },
    }))
    assert [phone.country for phone in contact.coordinates.phone_numbers] == ["GB", ""]
    assert contact.coordinates.postal_addresses[0].country == "FR"


@pytest.mark.parametrize("coordinates", [
    {"phone_numbers": [{"number": " "}]}, {"phone_numbers": [{"number": "12"}]},
    {"phone_numbers": [{"number": "1" * 81}]}, {"postal_addresses": [{"country": "FR"}]},
    {"postal_addresses": [{"city": "Lyon", "unknown": "value"}]},
    {"phone_numbers": [{"number": "1234"}] * 51},
])
def test_invalid_coordinates_are_rejected(coordinates):
    with pytest.raises(ValidationError):
        ContactCoordinates.model_validate(coordinates)
