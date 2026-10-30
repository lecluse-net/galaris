"""Canonical contact fusion, decision refusal and stale/replayed Dream work."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.contact import service
from app.contact.directory import directory
from app.contact.discovery_contracts import ContactMergeCandidate
from app.contact.models import ContactDiscoveryJob
from app.contact.schemas import ContactCreate, ContactUpdate
from app.dream import scheduler
from app.dream.mechanisms import contact_reconciliation as module
from app.dream.models import DreamReceipt
from app.dream.registry import register_mechanism, reset_registry
from app.llm.decision_contracts import ChoiceAnswer, DecisionResult
from app.llm.structured_service import StructuredInferenceResult
from app.memory import ContactCoordinates, ContactPhoneNumber, get_messenger_contact
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from core.params import runtime_settings


def decider(monkeypatch, choice="merge", confidence=0.99):
    async def infer(**kwargs):
        assert "same_person" in kwargs["questions"]
        assert "name alone" in kwargs["questions"]["same_person"].instructions
        return StructuredInferenceResult(output=DecisionResult(model="synthetic-decision", answers={
            "same_person": ChoiceAnswer(choice=choice, confidence=confidence)}), cost=0.12, messages=[])
    call = AsyncMock(side_effect=infer)
    monkeypatch.setattr(module, "run_profile_decision", call)
    return call


@pytest.fixture
def dream(monkeypatch, db):
    monkeypatch.setattr(runtime_settings, "DREAM_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "CONTACT_CAPTURE_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 0.92)
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler, "has_active_task_work", AsyncMock(return_value=False))
    reset_registry()
    register_mechanism(module.contact_reconciliation_mechanism)
    yield
    reset_registry()


async def pair(agent_id):
    first = await service.create_contact(ContactCreate(agent_id=agent_id, display_name="Nina Fiction", email="nina@example.org"))
    second = await service.create_contact(ContactCreate(agent_id=agent_id, display_name="Nina Fiction",
        coordinates=ContactCoordinates(phone_numbers=[ContactPhoneNumber(number="+33706050403", country="FR")])))
    return first, second


@pytest.mark.asyncio
async def test_dream_merges_coordinates_once_and_rewires_discovery_provenance(db, agents, memory_storage, dream, monkeypatch):
    agent_id = agents[0].id
    first, second = await pair(agent_id)
    target, source = sorted((first, second), key=lambda item: (item.created_at, item.memory_item_id))
    from uuid import uuid4
    db.add(ContactDiscoveryJob(agent_id=agents[0].id, source_kind="conversation_round", source_ref=str(uuid4()),
        observation_key="a" * 64, coordinate={"type": "phone", "value": "+33706050403"},
        context={"current": "Nina Fiction confirme que ces deux fiches sont les siennes."},
        status="success", contact_item_id=source.memory_item_id))
    await db.commit()
    call = decider(monkeypatch)
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 0
    db.expire_all()
    contacts = await directory(agent_id)
    assert len(contacts) == 1
    assert contacts[0].memory_item_id == target.memory_item_id
    assert contacts[0].identities[0].external_id == "nina@example.org"
    assert contacts[0].coordinates.phone_numbers[0].number == "+33706050403"
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.contact_item_id == target.memory_item_id
    receipt = (await db.scalars(select(DreamReceipt).where(DreamReceipt.mechanism_key == "contact.reconcile"))).one()
    assert (receipt.status, receipt.result_count, receipt.cost) == ("success", 1, pytest.approx(0.12))
    assert await module.contact_reconciliation_mechanism.apply(None, receipt.prepared_payload) == 0
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("choice,confidence", [("separate", 0.99), ("unresolved", 0.7)])
async def test_homonyms_or_unresolved_identity_do_not_merge(db, agents, memory_storage, dream, monkeypatch, choice, confidence):
    await pair(agents[0].id)
    decider(monkeypatch, choice, confidence)
    assert await scheduler.run_cycle() == 1
    assert len(await directory(agents[0].id)) == 2
    assert await scheduler.run_cycle() == 0


@pytest.mark.asyncio
async def test_a_human_edit_after_the_decision_invalidates_the_merge(db, agents, memory_storage, dream, monkeypatch):
    first, second = await pair(agents[0].id)
    decider(monkeypatch)
    mechanism = module.contact_reconciliation_mechanism
    claim = await mechanism.claim_one()
    prepared = await mechanism.prepare(claim)
    await service.update_contact(contact_item_id=second.memory_item_id, data=ContactUpdate(display_name="Another Person"))
    assert await mechanism.apply(claim, prepared.payload) == 0
    assert await get_messenger_contact(first.memory_item_id) is not None
    assert await get_messenger_contact(second.memory_item_id) is not None


@pytest.mark.asyncio
async def test_similarity_threshold_and_agent_ownership_bound_candidates(db, agents, memory_storage, dream, monkeypatch):
    first = await service.create_contact(ContactCreate(agent_id=agents[0].id, display_name="Nina Fiction", email="nina@example.org"))
    await service.create_contact(ContactCreate(agent_id=agents[1].id, display_name="Nina Fiction", email="nina@example.org"))
    from app.contact.facade import apply_contact_merge, contact_merge_candidates
    assert await contact_merge_candidates() == []
    second = await service.create_contact(ContactCreate(agent_id=agents[0].id, display_name="Nina Fictions", email="other@example.org"))
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 1.0)
    assert await contact_merge_candidates() == []
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", 0.92)
    candidates = await contact_merge_candidates()
    assert len(candidates) == 1
    assert not await apply_contact_merge(candidates[0].model_copy(update={"agent_id": agents[1].id}))
    assert await get_messenger_contact(first.memory_item_id) is not None
    assert await get_messenger_contact(second.memory_item_id) is not None


@pytest.mark.asyncio
async def test_new_identity_evidence_reopens_a_previously_declined_pair(db, agents, memory_storage, dream, monkeypatch):
    from uuid import uuid4

    agent_id = agents[0].id
    first, second = await pair(agent_id)
    decider(monkeypatch, "separate")
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 0
    db.add(ContactDiscoveryJob(agent_id=agent_id, source_kind="conversation_round", source_ref=str(uuid4()),
        observation_key="b" * 64, coordinate={"type": "email", "value": "nina@example.org"},
        context={"current": "Nina Fiction confirme que les deux coordonnées lui appartiennent."},
        status="success", contact_item_id=first.memory_item_id))
    await db.commit()
    decider(monkeypatch, "merge")
    assert await scheduler.run_cycle() == 1
    assert len(await directory(agent_id)) == 1
    assert len((await db.scalars(select(DreamReceipt).where(DreamReceipt.mechanism_key == "contact.reconcile"))).all()) == 2
