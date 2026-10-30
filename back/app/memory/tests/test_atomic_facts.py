"""Typed facts retain atomic values and real links across retries and corrections."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.memory import AtomicMemoryFact, MessengerContactObservation, observe_messenger_contact
from app.memory import acquisition_service, service
from app.memory.models import MemoryItem, MemoryLink
from app.memory.schemas import MemoryAcquisitionCreate
from app.memory.schemas import MemoryItemUpdate, MemoryPayload


@pytest.mark.parametrize("value", [["weekly", "monthly"], {"first": 1, "second": 2}, "<p>narrated</p>", "First paragraph\nSecond paragraph"])
def test_atom_rejects_multiple_values_and_editorial_prose(value):
    with pytest.raises(ValidationError):
        AtomicMemoryFact(predicate="wants", value=value)


@pytest.mark.asyncio
async def test_same_atom_links_new_evidence_without_model_calls_or_duplicates_after_a_contact_rename(db, agents, memory_storage, monkeypatch):
    from app.memory import update_messenger_contact
    owner, _ = agents
    contact = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id="matrix", user_id="@synthetic-fact:example.org", display_name="Nina Fiction"))
    fact = AtomicMemoryFact(subject_ref=f"memory://{contact}", predicate="Preferred language", value="fr")
    first = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
        fact=fact, source_kind="manual", source_ref="synthetic:first-fact"))
    await update_messenger_contact(contact_item_id=contact, display_name="Nina Renamed Fiction")
    unavailable = AsyncMock(side_effect=AssertionError("Identical atoms must not require semantic matching"))
    monkeypatch.setattr(acquisition_service, "find_similar_memory_candidates", unavailable)
    second = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
        fact=fact, source_kind="manual", source_ref="synthetic:second-fact"))
    assert first.memory_id == second.memory_id
    assert second.status == "merged"
    assert set(await service.source_refs(first.memory_id)) == {"synthetic:first-fact", "synthetic:second-fact"}
    assert await db.scalar(select(MemoryLink.id).where(MemoryLink.source_item_id == first.memory_id,
        MemoryLink.target_item_id == contact, MemoryLink.relation_type == "fact_subject")) is not None
    unavailable.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_property_creates_another_atom_without_appending_to_the_old_fact(db, agents, memory_storage):
    owner, _ = agents
    first = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
        fact=AtomicMemoryFact(predicate="preferred_language", value="fr"), source_ref="synthetic:first-property"))
    original = await service.item_record(first.memory_id)
    old_content, old_revision = original.content, original.revision
    second = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
        action="update", target_item_id=first.memory_id,
        fact=AtomicMemoryFact(predicate="report_frequency", value="weekly"), source_ref="synthetic:second-property"))
    assert first.memory_id != second.memory_id
    reopened = await service.item_record(first.memory_id)
    assert reopened.content == old_content and reopened.revision == old_revision
    assert len((await db.scalars(select(MemoryItem.id).where(MemoryItem.owner_agent_id == owner.id,
        MemoryItem.source_managed.is_(False)))).all()) == 2
    with pytest.raises(service.MemoryConflictError, match="Atomic facts"):
        await service.update_item(first.memory_id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Rewritten paragraph.</p>")),
            actor_agent_id=owner.id)


@pytest.mark.asyncio
async def test_homonymous_contacts_and_different_values_are_not_merged_as_identical_atoms(db, agents, memory_storage, monkeypatch):
    from app.memory import maintenance
    owner, _ = agents
    contacts = [await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id="matrix", user_id=f"@synthetic-{index}:example.org", display_name="Nina Fiction")) for index in range(2)]
    results = []
    for contact, value in [(contacts[0], "weekly"), (contacts[1], "weekly"), (contacts[0], "monthly")]:
        results.append(await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
            fact=AtomicMemoryFact(subject_ref=f"memory://{contact}", predicate="report_frequency", value=value),
            source_ref=f"synthetic:{contact}:{value}")))
    assert len({result.memory_id for result in results}) == 3
    items = [await service.item_record(result.memory_id) for result in results]
    primary = min(items, key=lambda item: str(item.id))
    async def similar(*_args, **_kwargs):
        return [(item, 1.0) for item in items if item.id != primary.id]
    monkeypatch.setattr(maintenance, "_indexed_candidates", similar)
    from core.params import runtime_settings
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    assert await maintenance.detect_for_item(primary.id, manual=True) == []


@pytest.mark.asyncio
async def test_atom_cannot_reference_another_agents_contact(db, agents, memory_storage):
    owner, peer = agents
    foreign = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=peer.id,
        messaging_id="matrix", user_id="@synthetic-foreign:example.org", display_name="Other Fiction"))
    with pytest.raises(service.MemoryPermissionError):
        await acquisition_service.acquire_memory(MemoryAcquisitionCreate(agent_id=owner.id,
            fact=AtomicMemoryFact(subject_ref=f"memory://{foreign}", predicate="wants", value="weekly_reports"),
            source_ref="synthetic:denied-contact"))


@pytest.mark.asyncio
async def test_fact_about_email_only_contact_keeps_the_link_without_copying_coordinates(db, agents, memory_storage):
    from app.memory import create_address_book_contact
    owner, _ = agents
    contact = await create_address_book_contact(owner_agent_id=owner.id,
        display_name="synthetic-fact@example.org", email="synthetic-fact@example.org")
    result = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
        agent_id=owner.id,
        fact=AtomicMemoryFact(subject_ref=f"memory://{contact.memory_item_id}",
            predicate="preferred_language", value="fr"),
        source_ref="synthetic:email-only-subject",
    ))
    assert result.status == "stored"
    stored = await service.item_record(result.memory_id)
    assert "synthetic-fact@example.org" not in stored.content
    assert stored.metadata_["atomic_fact"]["subject_ref"] == f"memory://{contact.memory_item_id}"
    assert await db.scalar(select(MemoryLink.id).where(
        MemoryLink.source_item_id == stored.id,
        MemoryLink.target_item_id == contact.memory_item_id,
        MemoryLink.relation_type == "fact_subject",
    )) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [(False, "false"), (1, "1")])
async def test_different_typed_values_cannot_deduplicate_through_identical_html(db, agents, memory_storage, values):
    owner, _ = agents
    results = [await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
        agent_id=owner.id, fact=AtomicMemoryFact(predicate="synthetic_value", value=value),
        source_ref=f"synthetic:typed-identity:{index}",
    )) for index, value in enumerate(values)]
    assert results[0].memory_id != results[1].memory_id
    items = [await service.item_record(result.memory_id) for result in results]
    assert items[0].content == items[1].content
    for item, value in zip(items, values, strict=True):
        assert type(item.metadata_["atomic_fact"]["value"]) is type(value)
