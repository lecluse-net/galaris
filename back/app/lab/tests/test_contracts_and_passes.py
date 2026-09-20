from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.lab.contracts import CONTRACTS, LabInput, capture_input, resolve_input, split_capture
from app.lab.models import (
    LabEvaluationDataset,
    LabEvaluationCase,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabJudgmentResult,
)
from app.lab import mechanism_evaluation_service as service, run_inference
from app.lab.judgment_service import rejudge
from app.lab.mechanism_rubrics import get_rubric
from app.lab.schemas import EvaluationRejudge, MechanismJudgeOutput


@pytest.mark.parametrize("route, effort, briefing, high, uses_llm_calls, permitted", [
    ("BRIEFING", "high", True, True, True, True),
    ("BRIEFING", "high", False, True, True, False),
    ("EXEC", "high", False, False, True, False),
    ("EXEC", "standard", False, False, True, True),
    ("PLAN", "standard", False, True, True, False),
    ("EXEC", "high", False, True, False, False),
    ("EXEC", "standard", False, True, False, True),
])
def test_lab_checks_the_same_harness_choices_as_runtime(route, effort, briefing, high, uses_llm_calls, permitted):
    from app.lab.objective_checks import check_output

    checks = check_output("dispatcher", {"pipeline_policy": {
        "use_planner": True, "use_briefing": briefing,
        "briefing_efforts": ["high"] if briefing else [],
        "execution_efforts": ["standard", "high"] if high else ["standard"],
        "uses_llm_calls": uses_llm_calls,
    }}, {"route": route, "effort": effort, "language": "en"})

    assert next(check for check in checks if check["code"] == "harness_choice")["passed"] is permitted


def test_one_variable_and_context_scope():
    value = LabInput(variable_value="Prepare the report")
    resolved, native = resolve_input("planner", value, {"language": "en", "max_nodes": 7})
    assert resolved.variable_value == native["objective"] == "Prepare the report"
    assert native["language"] == "en"
    assert resolved.model_dump() == {
        "variable_value": "Prepare the report",
        "context": {"history": [], "clarifications": []},
    }
    with pytest.raises(ValueError):
        LabInput(variable_value="Prepare the report", parameters={"language": "fr"})
    assert native["max_nodes"] == 7
    assert "expected_output" not in native
    with pytest.raises(ValueError):
        LabInput.model_validate({"variable_value": "a", "second_variable": "b"})
    with pytest.raises(ValueError):
        resolve_input("planner", value, {"unknown": True})


def test_topic_capture_separates_content_from_metadata():
    native = {
        "messages": [{"text": "Hello", "timestamp": 10}, {"text": "Bye", "timestamp": 20}],
        "initial_topic": None,
    }
    captured = capture_input("topic_classification", native)
    assert captured["variable_value"] == ["Hello", "Bye"]
    source_parameters = split_capture("topic_classification", native).parameters
    assert source_parameters == {}
    assert captured["context"]["message_context"] == [{"timestamp": 10}, {"timestamp": 20}]
    _, rebuilt = resolve_input("topic_classification", captured, source_parameters)
    assert [message["text"] for message in rebuilt["messages"]] == ["Hello", "Bye"]
    assert [message["timestamp"] for message in rebuilt["messages"]] == [10, 20]
    captured["context"]["message_context"].pop()
    with pytest.raises(ValueError, match="one message context"):
        resolve_input("topic_classification", captured, source_parameters)


def test_outcome_cannot_hide_mission_in_variable():
    with pytest.raises(ValueError):
        resolve_input("outcome_reflection", LabInput(variable_value={"objective": "mission"}), {})


@pytest.mark.asyncio
async def test_two_passes_and_rejudge_preserve_candidate_outputs(db, monkeypatch):
    from app.llm import LLM, LLMProvider
    from app.lab.inference_profile import model_binding

    provider = LLMProvider(
        name=f"test-provider-{uuid4()}", base_url="https://example.test/v1", is_active=True
    )
    db.add(provider)
    await db.flush()
    llm = LLM(
        llm_provider_id=provider.id,
        provider=provider,
        code=f"judge-{uuid4()}",
        llm_name="judge",
        label="judge",
        service_capabilities=["chat"],
    )
    db.add(llm)
    await db.flush()
    dataset = LabEvaluationDataset(name=f"passes-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    cases = [LabEvaluationCase(dataset_id=dataset.id, name=f"case-{i}") for i in range(2)]
    db.add_all(cases)
    await db.flush()
    snapshots = [
        {
            "id": str(case.id),
            "input_data": {
                "variable_value": case.name,
                "context": {"history": [{"text": f"History for {case.name}"}]},
            },
            "resolved_input": {
                "objective": case.name,
                "language": "en",
                "history": [{"text": f"History for {case.name}"}],
            },
            "expected_output": {"result": "reference", "choices": []},
        }
        for case in cases
    ]
    run = LabEvaluationRun(
        dataset_id=dataset.id,
        llm_id=llm.id,
        judge_llm_id=None,
        llm_snapshot={"binding": model_binding(llm)},
        case_snapshots=snapshots,
        total_cases=2,
        configuration_snapshot={
            "rubric": get_rubric("briefing").prompt_value(),
            "parameters": {"language": "en"},
        },
    )
    db.add(run)
    await db.commit()
    dataset.parameters = {"language": "fr"}
    for case in cases:
        case.input_data = {"variable_value": case.name, "context": {"history": []}}
    await db.commit()
    calls = []

    async def candidate(*args, **kwargs):
        assert kwargs["input_data"]["language"] == "en"
        assert kwargs["input_data"]["history"] == [
            {"text": f"History for {kwargs['input_data']['objective']}"}
        ]
        calls.append("candidate")
        return {"result": kwargs["input_data"]["objective"], "choices": []}, 0.1

    async def judge(**kwargs):
        assert kwargs["input_data"]["parameters"] == {"language": "en"}
        assert kwargs["input_data"]["context"]["history"] == [
            {"text": f"History for {kwargs['input_data']['variable_value']}"}
        ]
        calls.append("judge")
        return MechanismJudgeOutput(
            explanation="Supported",
            critical_failures=[],
            confidence_percent=95,
            dimensions=[
                {"code": dim.code, "score_percent": 90, "assessment": "Supported"}
                for dim in get_rubric("briefing").dimensions
            ],
        ), 0.02

    monkeypatch.setattr(run_inference, "evaluate_mechanism", candidate)
    monkeypatch.setattr(run_inference, "_judge", judge)
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=llm))
    # A missing judge must fail only the judgment, after both candidates are saved.
    await service.process_runs()
    await service.process_runs()
    await db.refresh(run)
    assert calls == ["candidate", "candidate"]
    assert run.phase == "judgment" and run.completed_cases == 2
    results = (
        await db.scalars(select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run.id))
    ).all()
    original = [(row.id, row.actual_output, row.cost) for row in results]
    await service.process_runs()
    await service.process_runs()
    await db.refresh(run)
    assert run.status == "partial"
    assert run.score_percent is None
    assert len((await db.scalars(select(LabJudgmentResult))).all()) == 2

    monkeypatch.setattr(service.llm_service, "get_profile_llm", AsyncMock(return_value=llm))
    await rejudge("briefing", run.id, EvaluationRejudge())
    await service.process_runs()
    await service.process_runs()
    await db.refresh(run)
    assert calls == ["candidate", "candidate", "judge", "judge"]
    assert run.status == "completed" and run.judged_cases == 2
    assert run.score_percent == pytest.approx(90)
    assert run.candidate_cost == pytest.approx(0.2)
    assert run.judge_cost == pytest.approx(0.04)
    assert len((await db.scalars(select(LabJudgmentResult))).all()) == 4
    for row in results:
        await db.refresh(row)
    assert [(row.id, row.actual_output, row.cost) for row in results] == original


@pytest.mark.asyncio
async def test_reasoning_scope_freezes_none_and_restores_profile(monkeypatch):
    from app.llm.structured_service import reasoning_effort_scope, resolve_reasoning_effort

    profile = AsyncMock(return_value="high")
    monkeypatch.setattr(service.llm_service, "get_profile_reasoning_effort_for_agent_id", profile)
    assert await resolve_reasoning_effort("text_high_llm_id", None) == "high"
    with reasoning_effort_scope(None):
        assert await resolve_reasoning_effort("text_high_llm_id", None, "high") is None
        with reasoning_effort_scope("low"):
            assert await resolve_reasoning_effort("text_high_llm_id", None) == "low"
        assert await resolve_reasoning_effort("text_high_llm_id", None) is None
    assert await resolve_reasoning_effort("text_high_llm_id", None) == "high"
    assert profile.await_count == 2


def test_fingerprints_separate_corpus_context_candidate_and_judge():
    from copy import deepcopy
    from app.lab.inference_profile import benchmark_fingerprints

    cases = [
        {
            "input_data": {"variable_value": "Report"},
            "expected_output": {"result": "Done"},
            "reasoning_effort": "high",
        }
    ]
    config = {
        "dataset_id": "a",
        "dataset_revision": 1,
        "system_prompt": "Instructions",
        "parameters": {"language": "fr"},
        "rubric": {"version": "one"},
        "judge_reasoning_effort": "high",
    }
    original = benchmark_fingerprints(cases, config, {"binding": "candidate"}, {"binding": "judge"})
    assert original == benchmark_fingerprints(
        cases,
        {**config, "dataset_id": "b", "dataset_revision": 9},
        {"binding": "candidate"},
        {"binding": "judge"},
    )
    judged = benchmark_fingerprints(
        cases,
        {**config, "rubric": {"version": "two"}},
        {"binding": "candidate"},
        {"binding": "judge"},
    )
    assert [key for key in original if judged[key] != original[key]] == ["judge"]
    changed = deepcopy(config)
    changed["parameters"]["language"] = "en"
    contextual = benchmark_fingerprints(
        cases, changed, {"binding": "candidate"}, {"binding": "judge"}
    )
    assert [key for key in original if contextual[key] != original[key]] == ["context"]


@pytest.mark.asyncio
async def test_dispatcher_preview_respects_deterministic_plan_and_pipeline():
    from app.agent import preview_dispatcher_input

    _, native = resolve_input(
        "dispatcher",
        LabInput(variable_value="Plan the release"),
        {"forced_route": "PLAN"},
    )
    assert await preview_dispatcher_input(native) == ("", "")
    _, blocked = resolve_input(
        "dispatcher",
        LabInput(variable_value="Plan the release"),
        {"forced_route": "PLAN", "pipeline_policy": {"use_planner": False}},
    )
    assert await preview_dispatcher_input(blocked) == ("", "")


@pytest.mark.parametrize("mechanism", ["task_executor", "conversation_executor", "voice_executor"])
def test_executor_configuration_cannot_accept_unused_instructions(mechanism):
    assert service.validate_configuration(mechanism, {}) == {}
    with pytest.raises(ValueError, match="prompt suffix"):
        service.validate_configuration(mechanism, {"system_prompt": "Would be ignored"})


@pytest.mark.asyncio
async def test_capture_requires_confirmation_and_never_stores_item_parameters(db):
    from app.lab.capture_service import CaptureParametersMismatch, check_capture

    dataset = LabEvaluationDataset(
        name="Shared context", mechanism="planner", parameters={"language": "en"}
    )
    db.add(dataset)
    await db.commit()

    def captured():
        return LabEvaluationCase(
            dataset_id=dataset.id,
            name="Report",
            readiness="ready",
            input_data={"variable_value": "Prepare a report"},
            expected_output={"steps": []},
            source_capture={"input_data": {"objective": "Prepare a report", "language": "fr"}},
        )

    item = captured()
    with pytest.raises(CaptureParametersMismatch) as conflict:
        await check_capture(item)
    assert conflict.value.detail["differences"] == [
        {"name": "language", "source_value": "fr", "dataset_value": "en"}
    ]
    assert not (
        await db.scalars(
            select(LabEvaluationCase).where(LabEvaluationCase.dataset_id == dataset.id)
        )
    ).all()
    token = conflict.value.detail["confirmation_token"]
    with pytest.raises(CaptureParametersMismatch):
        await check_capture(item, "0" * 64)

    await check_capture(item, token)
    db.add(item)
    await db.commit()
    assert item.input_data == {"variable_value": "Prepare a report", "context": {}}
    assert dataset.parameters == {"language": "en"}
    assert item.readiness == "draft"
    assert (
        item.source_capture["parameter_confirmation"]["differences"]
        == conflict.value.detail["differences"]
    )
    assert resolve_input("planner", item.input_data, dataset.parameters)[1]["language"] == "en"

    dataset.parameters = {"language": "zh"}
    await db.commit()
    with pytest.raises(CaptureParametersMismatch) as changed:
        await check_capture(captured(), token)
    assert changed.value.detail["confirmation_token"] != token

    matching = captured()
    matching.source_capture = {"input_data": {"objective": "Prepare a report", "language": "zh"}}
    await check_capture(matching)
    assert matching.readiness == "ready"
    assert "parameter_confirmation" not in matching.source_capture


@pytest.mark.parametrize("mechanism", list(CONTRACTS))
def test_every_lab_rejects_item_parameters(mechanism):
    from app.lab.schemas import MechanismCaseUpdate, EvaluationExpectedGenerate
    from app.lab.models import LabEvaluationCase

    item = {"variable_value": "test", "parameters": {}}
    with pytest.raises(ValueError, match="Extra inputs"):
        resolve_input(mechanism, item, {})
    with pytest.raises(ValueError, match="Extra inputs"):
        MechanismCaseUpdate(revision=1, input_data=item, expected_output={})
    with pytest.raises(ValueError, match="Extra inputs"):
        EvaluationExpectedGenerate(input_data=item)
    with pytest.raises(ValueError, match="Extra inputs"):
        LabEvaluationCase(input_data=item)


def test_capture_parameters_normalize_nested_defaults():
    from app.lab.contracts import validate_parameters

    observed = validate_parameters(
        "dispatcher", {"pipeline_policy": {"use_planner": False}}, partial=True
    )
    dataset = validate_parameters("dispatcher", {"pipeline_policy": {"use_planner": False}})
    assert set(observed) == {"pipeline_policy"}
    assert observed["pipeline_policy"] == dataset["pipeline_policy"]
