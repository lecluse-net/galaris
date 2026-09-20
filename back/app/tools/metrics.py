"""Privacy-preserving telemetry for rights-filtered tool discovery."""

from __future__ import annotations

import logfire


_search_counter = logfire.metric_counter(
    "tool_discovery_total",
    unit="1",
    description="Rights-filtered tool discovery operations.",
)
_search_latency = logfire.metric_histogram(
    "tool_discovery_duration_seconds",
    unit="s",
    description="End-to-end rights-filtered tool discovery latency.",
)
_catalog_size = logfire.metric_histogram(
    "tool_discovery_catalog_size",
    unit="1",
    description="Authorized candidates considered by tool discovery.",
)
_result_count = logfire.metric_histogram(
    "tool_discovery_result_count",
    unit="1",
    description="Tools returned by one discovery operation.",
)
_planner_prompt_chars = logfire.metric_histogram(
    "tool_discovery_planner_prompt_characters",
    unit="1",
    description="Tool-catalog characters added to a planner prompt.",
)
_catalog_snapshot_counter = logfire.metric_counter(
    "tool_discovery_catalog_snapshot_total",
    unit="1",
    description="Planner catalog snapshots checked again at execution.",
)
_missing_eager_tools = logfire.metric_histogram(
    "tool_discovery_missing_eager_tools",
    unit="1",
    description="Planner-selected tools unavailable in the execution catalog.",
)
_planner_selected_tools = logfire.metric_histogram(
    "tool_discovery_planner_selected_tools",
    unit="1",
    description="Distinct tools selected by one planner result.",
)
_planner_enriched_selection = logfire.metric_histogram(
    "tool_discovery_planner_enriched_selection",
    unit="1",
    description="Selected tools that appeared in the detailed retrieval result.",
)
_planner_unknown_tools = logfire.metric_histogram(
    "tool_discovery_planner_unknown_tools",
    unit="1",
    description="Planner-selected identifiers absent from its catalog snapshot.",
)


def observe_search(
    *,
    surface: str,
    mode: str,
    degraded: bool,
    degradation_reason: str | None,
    catalog_size: int,
    result_count: int,
    latency_seconds: float,
) -> None:
    """Record bounded labels only; objectives and tool identifiers stay private."""

    labels = {
        "surface": surface,
        "mode": mode,
        "degraded": str(degraded).lower(),
        "degradation_reason": degradation_reason or "none",
    }
    _search_counter.add(1, labels)
    _search_latency.record(latency_seconds, labels)
    _catalog_size.record(catalog_size, labels)
    _result_count.record(result_count, labels)


def observe_planner_prompt(*, characters: int) -> None:
    _planner_prompt_chars.record(characters, {})


def observe_catalog_snapshot(
    *,
    matches: bool,
    missing_eager_tools: int,
) -> None:
    labels = {"matches": str(matches).lower()}
    _catalog_snapshot_counter.add(1, labels)
    _missing_eager_tools.record(missing_eager_tools, labels)


def observe_planner_selection(
    *,
    selected_tools: int,
    selected_from_enrichment: int,
    unknown_tools: int,
) -> None:
    _planner_selected_tools.record(selected_tools, {})
    _planner_enriched_selection.record(selected_from_enrichment, {})
    _planner_unknown_tools.record(unknown_tools, {})


__all__ = [
    "observe_catalog_snapshot",
    "observe_planner_prompt",
    "observe_planner_selection",
    "observe_search",
]
