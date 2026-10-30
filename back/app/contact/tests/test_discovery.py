"""Synthetic end-to-end acquisition: real dispatcher, queue, decisions and persistence."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import register_contact_discovery
from app.agent.contact_discovery import ContactDiscoverySource
from app.agent.dispatcher import dispatch_conversation
from app.contact import discovery, discovery_inference as inference
from app.contact.directory import directory, fingerprint
from app.contact.discovery_contracts import ContactDiscoveryPlan, ContactOwnerEvidence
from app.contact.models import ContactDiscoveryJob
from app.contact.schemas import ContactCreate
from app.contact import service
from app.llm.decision_contracts import ChoiceAnswer, DecisionResult
from app.llm.structured_service import StructuredInferenceResult
from app.memory import ContactCoordinates, get_messenger_contact, list_messenger_contacts
from app.memory.models import MemoryItem
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from core.params import runtime_settings
from core.util import detect_contact_infos


@pytest.fixture(autouse=True)
def capture(monkeypatch, db):
    monkeypatch.setattr(runtime_settings, "CONTACT_CAPTURE_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    discovery.register_contact_runtime()
    yield
    register_contact_discovery(None)


def model_boundary(monkeypatch, *, name="Nina Fiction", status="identified", choose=None, platform=None, confidence=None):
    async def owner(**kwargs):
        prompt = json.loads(kwargs["prompt"])
        assert prompt["coordinate"]["value"] in json.dumps(prompt["conversation"], ensure_ascii=False)
        return StructuredInferenceResult(output=ContactOwnerEvidence(status=status, display_name=name,
            evidence_quotes=[name] if status == "identified" else [], messaging_platform=platform), cost=0.1, messages=[])

    async def decision(**kwargs):
        prompt = json.loads(kwargs["prompt"])
        assert prompt["requires_messaging_platform"] == (prompt["observation"]["coordinate"]["type"] == "instant_messaging")
        criteria = kwargs["questions"]["owner"].criteria
        value = choose(criteria) if choose is not None else (
            "ignore" if status == "ignore" else "unresolved" if status == "unresolved" else "create")
        return StructuredInferenceResult(output=DecisionResult(model="synthetic-decision", answers={
            "owner": ChoiceAnswer(choice=value, confidence=confidence)}), cost=0.2, messages=[])

    writer, decider = AsyncMock(side_effect=owner), AsyncMock(side_effect=decision)
    monkeypatch.setattr(inference.llm_service, "get_decision_models_for_agent_id",
        AsyncMock(return_value=(SimpleNamespace(id=1), SimpleNamespace(id=2), False)))
    monkeypatch.setattr(inference, "run_structured", writer)
    monkeypatch.setattr(inference, "run_profile_decision", decider)
    return writer, decider


async def deliver(agent_id, current, history=(), *, ai=False, round_id=None):
    messages = [{"text": text, "sender_display_name": "Synthetic correspondent"} for text in history]
    messages.append({"text": current, "sender_display_name": "Synthetic forwarder",
                     "sender_agent_id": 999 if ai else None})
    # Human path is deterministic. AI paths in the separate gate test use an END guard.
    return await dispatch_conversation(round_id=round_id or uuid4(), run_id=uuid4(), agent_id=agent_id,
        language="fr", objective=current, messages=messages, sender_is_ai=ai)


@pytest.mark.asyncio
async def test_contextual_phone_creates_owner_then_enriches_it_and_replays_without_llm(db, agents, memory_storage, monkeypatch):
    agent, _ = agents
    writer, decider = model_boundary(monkeypatch)
    source = uuid4()
    await deliver(agent.id, "C’est le 07 06 05 04 03.", ["As-tu le téléphone de Nina Fiction ?"], round_id=source)
    await deliver(agent.id, "C’est le 07 06 05 04 03.", ["As-tu le téléphone de Nina Fiction ?"], round_id=source)
    assert len((await db.scalars(select(ContactDiscoveryJob))).all()) == 1
    assert await discovery.process_contact_discovery() == 1
    contacts = await directory(agent.id)
    assert len(contacts) == 1 and contacts[0].display_name == "Nina Fiction"
    contact_id = contacts[0].memory_item_id
    assert contacts[0].coordinates.phone_numbers[0].number == "+33706050403"
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert (job.status, job.contact_item_id, job.cost) == ("success", contact_id, pytest.approx(0.3))

    model_boundary(monkeypatch, choose=lambda criteria: str(contact_id))
    await deliver(agent.id, "Le mail de Nina Fiction est nina@example.org.")
    assert await discovery.process_contact_discovery() == 1
    saved = await get_messenger_contact(contact_id)
    assert saved.coordinates.phone_numbers == contacts[0].coordinates.phone_numbers
    assert [(item.namespace, item.external_id) for item in saved.identities] == [("mail", "nina@example.org")]
    assert len(await directory(agent.id)) == 1

    writer = AsyncMock(side_effect=AssertionError("Known info must not invoke any model"))
    monkeypatch.setattr(inference, "run_structured", writer)
    monkeypatch.setattr(inference, "run_profile_decision", writer)
    revision = (await db.get(MemoryItem, contact_id)).revision
    await deliver(agent.id, "Nina Fiction : 07.06.05.04.03 ; nina@example.org.")
    assert await discovery.process_contact_discovery() == 1
    assert await discovery.process_contact_discovery() == 1
    writer.assert_not_awaited()
    assert (await db.get(MemoryItem, contact_id)).revision == revision
    db.expire_all()
    reopened = await get_messenger_contact(contact_id)
    assert reopened.coordinates.phone_numbers[0].number == "+33706050403"
    assert reopened.identities[0].external_id == "nina@example.org"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,value,platform", [
    ("email", "nina@example.org", None),
    ("postal_address", "12 rue des Fictions, 69003 Lyon", None),
    ("instant_messaging", "Telegram: @synthetic_nina", "telegram"),
    ("instant_messaging", "Matrix: @synthetic:example.org", "matrix"),
    ("instant_messaging", "WhatsApp: +33612345678", "whatsapp"),
])
async def test_each_coordinate_kind_is_recorded_without_creating_an_account(db, agents, memory_storage, monkeypatch, kind, value, platform):
    agent, _ = agents
    model_boundary(monkeypatch, platform=platform)
    result = await deliver(agent.id, f"Les coordonnées de Nina Fiction : {value}")
    assert [item.type for item in result.contact_infos] == [kind]
    assert await discovery.process_contact_discovery() == 1
    contact, = await directory(agent.id)
    if kind == "postal_address":
        assert contact.coordinates.postal_addresses[0].street == value
        assert contact.coordinates.postal_addresses[0].country == "FR"
    else:
        assert len(contact.identities) == 1
        assert contact.identities[0].namespace == (platform or "mail")
    assert contact.display_name == "Nina Fiction"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,choice", [("unresolved", "unresolved"), ("ignore", "ignore")])
async def test_ambiguous_or_illustrative_coordinates_remain_without_a_contact(db, agents, memory_storage, monkeypatch, status, choice):
    agent, _ = agents
    model_boundary(monkeypatch, status=status, choose=lambda criteria: choice)
    await deliver(agent.id, "Exemple : 07 06 05 04 03")
    await discovery.process_contact_discovery()
    assert await directory(agent.id) == []
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.status == ("ignored" if status == "ignore" else "unresolved")


@pytest.mark.asyncio
async def test_invented_owner_is_rejected_even_if_the_decider_says_create(db, agents, memory_storage, monkeypatch):
    model_boundary(monkeypatch, name="Invented Owner")
    await deliver(agents[0].id, "Son numéro est le 07 06 05 04 03.")
    await discovery.process_contact_discovery()
    assert await directory(agents[0].id) == []
    assert (await db.scalars(select(ContactDiscoveryJob.status))).one() == "unresolved"


@pytest.mark.asyncio
async def test_explicit_attribution_decision_is_not_replaced_by_an_arbitrary_confidence_cutoff(db, agents, memory_storage, monkeypatch):
    model_boundary(monkeypatch, confidence=0.86)
    await deliver(agents[0].id, "C’est le 07 06 05 04 03.", ["As-tu le numéro de Nina Fiction ?"])
    await discovery.process_contact_discovery()
    saved, = await directory(agents[0].id)
    assert saved.display_name == "Nina Fiction"
    assert saved.coordinates.phone_numbers[0].number == "+33706050403"


@pytest.mark.asyncio
async def test_checkpoint_recovery_reuses_decision_after_a_failure(db, agents, memory_storage, monkeypatch):
    writer, decider = model_boundary(monkeypatch)
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    original = discovery._apply
    monkeypatch.setattr(discovery, "_apply", AsyncMock(side_effect=RuntimeError("synthetic crash before apply")))
    await discovery.process_contact_discovery()
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.status == "retry" and job.prepared["action"] == "create"
    assert await directory(agents[0].id) == []
    job.available_at = datetime.now(timezone.utc)
    await db.commit()
    monkeypatch.setattr(discovery, "_apply", original)
    await discovery.process_contact_discovery()
    assert len(await directory(agents[0].id)) == 1
    writer.assert_awaited_once()
    decider.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_model_work_is_released_without_consuming_failure_budget(db, agents, memory_storage, monkeypatch):
    model_boundary(monkeypatch)
    monkeypatch.setattr(inference, "run_structured", AsyncMock(side_effect=asyncio.CancelledError))
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    with pytest.raises(asyncio.CancelledError):
        await discovery.process_contact_discovery()
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert (job.status, job.attempts, job.lease_token) == ("retry", 0, None)
    assert await directory(agents[0].id) == []


@pytest.mark.asyncio
async def test_known_coordinates_and_candidate_contacts_are_private_to_each_agent(db, agents, memory_storage, monkeypatch):
    first, second = agents
    foreign = await service.create_contact(ContactCreate(agent_id=second.id, display_name="Nina Fiction", email="nina@example.org"))
    writer, _ = model_boundary(monkeypatch)
    await deliver(first.id, "Nina Fiction : nina@example.org")
    await discovery.process_contact_discovery()
    own, = await directory(first.id)
    assert own.memory_item_id != foreign.memory_item_id
    writer.assert_awaited_once()
    assert (await directory(second.id))[0].memory_item_id == foreign.memory_item_id


@pytest.mark.asyncio
async def test_ai_end_route_still_enqueues_contact_work(db, agents, memory_storage, monkeypatch):
    from app.agent import dispatcher as module
    from app.agent.dispatcher import AI_EXCHANGE_MAX_DEPTH

    model_boundary(monkeypatch)
    text = "Le contact de Nina Fiction est nina@example.org."
    messages = [{"text": text, "sender": {"agent_id": agents[1].id}}] * AI_EXCHANGE_MAX_DEPTH
    result = await module.dispatch_conversation(round_id=uuid4(), run_id=uuid4(), agent_id=agents[0].id,
        language="fr", objective=text, messages=messages, sender_is_ai=True)
    assert result.decision.route == "END"
    await discovery.process_contact_discovery()
    assert (await directory(agents[0].id))[0].display_name == "Nina Fiction"


@pytest.mark.asyncio
async def test_configuration_disables_enqueue_and_processing(db, agents, monkeypatch):
    monkeypatch.setattr(runtime_settings, "CONTACT_CAPTURE_ENABLED", False)
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    assert (await db.scalars(select(ContactDiscoveryJob))).all() == []
    assert await discovery.process_contact_discovery() == 0


@pytest.mark.asyncio
async def test_ten_coordinates_in_one_message_are_recorded_on_the_same_person(db, agents, memory_storage, monkeypatch):
    from pathlib import Path
    cases = json.loads((Path(__file__).parents[2] / "agent/tests/fixtures/contact_detection_cases.json").read_text())
    message = next(case["text"] for case in cases if case["id"] == "ten-coordinates")
    writer, decider = model_boundary(monkeypatch,
        choose=lambda criteria: next((key for key in criteria if key not in {"ignore", "unresolved", "create"}), "create"))
    result = await deliver(agents[0].id, "Nina Fiction a communiqué ces coordonnées : " + message)
    assert len(result.contact_infos) == 10
    for _ in range(10):
        assert await discovery.process_contact_discovery() == 1
    assert await discovery.process_contact_discovery() == 0
    contact, = await directory(agents[0].id)
    assert len(contact.identities) == 2
    assert len(contact.coordinates.phone_numbers) == 3
    assert len(contact.coordinates.postal_addresses) == 5
    assert writer.await_count == decider.await_count == 10
    assert set((await db.scalars(select(ContactDiscoveryJob.status))).all()) == {"success"}


@pytest.mark.asyncio
async def test_human_edits_invalidate_a_prepared_enrichment_without_losing_coordinates(db, agents, memory_storage, monkeypatch):
    from app.memory import ContactPhoneNumber
    from app.contact.schemas import ContactUpdate
    created = await service.create_contact(ContactCreate(agent_id=agents[0].id,
        display_name="Nina Fiction", email="nina@example.org"))
    model_boundary(monkeypatch, choose=lambda criteria: str(created.memory_item_id))
    original = discovery._apply

    async def edit_then_apply(identity, token, plan):
        await service.update_contact(contact_item_id=created.memory_item_id, data=ContactUpdate(
            display_name="Nina Fiction", coordinates=ContactCoordinates(phone_numbers=[
                ContactPhoneNumber(number="+33123456789", country="FR")])))
        return await original(identity, token, plan)

    monkeypatch.setattr(discovery, "_apply", edit_then_apply)
    await deliver(agents[0].id, "Nina Fiction : 07 06 05 04 03")
    await discovery.process_contact_discovery()
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.status == "retry" and job.prepared is None
    saved = await get_messenger_contact(created.memory_item_id)
    assert [phone.number for phone in saved.coordinates.phone_numbers] == ["+33123456789"]
    monkeypatch.setattr(discovery, "_apply", original)
    await discovery.process_contact_discovery()
    saved = await get_messenger_contact(created.memory_item_id)
    assert {phone.number for phone in saved.coordinates.phone_numbers} == {"+33123456789", "+33706050403"}


@pytest.mark.asyncio
async def test_expired_leases_resume_and_exhausted_crash_work_becomes_error(db, agents, memory_storage, monkeypatch):
    model_boundary(monkeypatch)
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    job.status, job.attempts, job.lease_token = "running", 1, uuid4()
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await discovery.process_contact_discovery()
    assert (await db.get(ContactDiscoveryJob, job.id)).status == "success"
    await deliver(agents[0].id, "Autre : other@example.org")
    other = (await db.scalars(select(ContactDiscoveryJob).where(ContactDiscoveryJob.status == "pending"))).one()
    other.status, other.attempts, other.lease_token = "running", 5, uuid4()
    other.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert await discovery.process_contact_discovery() == 0
    assert (await db.get(ContactDiscoveryJob, other.id)).status == "error"


@pytest.mark.asyncio
async def test_owner_checkpoint_survives_a_decision_provider_failure(db, agents, memory_storage, monkeypatch):
    writer, decider = model_boundary(monkeypatch)
    original = decider.side_effect
    decider.side_effect = RuntimeError("synthetic provider interruption")
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    await discovery.process_contact_discovery()
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.status == "retry" and job.prepared["stage"] == "owner"
    assert job.cost == pytest.approx(0.1)
    decider.side_effect = original
    job.available_at = datetime.now(timezone.utc)
    await db.commit()
    await discovery.process_contact_discovery()
    assert len(await directory(agents[0].id)) == 1
    writer.assert_awaited_once()
    assert (await db.get(ContactDiscoveryJob, job.id)).cost == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_forgetting_a_contact_cancels_pending_old_observations(db, agents, memory_storage, monkeypatch):
    created = await service.create_contact(ContactCreate(agent_id=agents[0].id, display_name="Nina Fiction", email="nina@example.org"))
    model_boundary(monkeypatch)
    await deliver(agents[0].id, "Nina Fiction : nina@example.org")
    await service.forget_contact(contact_item_id=created.memory_item_id)
    assert await discovery.process_contact_discovery() == 0
    assert await directory(agents[0].id) == []
    assert (await db.scalars(select(ContactDiscoveryJob.status))).one() == "ignored"


@pytest.mark.asyncio
async def test_a_manually_entered_structured_address_is_recognized_without_llm(db, agents, memory_storage, monkeypatch):
    from app.memory import ContactPostalAddress
    await service.create_contact(ContactCreate(agent_id=agents[0].id, display_name="Nina Fiction",
        coordinates=ContactCoordinates(postal_addresses=[ContactPostalAddress(
            street="12 rue des Fictions", postal_code="69003", city="Lyon", country="FR")])))
    model = AsyncMock(side_effect=AssertionError("Known structured address must bypass LLM"))
    monkeypatch.setattr(inference, "run_structured", model)
    monkeypatch.setattr(inference, "run_profile_decision", model)
    await deliver(agents[0].id, "Nina Fiction : 12 rue des Fictions, 69003 Lyon.")
    await discovery.process_contact_discovery()
    model.assert_not_awaited()
    assert (await db.scalars(select(ContactDiscoveryJob.status))).one() == "success"


@pytest.mark.asyncio
async def test_coalesced_current_messages_capture_all_details_and_exclude_old_history(db, agents):
    current = [{"text": "Nina Fiction : nina@example.org"}, {"text": "Son numéro : +33 7 06 05 04 03"}, {"text": "Merci !"}]
    result = await dispatch_conversation(round_id=uuid4(), run_id=uuid4(), agent_id=agents[0].id,
        language="fr", objective="Merci !", sender_is_ai=False,
        messages=[{"text": "Ancienne adresse old@example.net"}, *current], current_messages=current)
    assert [item.type for item in result.contact_infos] == ["email", "phone"]
    assert len((await db.scalars(select(ContactDiscoveryJob))).all()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("history,expected", [([], "unresolved"), (["Nina Fiction utilise Telegram."], "success")])
async def test_generic_handle_requires_a_supported_platform_before_writing(db, agents, memory_storage, monkeypatch, history, expected):
    model_boundary(monkeypatch, platform="telegram")
    await deliver(agents[0].id, "Nina Fiction, pseudo : @SYNTHETIC_NINA.", history)
    await discovery.process_contact_discovery()
    assert (await db.scalars(select(ContactDiscoveryJob.status))).one() == expected
    contacts = await directory(agents[0].id)
    if expected == "success":
        assert contacts[0].identities[0].namespace == "telegram"
        assert contacts[0].identities[0].external_id == "synthetic_nina"
    else:
        assert contacts == []
