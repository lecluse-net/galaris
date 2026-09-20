"""Deterministic quality metrics for governed-memory recall evaluations."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from statistics import fmean
from typing import Sequence

from .facade import search_memory_detailed
from .schemas import MemoryType


@dataclass(frozen=True, slots=True)
class RecallEvaluationCase:
    """One fixed query with one or more acceptable relevant memory identifiers."""

    case_id: str
    expected_ids: frozenset[str]
    forbidden_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RecallEvaluationObservation:
    """Observed bounded ranking plus operational recall signals."""

    case: RecallEvaluationCase
    returned_ids: tuple[str, ...]
    prompt_chars: int = 0
    latency_ms: float = 0.0
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class RecallEvaluationScenario:
    """One executable recall case against the actual governed retrieval path."""

    case: RecallEvaluationCase
    agent_id: int
    query: str
    semantic_query: str | None = None
    memory_types: tuple[MemoryType, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallEvaluationSummary:
    case_count: int
    recall_at_k: float
    precision_at_k: float
    mean_reciprocal_rank: float
    zero_hit_rate: float
    degradation_rate: float
    leakage_rate: float
    mean_prompt_chars: float
    latency_p95_ms: float
    ndcg_at_k: float = 0.0
    false_positive_rate: float = 0.0


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def summarize_recall(
    observations: tuple[RecallEvaluationObservation, ...],
    *,
    k: int = 5,
) -> RecallEvaluationSummary:
    """Aggregate stable offline metrics without invoking an LLM."""

    if k < 1:
        raise ValueError("k must be positive.")
    if not observations:
        return RecallEvaluationSummary(
            case_count=0,
            recall_at_k=0.0,
            precision_at_k=0.0,
            mean_reciprocal_rank=0.0,
            zero_hit_rate=0.0,
            degradation_rate=0.0,
            leakage_rate=0.0,
            mean_prompt_chars=0.0,
            latency_p95_ms=0.0,
        )

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    zero_hits = 0
    positive_cases = 0
    negative_cases = false_positives = 0
    ndcgs: list[float] = []
    leaks = 0
    for observation in observations:
        ranked = observation.returned_ids[:k]
        relevant = observation.case.expected_ids
        matches = len(set(ranked) & relevant)
        recalls.append(matches / len(relevant) if relevant else 1.0)
        precisions.append(matches / len(ranked) if ranked else 0.0)
        first_rank = next(
            (
                rank
                for rank, item_id in enumerate(ranked, start=1)
                if item_id in relevant
            ),
            None,
        )
        if relevant:
            positive_cases += 1
            reciprocal_ranks.append(
                0.0 if first_rank is None else 1.0 / first_rank
            )
            zero_hits += int(first_rank is None)
            seen: set[str] = set()
            dcg = 0.0
            for rank, item_id in enumerate(ranked, start=1):
                if item_id in relevant and item_id not in seen:
                    dcg += 1 / math.log2(rank + 1)
                seen.add(item_id)
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
            ndcgs.append(dcg / ideal)
        else:
            negative_cases += 1
            false_positives += bool(ranked)
        leaks += int(
            any(
                item_id in observation.case.forbidden_ids
                for item_id in ranked
            )
        )

    count = len(observations)
    return RecallEvaluationSummary(
        case_count=count,
        recall_at_k=fmean(recalls),
        precision_at_k=fmean(precisions),
        mean_reciprocal_rank=(
            fmean(reciprocal_ranks) if reciprocal_ranks else 0.0
        ),
        zero_hit_rate=(
            zero_hits / positive_cases if positive_cases else 0.0
        ),
        degradation_rate=(
            sum(observation.degraded for observation in observations) / count
        ),
        leakage_rate=leaks / count,
        ndcg_at_k=fmean(ndcgs) if ndcgs else 0.0,
        false_positive_rate=false_positives / negative_cases if negative_cases else 0.0,
        mean_prompt_chars=fmean(
            observation.prompt_chars for observation in observations
        ),
        latency_p95_ms=_nearest_rank_p95(
            [observation.latency_ms for observation in observations]
        ),
    )


async def evaluate_recall(
    scenarios: Sequence[RecallEvaluationScenario],
    *,
    k: int = 5,
) -> tuple[
    tuple[RecallEvaluationObservation, ...],
    RecallEvaluationSummary,
]:
    """Execute the real recall pipeline and aggregate its bounded results."""

    observations: list[RecallEvaluationObservation] = []
    for scenario in scenarios:
        started_at = time.perf_counter()
        result = await search_memory_detailed(
            scenario.query,
            agent_id=scenario.agent_id,
            semantic_query=scenario.semantic_query,
            limit=k,
            memory_types=scenario.memory_types,
            record_llm_access=False,
            telemetry_kind="evaluation",
        )
        observations.append(
            RecallEvaluationObservation(
                case=scenario.case,
                returned_ids=tuple(str(hit.item.id) for hit in result.hits),
                prompt_chars=sum(len(hit.excerpt) for hit in result.hits),
                latency_ms=max(
                    0.0,
                    (time.perf_counter() - started_at) * 1_000,
                ),
                degraded=result.degraded,
            )
        )
    frozen = tuple(observations)
    return frozen, summarize_recall(frozen, k=k)


def assert_recall_quality(
    summary: RecallEvaluationSummary,
    *,
    minimum_recall_at_k: float = 0.9,
    maximum_leakage_rate: float = 0.0,
) -> None:
    """Fail a reproducible evaluation when the accepted quality floor regresses."""

    if summary.case_count < 1:
        raise AssertionError("Recall evaluation must contain at least one case.")
    if summary.recall_at_k < minimum_recall_at_k:
        raise AssertionError(
            "Recall quality regression: "
            f"{summary.recall_at_k:.3f} < {minimum_recall_at_k:.3f}."
        )
    if summary.leakage_rate > maximum_leakage_rate:
        raise AssertionError(
            "Recall isolation regression: "
            f"{summary.leakage_rate:.3f} > {maximum_leakage_rate:.3f}."
        )


__all__ = [
    "RecallEvaluationCase",
    "RecallEvaluationObservation",
    "RecallEvaluationScenario",
    "RecallEvaluationSummary",
    "assert_recall_quality",
    "evaluate_recall",
    "summarize_recall",
]
