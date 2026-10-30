"""Synthetic coordinate detection and unchanged routing across Dispatcher paths."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import dispatcher as module
from app.agent.contracts import DispatchDecision, DispatchResult
from app.agent.dispatcher import Dispatcher
from core.params import runtime_settings
from core.util import detect_contact_infos
from core.util import normalize_contact_coordinate


CASES = json.loads((Path(__file__).parent / "fixtures/contact_detection_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_synthetic_contact_corpus(case):
    result = detect_contact_infos(case["text"], default_country=case["country"])
    assert [[item.type, item.value] for item in result] == case["expected"]
    for item in result:
        assert case["text"][item.start:item.end] == item.value
    assert all(left.end <= right.start for left, right in zip(result, result[1:]))


@pytest.mark.parametrize("separator", [" ", ".", "-", "\u00a0", "\u202f", ""])
def test_phone_formats_share_an_exact_lookup_key(separator):
    number = separator.join(("07", "06", "05", "04", "03"))
    result = detect_contact_infos(f"C’est le {number}.", default_country="FR")
    assert len(result) == 1
    assert result[0].type == "phone"
    assert result[0].normalized_value == "+33706050403"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    "Le mail est nina@example.org.",
    "<p>Le mail est <a href=\"mailto:other@example.net\">nina@example.org</a>.</p>",
    "<p>nina@example.org</p><script>const hidden = 'other@example.net';</script>",
    "Voici <nina@example.org>.",
    "<p>nina@example.org",  # Incomplete HTML mentioned literally must not break routing.
    "x " * 600 + "nina@example.org",  # No 500-character routing-history truncation.
])
async def test_humans_receive_detected_contacts_without_loading_an_agent_or_calling_a_model(monkeypatch, source):
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    infer = AsyncMock(side_effect=AssertionError("Human dispatch must remain deterministic"))
    loader = AsyncMock(side_effect=AssertionError("No agent loading is necessary"))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    result = await Dispatcher().run_conversation(round_id=uuid4(), run_id=uuid4(), agent_id=7,
        objective=source, sender_is_ai=False, agent_loader=loader,
        messages=[{"text": "Earlier contact old@example.net"}, {"text": source}])
    assert result.success and result.decision.route == "EXEC"
    assert [item.value for item in result.contact_infos] == ["nina@example.org"]
    infer.assert_not_awaited()
    loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_ai_exchange_can_end_and_still_return_its_new_coordinates(monkeypatch):
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    source = "Merci. Son numéro est le 07 06 05 04 03."
    result = await Dispatcher().run_conversation(round_id=uuid4(), run_id=uuid4(), agent_id=7,
        objective=source, sender_is_ai=True,
        messages=[{"text": source, "sender": {"agent_id": 8}}] * module.AI_EXCHANGE_MAX_DEPTH)
    assert result.success and result.decision.route == "END"
    assert [item.normalized_value for item in result.contact_infos] == ["+33706050403"]


@pytest.mark.asyncio
async def test_task_forced_route_keeps_contact_detection_without_an_inference(monkeypatch):
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    task = module._EvaluationTaskContext.from_input({
        "objective": "Contact nina@example.org", "forced_route": "EXEC", "forced_effort": "standard",
        "messages": [{"text": "Earlier old@example.net"}],
    })
    result = await Dispatcher().run(task)
    assert result.success and (result.decision.route, result.decision.effort) == ("EXEC", "standard")
    assert [item.value for item in result.contact_infos] == ["nina@example.org"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["EXEC", "PLAN"])
async def test_inferred_task_route_keeps_the_same_detection_and_durable_serialization(monkeypatch, route):
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    task = module._EvaluationTaskContext.from_input({"objective": "Contact nina@example.org"})
    monkeypatch.setattr(module, "resolve_agent_decision_models", AsyncMock(return_value=(None, None, False)))
    monkeypatch.setattr(module, "has_agent_profile_model", AsyncMock(return_value=True))
    infer = AsyncMock(return_value=DispatchResult(prompt="synthetic", decision=DispatchDecision(
        route=route, effort="high" if route == "PLAN" else "standard")))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", infer)
    result = await Dispatcher().run(task)
    assert result.decision.route == route
    assert [item.value for item in result.contact_infos] == ["nina@example.org"]
    assert DispatchResult.model_validate_json(result.model_dump_json()).contact_infos == result.contact_infos


def test_older_dispatch_results_remain_readable_with_an_empty_list():
    result = DispatchResult.model_validate({"prompt": "", "decision": {"route": "EXEC"}})
    assert result.contact_infos == []


@pytest.mark.parametrize("text, platform, key", [
    ("Telegram: @Synthetic_Nina ; https://t.me/synthetic_nina", "telegram", "synthetic_nina"),
    ("WhatsApp: +33612345678 ; https://wa.me/33612345678", "whatsapp", "+33612345678"),
])
def test_messaging_profiles_and_labeled_identities_share_a_key(text, platform, key):
    result = detect_contact_infos(text, default_country="FR")
    assert len(result) == 2
    assert {(item.platform, item.normalized_value) for item in result} == {(platform, key)}


@pytest.mark.asyncio
@pytest.mark.parametrize("current, expected", [("Current nina@example.org", ["nina@example.org"]), ("", [])])
async def test_task_scans_current_message_before_its_objective_and_history(current, expected):
    task = module._EvaluationTaskContext.from_input({
        "objective": "Old objective old@example.org", "forced_route": "EXEC", "forced_effort": "standard",
        "data": {"text": current},
        "messages": [{"text": "Earlier sam@example.net"}],
    })
    result = await Dispatcher().run(task)
    assert [item.value for item in result.contact_infos] == expected


def test_generated_coordinates_preserve_offsets_keys_and_multiplicity():
    """Exercise 500 independently generated messages with an explicit extraction oracle."""
    import random
    randomizer = random.Random(73195)
    prefixes = ["Voici les coordonnées : ", "Coordonnées de Nina : ", "🤖 Transmis par un agent : ", "Échange fictif\n"]
    separators = [" ", ".", "-", "\u00a0", "\u202f", ""]
    for index in range(500):
        separator = randomizer.choice(separators)
        phone = separator.join(("07", "06", "05", "04", "03"))
        email = f"person{index}+test@example.org"
        text = f"{randomizer.choice(prefixes)}{email} ; {phone} ; Telegram: @synthetic_{index}."
        result = detect_contact_infos(text, default_country="FR")
        assert [(item.type, item.value) for item in result] == [
            ("email", email), ("phone", phone), ("instant_messaging", f"@synthetic_{index}")]
        assert result[1].normalized_value == "+33706050403"
        assert all(text[item.start:item.end] == item.value for item in result)
        assert all(left.end <= right.start for left, right in zip(result, result[1:]))
        assert result == detect_contact_infos(text, default_country="FR")


@pytest.mark.parametrize("number", ["+1 202 555 0123 ext. 456", "+1 202 555 0123 ext. 789"])
def test_phone_extensions_are_retained_in_comparison_keys(number):
    key = normalize_contact_coordinate("phone", number)
    assert key.endswith(";ext=" + number.rsplit(" ", 1)[-1])
    assert normalize_contact_coordinate("phone", key) == key
    assert detect_contact_infos(number, default_country="US")[0].normalized_value == key
