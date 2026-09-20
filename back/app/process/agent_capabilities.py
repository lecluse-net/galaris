"""Rights-aware business-process advertising for agent prompts."""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from typing import Any

from loguru import logger

from app.llm import rank_texts_by_semantic_similarity


_PROCESS_DISCOVERY_TOOLS = frozenset({"process_list", "process_get"})
_DESCRIPTION_MAX_CHARS = 500
_PROCESS_CATALOG_LIMIT = 10
_RELEVANCE_QUERY_MAX_CHARS = 4_000
_PROCESS_RELEVANCE_TEXT_MAX_CHARS = 1_000
_SEARCH_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _compact_text(value: object, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _json_catalog_entry(process: dict[str, Any]) -> str:
    entry = {
        "workflow_id": _compact_text(process.get("workflow_id"), max_chars=255),
        "label": _compact_text(process.get("label"), max_chars=255),
        "description": _compact_text(
            process.get("description"),
            max_chars=_DESCRIPTION_MAX_CHARS,
        ),
    }
    # Process metadata is administrator-provided reference data. Escaping angle brackets keeps
    # it from breaking the XML-like prompt section that contains this JSON line.
    return json.dumps(entry, ensure_ascii=False).replace("<", "\\u003c").replace(
        ">", "\\u003e"
    )


def _relevance_text(process: dict[str, Any]) -> str:
    return _compact_text(
        "\n".join(
            value
            for value in (
                str(process.get("workflow_id") or "").strip(),
                str(process.get("label") or "").strip(),
                str(process.get("description") or "").strip(),
            )
            if value
        ),
        max_chars=_PROCESS_RELEVANCE_TEXT_MAX_CHARS,
    ) or "[unnamed process]"


def _lexical_relevance(
    query: str,
    process: dict[str, Any],
) -> tuple[int, int, int, int]:
    normalized_query = " ".join(query.casefold().split())
    workflow_id = " ".join(
        str(process.get("workflow_id") or "").casefold().split()
    )
    label = " ".join(str(process.get("label") or "").casefold().split())
    description = " ".join(
        str(process.get("description") or "").casefold().split()
    )
    query_tokens = set(_SEARCH_TOKEN_RE.findall(normalized_query))
    workflow_tokens = set(_SEARCH_TOKEN_RE.findall(workflow_id))
    label_tokens = set(_SEARCH_TOKEN_RE.findall(label))
    description_tokens = set(_SEARCH_TOKEN_RE.findall(description))
    return (
        int(
            bool(
                normalized_query
                and normalized_query in f"{workflow_id} {label} {description}"
            )
        ),
        len(query_tokens & workflow_tokens),
        len(query_tokens & label_tokens),
        len(query_tokens & description_tokens),
    )


async def select_agent_processes(
    processes: list[dict[str, Any]],
    *,
    relevance_query: str = "",
) -> list[dict[str, Any]]:
    """Keep every small catalog, otherwise return ten candidates without a score threshold."""

    if len(processes) <= _PROCESS_CATALOG_LIMIT:
        return processes
    normalized_query = _compact_text(
        relevance_query,
        max_chars=_RELEVANCE_QUERY_MAX_CHARS,
    )
    if normalized_query:
        try:
            semantic_order = await rank_texts_by_semantic_similarity(
                normalized_query,
                [_relevance_text(process) for process in processes],
            )
        except Exception:
            logger.exception(
                "Semantic Process ranking failed; using deterministic lexical fallback"
            )
        else:
            if semantic_order is not None and len(semantic_order) == len(processes):
                return [
                    processes[index]
                    for index in semantic_order[:_PROCESS_CATALOG_LIMIT]
                ]
    ranked = sorted(
        enumerate(processes),
        key=lambda item: (
            tuple(-value for value in _lexical_relevance(normalized_query, item[1])),
            str(item[1].get("label") or "").casefold(),
            str(item[1].get("workflow_id") or "").casefold(),
            item[0],
        ),
    )
    return [process for _index, process in ranked[:_PROCESS_CATALOG_LIMIT]]


def render_agent_process_advertisement(
    processes: list[dict[str, Any]],
    *,
    launch_tool_name: str = "process_start",
    total_assigned: int | None = None,
    include_execution_guidance: bool = True,
) -> str:
    """Render a compact catalog whose entries remain data, not prompt instructions."""
    lines = [
        "## Business processes available to you",
        "",
        "The catalog below contains only workflows assigned to you.",
    ]
    if not processes:
        lines.extend(
            [
                "",
                "No business process is currently assigned to you. Do not invent a workflow ID.",
            ]
        )
        return "\n".join(lines)

    if include_execution_guidance:
        lines.extend(
            [
                "Inspect a possible match with `process_get`, then call "
                f"`{launch_tool_name}`. Use `process_list` to refresh this catalog after an "
                "authorization change or when a matching Process may be outside this projection. "
                "Never invent a workflow ID.",
                "",
            ]
        )
    if total_assigned is not None and total_assigned > len(processes):
        lines.extend(
            [
                f"Showing the {len(processes)} Processes most relevant to the current request "
                f"out of {total_assigned} assigned Processes; no relevance threshold was used.",
                "",
            ]
        )
    lines.extend(f"- {_json_catalog_entry(process)}" for process in processes)
    return "\n".join(lines)


async def build_agent_process_advertisement(
    agent_id: int,
    available_tool_names: Collection[str],
    *,
    launch_tool_name: str = "process_start",
    relevance_query: str = "",
    include_execution_guidance: bool = True,
) -> str:
    """Advertise assigned processes only when discovery, inspection, and launch are authorized."""
    required_tools = _PROCESS_DISCOVERY_TOOLS | {launch_tool_name}
    if not required_tools.issubset(available_tool_names):
        return ""

    from . import process_service

    processes = await process_service.list_for_agent(agent_id)
    selected = await select_agent_processes(
        processes,
        relevance_query=relevance_query,
    )
    return render_agent_process_advertisement(
        selected,
        launch_tool_name=launch_tool_name,
        total_assigned=len(processes),
        include_execution_guidance=include_execution_guidance,
    )


__all__ = [
    "build_agent_process_advertisement",
    "render_agent_process_advertisement",
    "select_agent_processes",
]
