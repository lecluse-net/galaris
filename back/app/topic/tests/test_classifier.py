from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.llm import model_usages
from app.llm.structured_service import StructuredInferenceResult
from app.topic import TopicCandidate
from app.topic import classifier


@pytest.fixture(autouse=True)
def default_topic_system_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(_name: str) -> None:
        return None

    monkeypatch.setattr(classifier.params_service, "get", fake_get)


def test_topic_prompt_does_not_replace_identity_with_a_generic_persona() -> None:
    prompt = " ".join(classifier.TOPIC_CLASSIFICATION_SYSTEM_PROMPT.split())

    assert "never replace it with a demographic" in prompt
    assert '"Medical follow-up"' in prompt
    assert '"Medical follow-up for a child with asthma"' in prompt
    assert "identity and asthma remain private activity or memory details" in prompt


@pytest.mark.asyncio
async def test_topic_classifier_uses_the_dream_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    resolved_params: list[str] = []

    async def fake_resolve_llm(model_field: str, agent_id: int | None) -> object:
        assert agent_id is None
        resolved_params.append(model_field)
        return object()

    async def fake_run_prompted(
        **kwargs: Any,
    ) -> StructuredInferenceResult[Any]:
        captured.append(kwargs)
        output_type = kwargs["output_type"]
        return StructuredInferenceResult(
            output=output_type(title="Gardening"),
            cost=0.0,
            messages=[],
        )

    monkeypatch.setattr(
        classifier.llm_service,
        "get_profile_llm_for_agent_id",
        fake_resolve_llm,
    )
    monkeypatch.setattr(classifier, "run_prompted", fake_run_prompted)

    await classifier.classify(
        activity="Prepare the balcony garden.",
        candidates=[],
        task_id=None,
        agent_id=None,
        language="en",
    )

    assert len(captured) == 1
    assert resolved_params == [model_usages.DREAM]
    assert captured[0]["request_limit"] is None


@pytest.mark.asyncio
async def test_topic_classifier_reuses_before_considering_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = TopicCandidate(
        id=uuid4(),
        title="Urban gardening",
        description="Growing plants in small city spaces.",
        keywords=["garden", "balcony"],
        activity_count=12,
    )
    captured: list[dict[str, Any]] = []

    async def fake_resolve_llm(_model_field: str, _agent_id: int | None) -> object:
        return object()

    async def fake_run_prompted(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.append(kwargs)
        output_type = kwargs["output_type"]
        return StructuredInferenceResult(
            output=output_type(
                topic_id=candidate.id,
                confidence=0.93,
                reason="The durable theme is already covered.",
            ),
            cost=0.01,
            messages=[],
        )

    monkeypatch.setattr(
        classifier.llm_service,
        "get_profile_llm_for_agent_id",
        fake_resolve_llm,
    )
    monkeypatch.setattr(classifier, "run_prompted", fake_run_prompted)

    decision, cost = await classifier.classify(
        activity="Prepare vegetables for a balcony garden.",
        candidates=[candidate],
        task_id=None,
        agent_id=None,
        language="en",
    )

    assert len(captured) == 1
    assert captured[0]["output_type"].__name__ == "_TopicReuseDecision"
    assert decision.action == "reuse"
    assert decision.topic_id == candidate.id
    assert cost == 0.01


@pytest.mark.asyncio
async def test_topic_classifier_creation_prompt_requires_abstract_subjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = TopicCandidate(
        id=uuid4(),
        title="Cooking",
        description="Food preparation and culinary practices.",
        keywords=["food", "recipes"],
    )
    captured: list[dict[str, Any]] = []

    async def fake_resolve_llm(_model_field: str, _agent_id: int | None) -> object:
        return object()

    async def fake_run_prompted(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.append(kwargs)
        output_type = kwargs["output_type"]
        if output_type.__name__ == "_TopicReuseDecision":
            output = output_type(topic_id=None)
        else:
            output = output_type(
                title="Gardening",
                description="Cultivating and caring for plants.",
                keywords=["plants", "cultivation"],
            )
        return StructuredInferenceResult(output=output, cost=0.01, messages=[])

    monkeypatch.setattr(
        classifier.llm_service,
        "get_profile_llm_for_agent_id",
        fake_resolve_llm,
    )
    monkeypatch.setattr(classifier, "run_prompted", fake_run_prompted)

    decision, cost = await classifier.classify(
        activity="Choose tomatoes for a north-facing balcony.",
        candidates=[candidate],
        task_id=None,
        agent_id=None,
        language="en",
    )

    assert len(captured) == 2
    assert "broader subject" in captured[0]["prompt"]
    assert "one or two category levels upward" in captured[1]["prompt"]
    assert "at least three varied future activities" in captured[1]["prompt"]
    assert "North-facing balcony tomatoes" in captured[1]["system_prompt"]
    assert decision.action == "create"
    assert decision.title == "Gardening"
    assert cost == 0.02


@pytest.mark.asyncio
async def test_topic_classifier_appends_configured_system_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_resolve_llm(_model_field: str, _agent_id: int | None) -> object:
        return object()

    async def fake_get(name: str) -> str:
        assert name == "ai.topic-classification-system-prompt"
        return "Prefer cultural domains over individual works."

    async def fake_run_prompted(**kwargs: Any) -> StructuredInferenceResult[Any]:
        captured.update(kwargs)
        output_type = kwargs["output_type"]
        return StructuredInferenceResult(
            output=output_type(title="Literature"),
            cost=0.01,
            messages=[],
        )

    monkeypatch.setattr(
        classifier.llm_service,
        "get_profile_llm_for_agent_id",
        fake_resolve_llm,
    )
    monkeypatch.setattr(classifier.params_service, "get", fake_get)
    monkeypatch.setattr(classifier, "run_prompted", fake_run_prompted)

    await classifier.classify(
        activity="Read and review one historical novel.",
        candidates=[],
        task_id=None,
        agent_id=None,
        language="en",
    )

    system_prompt = str(captured["system_prompt"])
    assert classifier.TOPIC_CLASSIFICATION_SYSTEM_PROMPT in system_prompt
    assert "Instance-specific topic-classification instructions:" in system_prompt
    assert "Prefer cultural domains over individual works." in system_prompt
    assert system_prompt.endswith(
        "Keep proper nouns, identifiers, code, and exact technical terms unchanged."
    )
