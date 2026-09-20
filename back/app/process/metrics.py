"""Lightweight module metrics without an additional observability dependency."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

import logfire

_exported_counters = {
    name: logfire.metric_counter(name) for name in (
        "process_runs_started_total", "process_runs_failed_total", "process_refresh_failures_total",
        "process_callback_auth_failures_total", "process_callback_duplicates_total", "process_callbacks_total",
        "process_cancel_requests_total", "process_retry_requests_total", "process_inbound_calls_total",
        "process_start_timeouts_total", "process_start_retries_total",
    )
}
_exported_histograms = {
    name: logfire.metric_histogram(name, unit="s") for name in (
        "process_run_duration_seconds", "process_callback_delivery_seconds",
        "process_start_job_lag_seconds", "process_start_latency_seconds",
    )
}

_lock = Lock()
_counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
def _values() -> list[float]:
    return []


_histograms: defaultdict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(_values)


def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted(labels.items()))


def increment(name: str, value: float = 1.0, **labels: str) -> None:
    if counter := _exported_counters.get(name):
        counter.add(value, labels)
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, **labels: str) -> None:
    if histogram := _exported_histograms.get(name):
        histogram.record(value, labels)
    with _lock:
        values = _histograms[_key(name, labels)]
        values.append(float(value))
        if len(values) > 10_000:
            del values[: len(values) - 10_000]


def snapshot() -> dict[str, list[dict[str, Any]]]:
    with _lock:
        counters = [
            {"name": name, "labels": dict(labels), "value": value}
            for (name, labels), value in sorted(_counters.items())
        ]
        histograms: list[dict[str, Any]] = []
        for (name, labels), values in sorted(_histograms.items()):
            histograms.append({
                "name": name,
                "labels": dict(labels),
                "count": len(values),
                "sum": sum(values),
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            })
    return {"counters": counters, "histograms": histograms}
