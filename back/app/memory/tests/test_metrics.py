from __future__ import annotations

from app.memory import metrics


def test_memory_metrics_snapshot_contains_only_bounded_operational_labels() -> None:
    metrics.reset()
    metrics.observe_recall(
        kind="context",
        mode="lexical",
        degraded=True,
        degradation_reason="embedding_not_configured",
        result_count=3,
        latency_seconds=0.025,
    )
    metrics.observe_context(item_count=3, prompt_chars=850, truncated=False)

    snapshot = metrics.snapshot()

    recall = next(
        row
        for row in snapshot["counters"]
        if row["name"] == "memory_recall_total"
    )
    assert recall["value"] == 1
    assert recall["labels"] == {
        "degradation_reason": "embedding_not_configured",
        "degraded": "true",
        "kind": "context",
        "mode": "lexical",
    }
    serialized = repr(snapshot)
    assert "query" not in serialized
    assert "memory_id" not in serialized
    prompt = next(
        row
        for row in snapshot["histograms"]
        if row["name"] == "memory_context_prompt_characters"
    )
    assert prompt["p95"] == 850

    metrics.reset()
