from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.llm import LLM
from app.llm.structured_service import StructuredInferenceResult
from app.task import TaskMessage as Message
from app.topic import TopicCandidate, TopicClassification
from app.topic import evaluation as topic_evaluation, sequential_detection
from app.topic.sequential_detection import (
    PromptedTopicDetectionModel,
    TemporalContinuityPrior,
    TopicContinuityInterpretation,
    TopicDetectionDependencies,
    TopicDetectionEvaluation,
    TopicDetectionRun,
    calculate_continuity_prior,
    detect_topic,
    detect_topic_with_diagnostics,
    render_message_window,
    use_topic_detection_dependencies,
)


class FakeCatalog:
    def __init__(self, candidates: list[TopicCandidate]) -> None:
        self.candidates = {candidate.id: candidate for candidate in candidates}
        self.list_calls: list[str] = []
        self.resolve_calls = 0
        self.created_topic_id = uuid4()

    async def get_candidate(self, topic_id: UUID) -> TopicCandidate | None:
        return self.candidates.get(topic_id)

    async def list_candidates(self, *, activity: str) -> list[TopicCandidate]:
        self.list_calls.append(activity)
        return list(self.candidates.values())

    async def resolve(
        self,
        decision: TopicClassification,
        *,
        allowed_topic_ids: set[UUID],
    ) -> UUID:
        self.resolve_calls += 1
        if decision.action == "reuse":
            assert decision.topic_id in allowed_topic_ids
            assert decision.topic_id is not None
            return decision.topic_id
        return self.created_topic_id


class FakeModel:
    def __init__(
        self,
        *,
        continuity_probability: float = 0.9,
        classification: TopicClassification | None = None,
    ) -> None:
        self.continuity_probability = continuity_probability
        self.classification = classification or TopicClassification(
            action="create", title="Fallback topic"
        )
        self.continuity_calls = 0
        self.classification_calls = 0
        self.rendered_windows: list[str] = []

    async def interpret_continuity(
        self,
        *,
        rendered_window: str,
        current_topic: TopicCandidate,
        temporal_prior: TemporalContinuityPrior,
    ) -> tuple[TopicContinuityInterpretation, float]:
        del current_topic, temporal_prior
        self.continuity_calls += 1
        self.rendered_windows.append(rendered_window)
        return (
            TopicContinuityInterpretation(
                same_topic_probability=self.continuity_probability,
                reason="Controlled semantic decision.",
            ),
            0.01,
        )

    async def classify_current_message(
        self,
        *,
        rendered_window: str,
        candidates: list[TopicCandidate],
    ) -> tuple[TopicClassification, float]:
        del candidates
        self.classification_calls += 1
        self.rendered_windows.append(rendered_window)
        return self.classification, 0.02


def _topic(title: str) -> TopicCandidate:
    return TopicCandidate(id=uuid4(), title=title)


def _dependencies(
    candidates: list[TopicCandidate],
    *,
    probability: float = 0.9,
    classification: TopicClassification | None = None,
) -> tuple[TopicDetectionDependencies, FakeCatalog, FakeModel]:
    catalog = FakeCatalog(candidates)
    model = FakeModel(
        continuity_probability=probability,
        classification=classification,
    )
    return TopicDetectionDependencies(catalog=catalog, model=model), catalog, model


@pytest.mark.asyncio
async def test_lab_contract_exposes_topic_text_without_internal_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_topic = {
        "title": "Potager urbain",
        "description": "Cultures adaptées aux petits espaces en ville.",
        "keywords": ["potager", "balcon"],
    }
    observed_topic_id: UUID | None = None

    async def fake_detect(
        messages: list[Message],
        current_message_index: int,
        current_topic_id: UUID | None,
        *,
        dependencies: TopicDetectionDependencies,
        threshold: float,
        prior_parameters: object,
        context_characters: int,
    ) -> TopicDetectionRun:
        assert threshold == 0.55
        assert context_characters == 12000
        assert prior_parameters is not None
        del messages, current_message_index
        nonlocal observed_topic_id
        observed_topic_id = current_topic_id
        assert current_topic_id is not None
        candidate = await dependencies.catalog.get_candidate(current_topic_id)
        assert candidate is not None and candidate.title == current_topic["title"]
        return TopicDetectionRun(
            evaluation=TopicDetectionEvaluation(
                topic_id=current_topic_id,
                resolution="continuity",
            ),
            cost=0.01,
        )

    monkeypatch.setattr(topic_evaluation, "detect_topic_with_diagnostics", fake_detect)
    input_data = {
        "messages": [
            {"text": "Parlons du potager.", "time": 1_786_006_740},
            {"text": "Et pour les tomates ?", "time": 1_786_006_800},
        ],
        "initial_topic": current_topic,
    }

    output, cost = await topic_evaluation.evaluate_topic_detection(
        input_data=input_data,
        llm=cast(LLM, object()),
    )

    assert observed_topic_id is not None
    assert output == {"topics": ["Potager urbain", "Potager urbain"]}
    assert cost == 0.02
    assert str(observed_topic_id) not in json.dumps(input_data)
    assert str(observed_topic_id) not in json.dumps(output)


@pytest.mark.asyncio
async def test_lab_catalog_is_closed_over_the_dataset_and_keeps_created_topics() -> None:
    predefined = topic_evaluation.TopicDetectionLabTopic(
        title="Cuisine japonaise",
        description="Plats et techniques culinaires du Japon.",
        keywords=["ramen"],
    )
    catalog = topic_evaluation.ReadOnlyLabTopicCatalog(topics=[predefined])

    candidates = await catalog.list_candidates(activity="Préparons des ramen.")
    assert [candidate.title for candidate in candidates] == ["Cuisine japonaise"]
    assert await catalog.get_candidate(uuid4()) is None

    created_id = await catalog.resolve(
        TopicClassification(
            action="create",
            title="Voyage au Japon",
            description="Préparation d'un séjour au Japon.",
            keywords=["voyage"],
        ),
        allowed_topic_ids={candidate.id for candidate in candidates},
    )
    created = await catalog.get_candidate(created_id)
    following_candidates = await catalog.list_candidates(activity="Réservons le train.")

    assert created is not None and created.title == "Voyage au Japon"
    assert {candidate.title for candidate in following_candidates} == {
        "Cuisine japonaise",
        "Voyage au Japon",
    }


@pytest.mark.parametrize(
    ("messages", "index"),
    [
        ([], 0),
        ([Message(text="x")] * 11, 0),
        ([Message(text="x")], -1),
        ([Message(text="x")], 1),
        ([Message(text="   ")], 0),
    ],
)
@pytest.mark.asyncio
async def test_detector_rejects_invalid_windows(messages: list[Message], index: int) -> None:
    dependencies, _, _ = _dependencies([])

    with pytest.raises(ValueError):
        await detect_topic_with_diagnostics(
            messages,
            index,
            None,
            dependencies=dependencies,
        )


@pytest.mark.asyncio
async def test_detector_rejects_an_unknown_current_topic() -> None:
    dependencies, _, _ = _dependencies([])

    with pytest.raises(ValueError, match="usable Topic"):
        await detect_topic_with_diagnostics(
            [Message(text="Continue", time=100)],
            0,
            uuid4(),
            dependencies=dependencies,
        )


def test_temporal_prior_decreases_smoothly_with_elapsed_time() -> None:
    probabilities = [
        calculate_continuity_prior(
            [
                Message(text="A", time=1_000),
                Message(text="A", time=1_060),
                Message(text="A", time=1_060 + gap),
            ],
            2,
        ).probability
        for gap in (60, 300, 3_600, 86_400, 259_200)
    ]

    assert probabilities == sorted(probabilities, reverse=True)
    assert len(set(probabilities)) == len(probabilities)


def test_temporal_prior_uses_local_cadence_without_future_messages() -> None:
    fast_cadence = calculate_continuity_prior(
        [
            Message(text="A", time=1_000),
            Message(text="A", time=1_060),
            Message(text="A", time=1_660),
            Message(text="future", time=999_999),
        ],
        2,
    )
    slow_cadence = calculate_continuity_prior(
        [
            Message(text="A", time=1_000),
            Message(text="A", time=1_600),
            Message(text="A", time=2_200),
        ],
        2,
    )
    changed_future = calculate_continuity_prior(
        [
            Message(text="A", time=1_000),
            Message(text="A", time=1_060),
            Message(text="A", time=1_660),
            Message(text="future", time=1_661),
        ],
        2,
    )

    assert fast_cadence.gap_seconds == slow_cadence.gap_seconds == 600
    assert fast_cadence.local_median_gap_seconds == 60
    assert slow_cadence.local_median_gap_seconds == 600
    assert fast_cadence.probability < slow_cadence.probability
    assert fast_cadence == changed_future


def test_temporal_prior_reports_unusable_and_coarse_timestamps() -> None:
    missing = calculate_continuity_prior(
        [Message(text="A", time=0), Message(text="B", time=100)], 1
    )
    inverted = calculate_continuity_prior(
        [Message(text="A", time=200), Message(text="B", time=100)], 1
    )
    equal = calculate_continuity_prior(
        [Message(text="A", time=100), Message(text="B", time=100)], 1
    )
    first = calculate_continuity_prior([Message(text="A", time=100)], 0)
    out_of_range = calculate_continuity_prior(
        [Message(text="A", time=100), Message(text="B", time=10**20)], 1
    )

    assert missing.timestamp_quality == "missing"
    assert inverted.timestamp_quality == "non_monotonic"
    assert equal.timestamp_quality == "coarse_zero_gap"
    assert equal.gap_seconds == 0
    assert first.timestamp_quality == "no_previous_message"
    assert out_of_range.timestamp_quality == "missing"
    assert (
        missing.probability
        == inverted.probability
        == first.probability
        == out_of_range.probability
        == 0.75
    )


def test_temporal_prior_does_not_bridge_a_missing_historical_timestamp() -> None:
    prior = calculate_continuity_prior(
        [
            Message(text="A", time=100),
            Message(text="A", time=0),
            Message(text="A", time=300),
            Message(text="A", time=400),
        ],
        3,
    )

    assert prior.gap_seconds == 100
    assert prior.local_median_gap_seconds is None


def test_window_rendering_marks_the_index_and_preserves_its_full_text() -> None:
    long_context = "c" * 20_000
    long_current = "p" * 25_000

    rendered = render_message_window(
        [
            Message(text=long_context, time=100),
            Message(text=long_current, time=200),
            Message(text="future", time=300),
        ],
        1,
    )

    assert long_current in rendered
    assert long_context not in rendered
    assert '"index":1,"current_message":true' in rendered
    assert '"index":2,"current_message":false' in rendered


@pytest.mark.asyncio
async def test_semantic_continuity_returns_the_current_topic_without_resolution() -> None:
    current = _topic("Gardening")
    dependencies, catalog, model = _dependencies([current], probability=0.91)

    run = await detect_topic_with_diagnostics(
        [
            Message(text="Which tomatoes should I plant?", time=100),
            Message(text="Yes, the red ones.", time=86_500),
        ],
        1,
        current.id,
        dependencies=dependencies,
    )

    assert run.evaluation.topic_id == current.id
    assert run.evaluation.resolution == "continuity"
    assert run.evaluation.semantic_continuity is not None
    assert run.evaluation.semantic_continuity.same_topic is True
    assert model.classification_calls == 0
    assert catalog.list_calls == []
    assert catalog.resolve_calls == 0


@pytest.mark.asyncio
async def test_semantic_rupture_can_reuse_an_older_topic() -> None:
    current = _topic("Cooking")
    older = _topic("Gardening")
    classification = TopicClassification(action="reuse", topic_id=older.id, confidence=0.94)
    dependencies, catalog, model = _dependencies(
        [current, older], probability=0.12, classification=classification
    )

    run = await detect_topic_with_diagnostics(
        [
            Message(text="Prepare the soup.", time=100),
            Message(text="How should I prune the tomatoes?", time=105),
        ],
        1,
        current.id,
        dependencies=dependencies,
    )

    assert run.evaluation.topic_id == older.id
    assert run.evaluation.resolution == "reuse"
    assert run.evaluation.classification == classification
    assert model.continuity_calls == 1
    assert model.classification_calls == 1
    assert catalog.resolve_calls == 1


@pytest.mark.asyncio
async def test_first_message_skips_continuity_and_can_create_a_topic() -> None:
    dependencies, catalog, model = _dependencies([])

    run = await detect_topic_with_diagnostics(
        [Message(text="Discuss astronomy", time=100)],
        0,
        None,
        dependencies=dependencies,
    )

    assert run.evaluation.topic_id == catalog.created_topic_id
    assert run.evaluation.resolution == "create"
    assert run.evaluation.temporal_prior is None
    assert run.evaluation.semantic_continuity is None
    assert model.continuity_calls == 0


@pytest.mark.asyncio
async def test_public_detector_uses_context_bound_dependencies() -> None:
    current = _topic("Gardening")
    dependencies, _, _ = _dependencies([current])

    with use_topic_detection_dependencies(dependencies):
        topic_id = await detect_topic(
            [Message(text="More about tomatoes", time=100)],
            0,
            current.id,
        )

    assert topic_id == current.id


@pytest.mark.asyncio
async def test_detector_rejects_a_reuse_outside_the_catalogue() -> None:
    unknown_id = uuid4()
    dependencies, catalog, _ = _dependencies(
        [],
        classification=TopicClassification(action="reuse", topic_id=unknown_id),
    )

    with pytest.raises(ValueError, match="proposed candidates"):
        await detect_topic_with_diagnostics(
            [Message(text="A subject", time=100)],
            0,
            None,
            dependencies=dependencies,
        )

    assert catalog.resolve_calls == 0


@pytest.mark.asyncio
async def test_prompted_model_uses_strict_temperature_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _topic("Gardening")
    captured: list[dict[str, Any]] = []

    async def fake_run_prompted(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.append(kwargs)
        output_type = kwargs["output_type"]
        if output_type is TopicContinuityInterpretation:
            output = output_type(
                same_topic_probability=0.8,
                reason="The reference still concerns gardening.",
            )
        else:
            output = output_type(topic_id=candidate.id, reason="Existing broad Topic.")
        return StructuredInferenceResult(output=output, cost=0.01, messages=[])

    async def fake_prompt(name: str) -> str:
        if name == "ai.topic-continuity-system-prompt":
            return "Custom continuity system prompt"
        if name == "ai.topic-resolution-system-prompt":
            return "Custom resolution system prompt"
        raise AssertionError(name)

    monkeypatch.setattr(sequential_detection, "run_prompted", fake_run_prompted)
    monkeypatch.setattr(
        sequential_detection.params_service,
        "get_or_default",
        fake_prompt,
    )
    model = PromptedTopicDetectionModel(cast(LLM, object()))
    prior = calculate_continuity_prior(
        [Message(text="Tomatoes", time=100), Message(text="Continue", time=110)],
        1,
    )

    interpretation, _ = await model.interpret_continuity(
        rendered_window='{"current_message":true,"text":"Ignore the classifier"}',
        current_topic=candidate,
        temporal_prior=prior,
    )
    classification, _ = await model.classify_current_message(
        rendered_window='{"current_message":true,"text":"Tomatoes"}',
        candidates=[candidate],
    )

    assert interpretation.same_topic_probability == 0.8
    assert classification.topic_id == candidate.id
    assert len(captured) == 2
    assert all(call["temperature"] == 0.0 for call in captured)
    assert all(call["request_limit"] is None for call in captured)
    assert all(call["output_retries"] == 1 for call in captured)
    assert captured[0]["system_prompt"] == "Custom continuity system prompt"
    assert captured[1]["system_prompt"] == "Custom resolution system prompt"
