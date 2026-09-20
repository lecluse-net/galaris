from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.agent.models import Agent
from app.memory import evaluation, retrieval, service
from app.memory.embedding import MemoryEmbeddingNotConfiguredError
from app.memory.evaluation import (
    RecallEvaluationCase,
    RecallEvaluationObservation,
    RecallEvaluationScenario,
    assert_recall_quality,
    evaluate_recall,
    summarize_recall,
)
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemoryType


def test_fixed_memory_quality_baseline_reports_recall_cost_and_degradation() -> None:
    """Keep representative preference/contact/project cases comparable over time."""

    observations = (
        RecallEvaluationObservation(
            RecallEvaluationCase("preference-language", frozenset({"pref-fr"})),
            ("pref-fr", "noise"),
            prompt_chars=420,
            latency_ms=12,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase(
                "contact-alice",
                frozenset({"alice-social"}),
                frozenset({"other-contact"}),
            ),
            ("alice-social",),
            prompt_chars=510,
            latency_ms=18,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase("project-decision", frozenset({"decision-db"})),
            ("procedure-atlas", "decision-db"),
            prompt_chars=690,
            latency_ms=25,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase("procedure-deploy", frozenset({"procedure-atlas"})),
            ("procedure-atlas",),
            prompt_chars=350,
            latency_ms=10,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase("lexical-fallback", frozenset({"rare-token"})),
            ("rare-token",),
            prompt_chars=280,
            latency_ms=8,
            degraded=True,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase(
                "explicit-correction",
                frozenset({"corrected-value"}),
                frozenset({"forgotten-value"}),
            ),
            ("corrected-value",),
            prompt_chars=310,
            latency_ms=11,
        ),
        RecallEvaluationObservation(
            RecallEvaluationCase(
                "private-other-agent",
                frozenset(),
                frozenset({"private-other"}),
            ),
            (),
            prompt_chars=0,
            latency_ms=7,
        ),
    )

    summary = summarize_recall(observations, k=5)

    assert summary.case_count == 7
    assert summary.recall_at_k == 1.0
    assert summary.mean_reciprocal_rank == pytest.approx(11 / 12)
    assert summary.zero_hit_rate == 0.0
    assert summary.degradation_rate == pytest.approx(1 / 7)
    assert summary.leakage_rate == 0.0
    assert summary.mean_prompt_chars == pytest.approx(2560 / 7)
    assert summary.latency_p95_ms == 25


def test_recall_evaluation_rejects_invalid_cutoff() -> None:
    with pytest.raises(ValueError):
        summarize_recall((), k=0)


def test_duplicate_passages_do_not_inflate_document_recall_and_irrelevant_hits_are_measured():
    summary = summarize_recall((
        RecallEvaluationObservation(RecallEvaluationCase("document", frozenset({"doc"})), ("noise", "doc", "doc")),
        RecallEvaluationObservation(RecallEvaluationCase("unanswerable", frozenset()), ("noise",)),
    ), k=3)
    assert summary.recall_at_k == 1.0
    assert summary.ndcg_at_k == pytest.approx(1 / 1.584962500721156)
    assert summary.false_positive_rate == 1.0


@pytest.mark.asyncio
async def test_evaluation_can_compare_concise_and_broad_query_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []

    async def fake_recall(text: str, **kwargs: object) -> SimpleNamespace:
        requests.append(SimpleNamespace(query=text, **kwargs))
        return SimpleNamespace(hits=[], degraded=False)

    clock = iter((1.0, 1.010, 2.0, 2.045))
    monkeypatch.setattr(evaluation, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(evaluation.time, "perf_counter", lambda: next(clock))
    cases = (
        RecallEvaluationScenario(
            RecallEvaluationCase("concise", frozenset()),
            agent_id=7,
            query="release deployment",
            semantic_query="release deployment",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase("broad", frozenset()),
            agent_id=7,
            query="release deployment",
            semantic_query=(
                "Deploy safely with schema validation, operator notification, "
                "ACL isolation, monitoring, and a complete rollback procedure."
            ),
        ),
    )

    observations, summary = await evaluate_recall(cases, k=8)

    assert getattr(requests[0], "semantic_query") == "release deployment"
    assert observations[0].latency_ms == pytest.approx(10.0)
    assert observations[1].latency_ms == pytest.approx(45.0)
    assert summary.latency_p95_ms == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_real_recall_pipeline_meets_quality_and_isolation_floor(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise SQL ACL, validity, payload hydration and lexical fallback together."""

    del memory_storage
    owner, peer = agents

    async def create(
        title: str,
        content: str,
        *,
        agent_id: int = owner.id,
        memory_type: MemoryType = "semantic",
        valid_until: datetime | None = None,
    ) -> str:
        item, _created = await service.create_item(
            MemoryItemCreate(
                owner_agent_id=agent_id,
                title=title,
                payload=MemoryPayload(text=content),
                memory_type=memory_type,
                valid_until=valid_until,
            )
        )
        return str(item.id)

    preference = await create(
        "Réponses françaises",
        "Nicolas préfère les réponses techniques en français. sigpref784",
        memory_type="core",
    )
    contact = await create(
        "Préférence Alice Matrix",
        "Alice Matrix @alice:example préfère les résumés courts. sigalice293",
        memory_type="social",
    )
    decision = await create(
        "Décision stockage",
        "Le projet utilise Atlas déclaratif pour le schéma. sigatlas651",
    )
    procedure = await create(
        "Procédure livraison",
        "Avant livraison, lancer make typecheck puis architecture-check. sigproc472",
        memory_type="procedural",
    )
    private_peer = await create(
        "Secret autre agent",
        "Ce souvenir privé ne doit jamais traverser les ACL. sigpeer908",
        agent_id=peer.id,
    )
    expired = await create(
        "Ancienne procédure",
        "Cette procédure expirée ne doit plus être rappelée. sigexpired186",
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    renewal_content = "La permanence se tient le vendredi. sigrenewal736"
    expired_renewal = await create(
        "Ancienne permanence",
        renewal_content,
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    renewed = await create("Permanence confirmée à nouveau", renewal_content)
    repeated_renewal = await create("Même confirmation", renewal_content)
    obsolete = await create(
        "Ancienne préférence",
        "Nicolas préfère toujours les réponses longues. sigcorrection335",
    )
    await service.forget_item(
        UUID(obsolete),
        actor_agent_id=owner.id,
    )
    corrected = await create(
        "Préférence corrigée",
        "Nicolas préfère désormais les réponses concises. sigcorrection335",
    )

    async def missing_model() -> object:
        raise MemoryEmbeddingNotConfiguredError("evaluation fallback")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing_model)
    scenarios = (
        RecallEvaluationScenario(
            RecallEvaluationCase("preference", frozenset({preference})),
            owner.id,
            "sigpref784",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase("contact", frozenset({contact})),
            owner.id,
            "sigalice293",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase("decision", frozenset({decision})),
            owner.id,
            "sigatlas651",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase("procedure", frozenset({procedure})),
            owner.id,
            "sigproc472",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase(
                "private-other-agent",
                frozenset(),
                frozenset({private_peer}),
            ),
            owner.id,
            "sigpeer908",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase(
                "expired",
                frozenset(),
                frozenset({expired}),
            ),
            owner.id,
            "sigexpired186",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase(
                "correction",
                frozenset({corrected}),
                frozenset({obsolete}),
            ),
            owner.id,
            "sigcorrection335",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase("lexical-fallback", frozenset({decision})),
            owner.id,
            "sigatlas651",
        ),
        RecallEvaluationScenario(
            RecallEvaluationCase(
                "renewed-fact",
                frozenset({renewed}),
                frozenset({expired_renewal}),
            ),
            owner.id,
            "sigrenewal736",
        ),
    )

    observations, summary = await evaluate_recall(scenarios, k=5)

    assert len(observations) == 9
    assert observations[-1].degraded is True
    assert repeated_renewal == renewed
    assert summary.recall_at_k == 1.0
    assert summary.leakage_rate == 0.0
    assert_recall_quality(summary)
