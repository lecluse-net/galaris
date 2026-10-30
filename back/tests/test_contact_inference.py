"""Actual profile resolution, SDK, native decision HTTP and durable contact writes."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.dispatcher import dispatch_conversation
from app.agent import register_contact_discovery
from app.contact import discovery
from app.contact.directory import directory
from app.contact.models import ContactDiscoveryJob
from app.llm.models import LLMCall, LLMInference
from app.llm import LLMCallPurpose
from core.params import runtime_settings
from tests.test_decision_inference import decisions, runtime  # noqa: F401
from tests.test_decision_workflows import profile_context, memory_extraction_storage  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["create", "unresolved", "ignore"])
async def test_contact_pipeline_uses_real_durable_text_and_decision_lifecycles(
    decisions, runtime, memory_extraction_storage, monkeypatch, selection,
):
    db, _request, native_calls, text_calls, decision_mode = decisions
    _, _text_model, _requests, text_mode = runtime
    task, _profile = await profile_context(decisions, runtime, fallback=False)
    agent_id = task.agent_id
    monkeypatch.setattr(runtime_settings, "CONTACT_CAPTURE_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    decision_mode["selections"] = {"owner": selection}
    text_mode.update(structured=False, concurrent=True, outputs=[json.dumps({
        "status": "identified", "display_name": "Nina Fiction", "evidence_quotes": ["Nina Fiction"],
    })])
    discovery.register_contact_runtime()
    try:
        result = await dispatch_conversation(round_id=uuid4(), run_id=uuid4(), agent_id=agent_id,
            language="fr", objective="C’est le 07 06 05 04 03.", sender_is_ai=False,
            messages=[{"text": "As-tu le téléphone de Nina Fiction ?"}, {"text": "C’est le 07 06 05 04 03."}])
        assert result.contact_infos and text_calls == native_calls == []
        assert await discovery.process_contact_discovery() == 1
    finally:
        register_contact_discovery(None)
    job = (await db.scalars(select(ContactDiscoveryJob))).one()
    assert job.status == {"create": "success", "unresolved": "unresolved", "ignore": "ignored"}[selection], job.last_error
    assert len(native_calls) == 1
    assert text_calls
    contacts = await directory(agent_id)
    if selection == "create":
        assert len(contacts) >= 1
        saved = next(item for item in contacts if item.memory_item_id == job.contact_item_id)
        assert saved.display_name == "Nina Fiction"
        assert saved.coordinates.phone_numbers[0].number == "+33706050403"
    else:
        assert not any(item.display_name == "Nina Fiction" for item in contacts)
    inferences = (await db.scalars(select(LLMInference).where(
        LLMInference.request["purpose"].as_string() == LLMCallPurpose.CONTACT_OWNER))).all()
    assert len(inferences) == 2
    assert all(item.status == "completed" for item in inferences)
    calls = (await db.scalars(select(LLMCall).where(LLMCall.purpose == LLMCallPurpose.CONTACT_OWNER))).all()
    assert len(calls) >= 2
