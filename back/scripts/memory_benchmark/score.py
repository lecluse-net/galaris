"""Facet-based rank scoring and full-list leakage checks at multiple stages."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from statistics import mean

from .generate import Corpus, Memory
from .io import string, strings
from .validate import prohibited, validate


STAGES = ("candidates", "retrieved", "injected")


@dataclass(frozen=True)
class Observation:
    query_id: str
    ranks: dict[str, tuple[str, ...]]
    response_mode: str | None
    latency_ms: float | None
    context_tokens: float | None


@dataclass(frozen=True)
class Result:
    query_id: str
    stage: str
    domain: str
    profile: str
    family: str
    language: str
    split: str
    surface: str
    observed: bool
    answerable: bool
    recall: float | None
    precision: float
    mrr: float | None
    complete_mrr: float | None
    ndcg: float | None
    complete: bool | None
    empty: bool
    forbidden_ids: tuple[str, ...]
    violation_reasons: dict[str, int]
    duplicate_count: int
    response_mode_correct: bool | None
    latency_ms: float | None
    context_tokens: float | None


def _nonnegative(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Measurements must be finite, nonnegative numbers")
    return float(value)


def observations(records: list[dict[str, object]]) -> tuple[Observation, ...]:
    result: list[Observation] = []
    for d in records:
        allowed = {"query_id", *STAGES, "response_mode", "latency_ms", "context_tokens"}
        if set(d) - allowed:
            raise ValueError("Unknown observation fields")
        ranks = {stage: strings(d[stage]) for stage in STAGES if stage in d}
        if not ranks:
            raise ValueError("Supply at least one ranked stage per observation")
        mode = d.get("response_mode")
        if mode is not None and mode not in ("answer", "clarify", "unknown", "unavailable"):
            raise ValueError("Unsupported response mode")
        result.append(Observation(string(d["query_id"]), ranks, None if mode is None else string(mode),
                                  _nonnegative(d.get("latency_ms")), _nonnegative(d.get("context_tokens"))))
    return tuple(result)


def _aggregate(rows: list[Result]) -> dict[str, object]:
    def avg(attribute: str) -> float | None:
        values: list[object] = [getattr(row, attribute) for row in rows]
        numbers = [float(v) for v in values if isinstance(v, (float, int, bool))]
        return mean(numbers) if numbers else None

    violations: Counter[str] = Counter()
    for row in rows:
        violations.update(row.violation_reasons)
    return {
        "queries": len(rows), "observed": sum(r.observed for r in rows),
        "coverage": avg("observed"), "answerable_queries": sum(r.answerable for r in rows),
        "facet_recall_at_k": avg("recall"), "precision_at_k": avg("precision"),
        "mrr_at_k": avg("mrr"), "complete_mrr_at_k": avg("complete_mrr"),
        "ndcg_at_k": avg("ndcg"), "complete_recall_at_k": avg("complete"),
        "queries_with_forbidden_ids": sum(bool(r.forbidden_ids) for r in rows),
        "forbidden_id_count_full_list": sum(len(r.forbidden_ids) for r in rows),
        "violation_reasons": dict(violations), "duplicate_id_count": sum(r.duplicate_count for r in rows),
        "no_fact_queries": sum(not r.answerable for r in rows),
        "nonempty_no_fact_queries": sum(not r.answerable and not r.empty for r in rows),
        "response_mode_evaluated": sum(r.response_mode_correct is not None for r in rows),
        "response_mode_accuracy": avg("response_mode_correct"),
        "mean_latency_ms_observed": avg("latency_ms"), "mean_context_tokens_observed": avg("context_tokens"),
    }


def score(corpus: Corpus, observed: tuple[Observation, ...], *, k: int = 8,
          splits: tuple[str, ...] = (), stages: tuple[str, ...] = ()) -> tuple[dict[str, object], tuple[Result, ...]]:
    validate(corpus)
    if k < 1:
        raise ValueError("k must be positive")
    selected = tuple(q for q in corpus.queries if not splits or q.split in splits)
    if not selected or set(splits) - {q.split for q in corpus.queries}:
        raise ValueError("Unknown/empty evaluation partition")
    selected_stages = stages or tuple(stage for stage in STAGES if any(stage in o.ranks for o in observed))
    if not selected_stages or set(selected_stages) - set(STAGES) or len(set(selected_stages)) != len(selected_stages):
        raise ValueError("Supply valid, distinct stages (also for an empty observation file)")
    by_query = {o.query_id: o for o in observed}
    if len(by_query) != len(observed) or set(by_query) - {q.id for q in corpus.queries}:
        raise ValueError("Duplicate or unknown observation query IDs")
    memories: dict[str, Memory] = {m.id: m for m in corpus.memories}
    answers = {a.query_id: a for a in corpus.answers}
    results: list[Result] = []
    for q in selected:
        a, o = answers[q.id], by_query.get(q.id)
        groups = [set(g.any_of) for g in a.required]
        useful = set(a.optional_ids) | {i for group in groups for i in group}
        for stage in selected_stages:
            present = o is not None and stage in o.ranks
            ranks = o.ranks.get(stage, ()) if o is not None else ()
            top = ranks[:k]  # Do not deduplicate before ranking: duplicates consume real slots.
            found: set[int] = set()
            dcg = 0.0
            first_rank = complete_rank = 0
            credited_optional: set[str] = set()
            for rank, identity in enumerate(top, 1):
                newly_found = {gi for gi, group in enumerate(groups) if identity in group} - found
                gain = float(len(newly_found))
                if newly_found and not first_rank:
                    first_rank = rank
                found.update(newly_found)
                if groups and len(found) == len(groups) and not complete_rank:
                    complete_rank = rank
                if identity in a.optional_ids and identity not in credited_optional:
                    gain += 0.25
                    credited_optional.add(identity)
                dcg += gain / math.log2(rank + 1)
            ideal_gains = ([1.0] * len(groups) + [0.25] * len(set(a.optional_ids)))[:k]
            ideal = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, 1))
            banned: dict[str, str] = {}
            for identity in dict.fromkeys(ranks):
                reason = a.forbidden.get(identity)
                if identity not in memories:
                    reason = "unknown_id"
                elif reason is None:
                    reason = prohibited(memories[identity], q)
                if reason is not None:
                    banned[identity] = reason
            answerable = bool(groups)
            results.append(Result(
                q.id, stage, q.domain, q.profile, q.family, q.language, q.split, q.surface, present, answerable,
                len(found) / len(groups) if groups else None,
                len(set(top) & useful) / len(top) if top else 0.0,
                (1.0 / first_rank if first_rank else 0.0) if answerable else None,
                (1.0 / complete_rank if complete_rank else 0.0) if answerable else None,
                dcg / ideal if answerable and ideal else None,
                len(found) == len(groups) if answerable else None, not ranks,
                tuple(banned), dict(Counter(banned.values())), len(ranks) - len(set(ranks)),
                o.response_mode == a.response_mode if present and o is not None and o.response_mode is not None else None,
                o.latency_ms if present and o is not None else None,
                o.context_tokens if present and o is not None else None))
    stage_reports: dict[str, object] = {}
    for stage in selected_stages:
        rows = [r for r in results if r.stage == stage]
        slices: dict[str, object] = {}
        for dimension in ("domain", "profile", "family", "language", "split", "surface"):
            buckets: dict[str, list[Result]] = {}
            for row in rows:
                label = string(getattr(row, dimension))
                buckets.setdefault(label, []).append(row)
            slices[dimension] = {label: _aggregate(bucket) for label, bucket in sorted(buckets.items())}
        stage_reports[stage] = {"overall": _aggregate(rows), "slices": slices}
    return {"k": k, "query_count": len(selected), "observation_count": len(observed),
            "stages": stage_reports, "limitations": [
                "All selected queries enter denominators; missing observations score as misses.",
                "No-fact queries are excluded from recall/rank denominators, never treated as perfect recall.",
                "Forbidden IDs are checked throughout supplied lists, including beyond k.",
                "Response mode is optional; ID recall does not grade generated text or quoted instruction safety.",
            ]}, tuple(results)
