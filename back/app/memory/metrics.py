"""Privacy-preserving operational metrics for governed-memory recall."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

import logfire


_lock = Lock()
_counters: defaultdict[
    tuple[str, tuple[tuple[str, str], ...]],
    float,
] = defaultdict(float)


def _values() -> list[float]:
    return []


_histograms: defaultdict[
    tuple[str, tuple[tuple[str, str], ...]],
    list[float],
] = defaultdict(_values)

_recall_counter = logfire.metric_counter(
    "memory_recall_total",
    unit="1",
    description="Governed-memory recall operations by kind and outcome.",
)
_recall_latency = logfire.metric_histogram(
    "memory_recall_duration_seconds",
    unit="s",
    description="End-to-end governed-memory recall latency.",
)
_recall_results = logfire.metric_histogram(
    "memory_recall_result_count",
    unit="1",
    description="Number of governed memories returned by one recall.",
)
_prompt_chars = logfire.metric_histogram(
    "memory_context_prompt_characters",
    unit="1",
    description="Characters of governed memory presented in an agent context.",
)


def _key(
    name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted(labels.items()))


def increment(name: str, value: float = 1.0, **labels: str) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, **labels: str) -> None:
    with _lock:
        values = _histograms[_key(name, labels)]
        values.append(float(value))
        if len(values) > 10_000:
            del values[: len(values) - 10_000]


def observe_recall(
    *,
    kind: str,
    mode: str,
    degraded: bool,
    degradation_reason: str | None,
    result_count: int,
    latency_seconds: float,
) -> None:
    """Record bounded labels only; queries and memory identifiers stay private."""

    labels = {
        "kind": kind,
        "mode": mode,
        "degraded": str(degraded).lower(),
        "degradation_reason": degradation_reason or "none",
    }
    increment(
        "memory_recall_total",
        kind=kind,
        mode=mode,
        degraded=labels["degraded"],
        degradation_reason=labels["degradation_reason"],
    )
    observe(
        "memory_recall_duration_seconds",
        latency_seconds,
        kind=kind,
        mode=mode,
        degraded=labels["degraded"],
        degradation_reason=labels["degradation_reason"],
    )
    observe(
        "memory_recall_result_count",
        float(result_count),
        kind=kind,
        mode=mode,
        degraded=labels["degraded"],
        degradation_reason=labels["degradation_reason"],
    )
    _recall_counter.add(1, labels)
    _recall_latency.record(latency_seconds, labels)
    _recall_results.record(result_count, labels)


def observe_context(*, item_count: int, prompt_chars: int, truncated: bool) -> None:
    labels = {"truncated": str(truncated).lower()}
    increment("memory_context_total", truncated=labels["truncated"])
    observe(
        "memory_context_item_count",
        float(item_count),
        truncated=labels["truncated"],
    )
    observe(
        "memory_context_prompt_characters",
        float(prompt_chars),
        truncated=labels["truncated"],
    )
    _prompt_chars.record(prompt_chars, labels)


def snapshot() -> dict[str, list[dict[str, Any]]]:
    """Return the process-local view used by the admin diagnostics endpoint."""

    with _lock:
        counters = [
            {"name": name, "labels": dict(labels), "value": value}
            for (name, labels), value in sorted(_counters.items())
        ]
        histograms: list[dict[str, Any]] = []
        for (name, labels), values in sorted(_histograms.items()):
            ordered = sorted(values)
            p95_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
            histograms.append(
                {
                    "name": name,
                    "labels": dict(labels),
                    "count": len(values),
                    "sum": sum(values),
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                    "p95": ordered[p95_index] if ordered else None,
                }
            )
    return {"counters": counters, "histograms": histograms}


def reset() -> None:
    """Clear only the local mirror, primarily for deterministic tests."""

    with _lock:
        _counters.clear()
        _histograms.clear()


__all__ = [
    "increment",
    "observe",
    "observe_context",
    "observe_recall",
    "reset",
    "snapshot",
]
