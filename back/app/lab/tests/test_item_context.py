from copy import deepcopy

import pytest

from app.lab.contracts import CONTRACTS, LabInput, capture_input, resolve_input, split_capture
from app.lab import mechanism_evaluation_service as service
from app.lab.models import LabEvaluationCase, LabEvaluationDataset


@pytest.mark.parametrize("mechanism", list(CONTRACTS))
def test_item_context_cannot_override_shared_settings(mechanism):
    contract = CONTRACTS[mechanism]
    descriptor = contract.descriptor()
    assert not (
        descriptor["context_schema"]["properties"].keys()
        & descriptor["parameters_schema"]["properties"].keys()
    )
    with pytest.raises(ValueError, match="Extra inputs"):
        resolve_input(mechanism, LabInput(variable_value="Request", context={"language": "fr"}), {})
    for name in contract.context_type.model_fields:
        with pytest.raises(ValueError, match="Extra inputs"):
            resolve_input(mechanism, LabInput(variable_value="Request"), {name: []})


@pytest.mark.parametrize(
    "mechanism,field",
    [
        ("dispatcher", "messages"),
        ("briefing", "history"),
        ("planner", "history"),
        ("planner", "clarifications"),
        ("task_executor", "history"),
        ("conversation_executor", "history"),
        ("voice_executor", "history"),
        ("briefing", "recent_attachments"),
        ("briefing", "recent_images"),
    ],
)
def test_capture_and_resolution_preserve_each_items_history(mechanism, field):
    histories = [[{"text": text, "uri": f"tool://files/{text}"}] for text in ["first", "second"]]
    shared = {}
    for history in histories:
        native = {"objective": "Request", "message": "Request", field: deepcopy(history)}
        captured = capture_input(mechanism, native)
        assert split_capture(mechanism, native).parameters == {}
        item, rebuilt = resolve_input(mechanism, captured, shared)
        assert item.context[field] == rebuilt[field] == history
        native[field].clear()
        assert item.context[field] == history
    assert shared == {}


def test_topic_and_memory_metadata_are_part_of_the_item():
    topic_native = {
        "initial_topic": {"title": "Existing topic"},
        "messages": [{"text": "Hello", "timestamp": 10}],
    }
    topic = capture_input("topic_classification", topic_native)
    resolved, native = resolve_input("topic_classification", topic, {})
    assert resolved.context["message_context"] == [{"timestamp": 10}]
    assert native["initial_topic"]["title"] == "Existing topic"
    memory_native = {
        "topic": {"id": "topic-1", "title": "Preferences"},
        "history": [{"speaker_name": "Ada", "speaker_kind": "human", "text": "Earlier"}],
        "current": [{"speaker_name": "Ada", "speaker_kind": "human", "text": "French please"}],
    }
    memory = capture_input("memory_extraction", memory_native)
    _, rebuilt = resolve_input("memory_extraction", memory, {})
    for field in ("topic", "history", "current"):
        assert rebuilt[field] == memory_native[field]


def test_previous_goal_tracking_is_item_evidence():
    native = {
        "cycle_result": {"status": "completed", "result": "Done"},
        "tracking_content": "<p>Prior cycle</p>",
    }
    item = capture_input("goal_tracking", native)
    assert split_capture("goal_tracking", native).parameters == {}
    assert (
        resolve_input("goal_tracking", item, {})[1]["tracking_content"]
        == native["tracking_content"]
    )


def test_history_retains_native_size_limits():
    for mechanism, limit in [("briefing", 6), ("planner", 30), ("memory_extraction", 5)]:
        with pytest.raises(ValueError, match="at most"):
            resolve_input(
                mechanism,
                LabInput(variable_value="Request", context={"history": [{}] * (limit + 1)}),
                {},
            )


@pytest.mark.asyncio
async def test_captures_preserve_history_through_preview_reference_and_snapshot(db, monkeypatch):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.llm import LLM, LLMProvider
    from app.lab.capture_service import check_capture
    from app.lab.models import LabEvaluationRun
    from app.lab.schemas import EvaluationRunStart, MechanismExpectedGenerate

    provider = LLMProvider(
        name=f"context-{uuid4()}", base_url="https://example.test/v1", is_active=True
    )
    db.add(provider)
    await db.flush()
    llm = LLM(
        llm_provider_id=provider.id,
        provider=provider,
        code=f"context-{uuid4()}",
        llm_name="test",
        label="test",
        service_capabilities=["chat"],
    )
    db.add(llm)
    await db.flush()
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=llm))
    monkeypatch.setattr(service.llm_service, "get_profile_llm", AsyncMock(return_value=llm))
    inference = AsyncMock(return_value=({"result": "Reference", "choices": []}, 0))
    monkeypatch.setattr(service, "evaluate_mechanism", inference)

    dataset = LabEvaluationDataset(
        name="Different histories", mechanism="briefing", parameters={"language": "en"}
    )
    db.add(dataset)
    await db.commit()
    for text in ["First conversation", "Second conversation"]:
        native = {"objective": "Prepare a report", "language": "en", "history": [{"text": text}]}
        item = LabEvaluationCase(
            dataset_id=dataset.id,
            name=text,
            readiness="ready",
            expected_output={"result": "Reference", "choices": []},
            input_data=capture_input("briefing", native),
            source_capture={"input_data": native},
        )
        await check_capture(item)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        preview = await service.preview_input(
            "briefing", dataset.id, LabInput.model_validate(item.input_data)
        )
        assert preview.input.context["history"] == native["history"]
        assert preview.native_input["history"] == native["history"]
        assert text in preview.candidate_prompt
        assert preview.origins["history"] == "item"
        assert preview.origins["language"] == "dataset"
        assert "history" not in preview.parameters
        assert "parameter_confirmation" not in item.source_capture
        await service.generate_expected("briefing", item.id, MechanismExpectedGenerate())
        assert inference.call_args.kwargs["input_data"]["history"] == native["history"]
        await service.generate_expected(
            "briefing",
            item.id,
            MechanismExpectedGenerate(
                input_data=LabInput(
                    variable_value="Prepare a report",
                    context={"history": [{"text": "Unsaved edit"}]},
                ),
            ),
        )
        assert inference.call_args.kwargs["input_data"]["history"] == [{"text": "Unsaved edit"}]
    assert dataset.parameters == {"language": "en"}
    started = await service.start_run("briefing", dataset.id, EvaluationRunStart(llm_id=llm.id))
    run = await db.get(LabEvaluationRun, started.id)
    assert len(run.case_snapshots) == 2
    assert "history" not in run.configuration_snapshot["parameters"]
    for snapshot in run.case_snapshots:
        history = [{"text": snapshot["name"]}]
        assert snapshot["input_data"]["context"]["history"] == history
        assert snapshot["resolved_input"]["history"] == history


def test_corpus_fingerprint_includes_item_history():
    from app.lab.inference_profile import benchmark_fingerprints

    cases = [
        {
            "input_data": {"variable_value": "Request", "context": {"history": []}},
            "expected_output": {},
        }
    ]
    original = benchmark_fingerprints(cases, {}, {"binding": "model"}, {})
    cases[0]["input_data"]["context"]["history"] = [{"text": "Prior turn"}]
    changed = benchmark_fingerprints(cases, {}, {"binding": "model"}, {})
    assert [key for key in original if original[key] != changed[key]] == ["corpus"]
