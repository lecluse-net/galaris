from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.dream.contracts import (
    DreamClaim,
    ExperienceLesson,
    TaskOutcomeEvidence,
    TaskOutcomeEvidenceItem,
    TaskOutcomeReflection,
)
from app.dream.mechanisms import task_outcome_reflection
from app.dream.outcome_evidence import significance_reason


def _evidence(*observations: TaskOutcomeEvidenceItem, status: str = "SUCCESS") -> TaskOutcomeEvidence:
    return TaskOutcomeEvidence(
        task_id=uuid4(),
        owner_agent_id=7,
        terminal_status=status,
        observations=list(observations),
        fingerprint="a" * 64,
    )


def test_significance_is_deterministic_and_rejects_unverified_success() -> None:
    included, reason = significance_reason(_evidence())
    assert included is False
    assert reason == "unverified_success"

    included, reason = significance_reason(
        _evidence(
            TaskOutcomeEvidenceItem(
                reference="attempt:1",
                kind="attempt",
                status="ERROR",
                name="EXEC:ToolError",
            ),
            TaskOutcomeEvidenceItem(
                reference="attempt:2",
                kind="attempt",
                status="SUCCESS",
                name="EXEC",
            ),
        )
    )
    assert included is True
    assert reason == "recovered_after_failure"


def test_reflection_rejects_unknown_evidence_references() -> None:
    evidence = _evidence(
        TaskOutcomeEvidenceItem(
            reference="tool:0:verify",
            kind="tool_result",
            status="success",
            name="verify",
            detail="verified",
        )
    )
    invalid = ExperienceLesson(
        outcome_kind="verified_success",
        lesson_kind="procedure",
        situation="A deployment needs verification.",
        applicability="Deployments using this tool.",
        recommended_action="Run the verification tool.",
        observed_result="The deployment was verified.",
        evidence_refs=["tool:99:invented"],
        confidence=0.9,
    )
    assert task_outcome_reflection._validated_lessons(  # pyright: ignore[reportPrivateUsage]
        TaskOutcomeReflection(lessons=[invalid]), evidence
    ) == []


def test_experience_memory_uses_source_language_for_deterministic_labels() -> None:
    lesson = ExperienceLesson(
        outcome_kind="verified_success",
        lesson_kind="procedure",
        situation="Un déploiement doit être vérifié.",
        applicability="Déploiements avec une sonde de santé.",
        recommended_action="Exécuter la sonde après le déploiement.",
        avoid_action="Ignorer la vérification.",
        observed_result="La sonde a confirmé le déploiement.",
        evidence_refs=["tool:0:health"],
        confidence=0.9,
    )

    extraction = task_outcome_reflection._extraction(  # pyright: ignore[reportPrivateUsage]
        [lesson],
        "verified_tool_success",
        language="fr",
    )

    memory = extraction.memories[0]
    assert memory.title.startswith("Expérience :")
    assert "Recommandation" in memory.content
    assert "Action à éviter" in memory.content
    assert "Résultat observé" in memory.content


@pytest.mark.asyncio
async def test_apply_establishes_a_fresh_database_session(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = False

    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        nonlocal entered
        entered = True
        yield

    apply_prepared = AsyncMock(return_value=2)
    monkeypatch.setattr(task_outcome_reflection, "get_db_session", session)
    monkeypatch.setattr(
        task_outcome_reflection.task_outcome_reflection_mechanism,
        "_apply",
        apply_prepared,
    )
    claim = DreamClaim(
        receipt_id=uuid4(),
        lease_token=uuid4(),
        subject_kind="task_outcome",
        subject_id=f"{uuid4()}:fingerprint",
        attempts=1,
        prepared_payload={},
    )

    result = await task_outcome_reflection.task_outcome_reflection_mechanism.apply(claim, {})

    assert entered is True
    assert result == 2
    apply_prepared.assert_awaited_once_with(claim, {})
