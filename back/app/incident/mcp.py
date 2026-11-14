"""Read-only failure journal tools under the live Galaris administration scope."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from app.tools.facade import administration_scope
from app.tools import McpToolContext, mcp_tool

from . import service
from .serialization import incident_detail, incident_read


_PATTERN_FIELDS = {"pattern", "pattern_status", "pattern_occurrence_count"}


@mcp_tool(
    "platform_admin", name="incidents_list", approval="ask",
    approval_reason="Sensitive failure diagnostics within the delegated administration scope",
    effect_policy="read", concurrency_policy="safe",
    description=(
        "List persisted LLM and tool failure incidents, newest first, within your live "
        "personal/team/all Galaris administration scope. Returns items, total, page and page_size "
        "without traces; use incident_get with a returned ID for full diagnostics. "
        "Optional occurred_from/occurred_until are inclusive ISO datetimes with timezone offsets. "
        "Pages default to 50, maximum 500. Global pattern status/counts require all scope."
    ),
)
async def incidents_list(
    ctx: McpToolContext,
    page: Annotated[int, Field(ge=1)] = 1,
    page_size: Annotated[int, Field(ge=1, le=500)] = 50,
    occurred_from: datetime | None = None,
    occurred_until: datetime | None = None,
    kind: Annotated[str | None, Field(max_length=20)] = None,
    category: Annotated[str | None, Field(max_length=60)] = None,
    recovered: bool | None = None,
    search: Annotated[str | None, Field(max_length=300)] = None,
) -> dict[str, Any]:
    scope = await administration_scope(ctx.agent_id, "platform_admin")
    scope.require_administration()
    if page < 1 or not 1 <= page_size <= 500:
        raise ValueError("page must be positive and page_size must be between 1 and 500")
    for name, value in (("occurred_from", occurred_from), ("occurred_until", occurred_until)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{name} must include a timezone offset")
    if occurred_from is not None and occurred_until is not None and occurred_from > occurred_until:
        raise ValueError("occurred_from must be earlier than or equal to occurred_until")
    rows, total = await service.list_incidents(
        page=page, page_size=page_size, occurred_from=occurred_from,
        occurred_until=occurred_until, kind=kind, category=category,
        recovered=recovered, search=search, agent_ids=scope.agent_ids,
    )
    return {
        "items": [incident_read(*row).model_dump(
            mode="json", exclude=set() if scope.is_global else _PATTERN_FIELDS,
        ) for row in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@mcp_tool(
    "platform_admin", name="incident_get", approval="ask",
    approval_reason="Sensitive failure trace within the delegated administration scope",
    effect_policy="read", concurrency_policy="safe",
    description=(
        "Inspect one failure incident by its exact UUID returned by incidents_list. "
        "Returns its correlations, sanitized trace, redaction/truncation metadata and hash. "
        "Rechecks the active Galaris administration connection and personal/team/all scope. "
        "Global pattern diagnosis, remediation and counters are included only with all scope. "
        "Read-only: does not resolve, purge or replay the incident."
    ),
)
async def incident_get(ctx: McpToolContext, incident_id: UUID) -> dict[str, Any]:
    scope = await administration_scope(ctx.agent_id, "platform_admin")
    scope.require_administration()
    row = await service.get_incident(incident_id, agent_ids=scope.agent_ids)
    if row is None:
        raise ValueError("Failure incident not found in the administration scope")
    return incident_detail(*row).model_dump(
        mode="json", exclude=set() if scope.is_global else _PATTERN_FIELDS,
    )
