"""Synthetic generation preserves each experiment contract and publishes only complete drafts."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.lab import mechanism_evaluation_service as experiments
from app.lab import synthetic_service as service
from app.lab.contracts import CONTRACTS
from app.lab.mechanism_registry import get_mechanism
from app.lab.models import LabEvaluationCase, LabEvaluationDataset
from app.lab.schemas import EvaluationCaseCreate, MechanismCaseUpdate, MechanismDatasetCreate
from app.lab.synthetic_schemas import SyntheticContent, SyntheticDatasetRequest


def generated_content(mechanism):
    variable = "<p>Summarize the fictional observatory schedule.</p>"
    context = {}
    if mechanism == "topic_classification":
        variable = ["When does the fictional observatory open?"]
    elif mechanism == "memory_extraction":
        variable = ["Please keep the schedule brief."]
        context = {"topic": {"id": "synthetic-topic", "title": "Observatory"}}
    elif mechanism == "outcome_reflection":
        variable = {"terminal_status": "SUCCESS", "final_result": "Schedule checked against supplied evidence."}
    elif mechanism == "goal_tracking":
        variable = {"status": "SUCCESS", "result": "<p>The schedule is ready.</p>"}
    elif mechanism == "task_analysis":
        variable = {"selected_task": {"objective": "Summarize the observatory schedule", "status": "SUCCESS"}}
    output = deepcopy(get_mechanism(mechanism).default_output)
    if mechanism == "briefing":
        output = {"result": "Check the supplied schedule before summarizing it.", "choices": [
            {"kind": "other", "identifier": "schedule_evidence", "reason": "Verify the opening time."},
        ]}
    if mechanism == "topic_classification":
        output = {"topics": ["Observatory schedule"]}
    if mechanism.endswith("_executor"):
        output = {"action": "reply", "response": "The supplied schedule opens at nine.", "tool_calls": [], "tool_results": []}
    return SyntheticContent.model_validate({
        "description": "A completely fictional observatory experiment.", "parameters": {},
        "cases": [{"name": "Opening schedule", "categories": ["nominal"],
                   "input_data": {"variable_value": variable, "context": context}, "expected_output": output}],
    })


def fake_generator(monkeypatch, content):
    llm = SimpleNamespace(id=1, code="synthetic-model", llm_name="synthetic-model", service_capabilities=["chat"])
    monkeypatch.setattr(service.llm_service, "get_profile_llm", AsyncMock(return_value=llm))
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=llm))
    infer = AsyncMock(return_value=SimpleNamespace(output=content, cost=0.012))
    monkeypatch.setattr(service, "run_structured", infer)
    return infer


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
async def test_every_lab_generates_reviewable_cases_with_its_own_contract(db, monkeypatch, mechanism):
    infer = fake_generator(monkeypatch, generated_content(mechanism))
    request = SyntheticDatasetRequest(name=f"Synthetic {mechanism}", count=1, categories=["nominal"], instructions="Use an observatory")
    result = await service.generate_dataset(mechanism, request)
    assert result.dataset.case_count == 1
    assert result.dataset.ready_case_count == 0
    assert result.dataset.mechanism == mechanism
    assert result.cost == 0.012
    prompt = json.loads(infer.call_args.kwargs["prompt"])
    assert prompt["mechanism"] == mechanism
    assert prompt["contract"]["variable_name"] == CONTRACTS[mechanism].variable_name
    assert prompt["request"]["instructions"] == request.instructions
    assert prompt["scenarios"]
    assert prompt["usage_context"]
    assert prompt["expected_output_schema"]
    assert prompt["rubric"]["dimensions"]
    if mechanism in {"topic_classification", "memory_extraction"}:
        assert prompt["native_input_schema"]["properties"]
    if mechanism.endswith("_executor"):
        assert prompt["simulated_tools"]
    cases = await experiments.list_cases(mechanism, result.dataset.id)
    assert cases[0].readiness == "draft"
    assert cases[0].source_capture["source_kind"] == "synthetic"
    assert cases[0].source_task_id is None
    # Reviewing through the real editor contract makes a generated case usable.
    saved = await experiments.update_case(mechanism, cases[0].id, MechanismCaseUpdate(
        revision=cases[0].revision, input_data=cases[0].input_data, expected_output=cases[0].expected_output,
    ))
    assert saved.readiness == "ready"
    with pytest.raises(ValueError, match="name|nom"):
        await service.generate_dataset(mechanism, request)
    assert infer.await_count == 1


@pytest.mark.asyncio
async def test_invalid_last_case_or_provider_failure_never_publishes_partial_dataset(db, monkeypatch):
    content = generated_content("briefing")
    bad = content.cases[0].model_copy(deep=True)
    bad.name = "Invalid context"
    bad.input_data.context = {"unknown_setting": True}
    content.cases.append(bad)
    infer = fake_generator(monkeypatch, content)
    before = await db.scalar(select(func.count()).select_from(LabEvaluationDataset))
    request = SyntheticDatasetRequest(name="Rejected generation", count=2, categories=["nominal"])
    with pytest.raises(ValueError):
        await service.generate_dataset("briefing", request)
    assert await db.scalar(select(func.count()).select_from(LabEvaluationDataset)) == before
    infer.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        await service.generate_dataset("briefing", request)
    assert await db.scalar(select(func.count()).select_from(LabEvaluationDataset)) == before


@pytest.mark.parametrize("change", ["count", "duplicate", "coverage", "topic_alignment", "memory_links", "tools"])
def test_synthetic_references_must_be_consistent_with_the_experiment(change):
    mechanism = "topic_classification" if change == "topic_alignment" else "memory_extraction" if change == "memory_links" else "task_executor" if change == "tools" else "briefing"
    content = generated_content(mechanism)
    request = SyntheticDatasetRequest(name="Invalid experiment", count=1, categories=["nominal"])
    if change == "count":
        request.count = 2
    elif change == "duplicate":
        content.cases.append(content.cases[0].model_copy(deep=True))
        request.count = 2
    elif change == "coverage":
        content.cases[0].categories = ["security"]
    elif change == "topic_alignment":
        content.cases[0].expected_output = {"topics": []}
    elif change == "memory_links":
        content.cases[0].expected_output["relevant_memory_ids"] = ["not-in-corpus"]
    elif change == "tools":
        content.cases[0].expected_output["tool_calls"] = [{"name": "live_tool", "arguments": {}}]
    with pytest.raises(ValueError):
        service.validate_content(mechanism, request, content)


@pytest.mark.asyncio
async def test_missing_model_and_timeout_leave_existing_datasets_untouched(db, monkeypatch):
    infer = fake_generator(monkeypatch, generated_content("briefing"))
    request = SyntheticDatasetRequest(name="Model failure", count=1, categories=["nominal"])
    monkeypatch.setattr(service.llm_service, "get_profile_llm", AsyncMock(return_value=None))
    with pytest.raises(ValueError):
        await service.generate_dataset("briefing", request)
    infer.assert_not_awaited()
    infer = fake_generator(monkeypatch, generated_content("briefing"))
    infer.side_effect = TimeoutError()
    with pytest.raises(ValueError, match="minutes"):
        await service.generate_dataset("briefing", request)
    assert not (await db.scalars(select(LabEvaluationDataset).where(LabEvaluationDataset.name == request.name))).all()


@pytest.mark.asyncio
async def test_synthetic_http_requires_privileges_and_creates_drafts(client, monkeypatch):
    infer = fake_generator(monkeypatch, generated_content("briefing"))
    url = "/api/evaluation/briefing/datasets/synthetic"
    payload = {"name": "HTTP synthetic", "count": 1, "categories": ["nominal"]}
    assert (await client.post(url, json=payload)).status_code in {401, 403}
    infer.assert_not_awaited()
    credentials = {"email": "synthetic-admin@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    response = await client.post(url, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["dataset"]["ready_case_count"] == 0
    assert (await client.post(url, json={**payload, "count": 21})).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
@pytest.mark.parametrize("granted", [True, False])
async def test_generation_requires_edit_of_the_requested_lab(monkeypatch, mechanism, granted):
    from app.lab.access import MECHANISM_PRIVILEGES
    from app.lab.assertions import LabMechanismEditPrivilegeAssertion
    from app.lab.router import generate_synthetic_dataset
    from core.authorize import AssertionContext

    check = AsyncMock(return_value=granted)
    monkeypatch.setattr("app.lab.assertions.check_privilege", check)
    assert generate_synthetic_dataset._authorize_meta["assertion"] is LabMechanismEditPrivilegeAssertion
    user, db = SimpleNamespace(), SimpleNamespace()
    assert await LabMechanismEditPrivilegeAssertion().assert_(AssertionContext(user=user, db=db, params={"mechanism": mechanism})) is granted
    check.assert_awaited_once_with(user, [MECHANISM_PRIVILEGES[mechanism][1]], db)


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
async def test_generation_uses_selected_experiment_context_without_copying_cases(db, monkeypatch, mechanism):
    source = await experiments.prepare_dataset(mechanism, MechanismDatasetCreate(
        name=f"Context {mechanism}", description="Scheduling at a fictional observatory.",
    ))
    if "language" in source.parameters:
        source.parameters = {**source.parameters, "language": "fr"}
    if mechanism == "planner":
        source.parameters = {**source.parameters, "max_nodes": 4, "can_clarify": False}
    if mechanism == "memory_extraction":
        source.parameters = {**source.parameters, "source_kind": "task"}
    if get_mechanism(mechanism).executor:
        source.prompt_suffix = "Only confirm deliveries supported by a receipt."
    db.add(source)
    await db.commit()
    original = await experiments.dataset_read(source)
    private_case = await experiments.create_case(
        mechanism, source.id, EvaluationCaseCreate(name="Do not copy this existing case")
    )
    content = generated_content(mechanism)
    content.parameters = deepcopy(source.parameters)
    if mechanism == "memory_extraction":
        content.cases[0].input_data.variable_value = {
            "task_trace": {"status": "SUCCESS", "final_result": "Schedule summarized"},
            "messages": ["Please keep the schedule brief."],
        }
    infer = fake_generator(monkeypatch, content)
    result = await service.generate_dataset(mechanism, SyntheticDatasetRequest(
        name=f"Contextual {mechanism}", count=1, categories=["nominal"],
        source_dataset_id=source.id, source_revision=source.revision,
    ))
    prompt = json.loads(infer.call_args.kwargs["prompt"])
    assert prompt["shared_parameters"] == original.parameters
    assert prompt["source_context"]["description"] == source.description
    assert private_case.name not in infer.call_args.kwargs["prompt"]
    assert result.dataset.parameters == original.parameters
    assert result.dataset.configuration == original.configuration
    assert result.dataset.prompt_suffix == original.prompt_suffix
    if get_mechanism(mechanism).executor:
        assert source.prompt_suffix in prompt["executor_system_prompt"]
    cases = await experiments.list_cases(mechanism, result.dataset.id)
    assert cases[0].source_capture["source_context"]["revision"] == source.revision
    assert len(await experiments.list_cases(mechanism, source.id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["wrong_lab", "deleted", "stale", "changed_parameters"])
async def test_invalid_context_never_creates_a_misleading_experiment(db, monkeypatch, invalid):
    from app.lab.dispatcher_evaluation_service import RevisionConflictError

    source = await experiments.prepare_dataset("briefing", MechanismDatasetCreate(name="Source"))
    source.parameters = {**source.parameters, "language": "fr"}
    db.add(source)
    await db.commit()
    revision = source.revision
    if invalid == "deleted":
        source.soft_delete()
        await db.commit()
    if invalid == "stale":
        source.description = "Changed context"
        await db.commit()
    infer = fake_generator(monkeypatch, generated_content("briefing"))
    with pytest.raises((LookupError, RevisionConflictError, ValueError)):
        await service.generate_dataset("planner" if invalid == "wrong_lab" else "briefing", SyntheticDatasetRequest(
            name="Rejected context", count=1, categories=["nominal"],
            source_dataset_id=source.id, source_revision=revision,
        ))
    assert not (await db.scalars(select(LabEvaluationDataset).where(LabEvaluationDataset.name == "Rejected context"))).all()
    if invalid != "changed_parameters":
        infer.assert_not_awaited()


def test_synthetic_reference_cannot_replace_a_configured_tool_failure_with_success():
    content = generated_content("task_executor")
    failure = {"success": False, "error": "Destination unavailable"}
    content.parameters = {"available_tools": ["deliver_report"], "tool_responses": {"executor_tool_call": [failure]}}
    call = {"name": "executor_tool_call", "arguments": {"tool_name": "deliver_report", "arguments": {}}}
    content.cases[0].expected_output = {
        "action": "use_tool", "response": "Delivery was not confirmed.",
        "tool_calls": [call], "tool_results": [{**call, "result": {"success": True}}],
    }
    request = SyntheticDatasetRequest(name="Tool evidence", count=1, categories=["nominal"])
    with pytest.raises(ValueError, match="configured response fixtures"):
        service.validate_content("task_executor", request, content)
    content.cases[0].expected_output["tool_results"][0]["result"] = failure
    service.validate_content("task_executor", request, content)
