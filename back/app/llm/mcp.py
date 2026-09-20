"""Native MCP tools for inspecting persisted LLM calls."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, select

from app.llm.models import LLMCall
from app.llm.schemas import LLMCallRead
from app.tools.mcp_loader import McpToolContext, mcp_tool
from core.database import get_db

_INSPECTION_LIMIT_MAX = 100


@mcp_tool(
    "galaris_admin",
    name="llm_call",
    description=(
        "Return a complete LLM-call inspection as JSON text, including request and response "
        "content, reasoning, tools, usage, costs, timings, errors, and safe summaries of its "
        "related task, agent, configured LLM, and process run. Accept a full UUID or a unique "
        "prefix."
    ),
)
async def mcp_llm_call(ctx: McpToolContext, llm_call_id: str) -> str:  # noqa: ARG001
    """Return the complete JSON representation of an LLM call."""

    from app.tools import require_galaris_admin_access

    await require_galaris_admin_access(ctx.agent_id)
    payload = await inspect_llm_call(llm_call_id)
    return json.dumps(payload, ensure_ascii=False)


@mcp_tool(
    "galaris_admin",
    name="llm_calls",
    description=(
        "Return a JSON array containing only the IDs of the most recent LLM calls started in "
        "the inclusive datetime range. Datetimes must include a timezone offset."
    ),
)
async def mcp_llm_calls(
    ctx: McpToolContext,
    date_debut: datetime,
    date_fin: datetime,
    limit: int = 20,
) -> str:
    """Return LLM-call IDs in an inclusive datetime range as JSON text."""

    from app.tools import require_galaris_admin_access

    await require_galaris_admin_access(ctx.agent_id)
    payload = await inspect_llm_calls(date_debut, date_fin, limit=limit)
    return json.dumps(payload, ensure_ascii=False)


def _inspection_window(
    date_debut: datetime,
    date_fin: datetime,
    limit: int,
) -> tuple[datetime, datetime, int]:
    """Validate an inclusive MCP inspection range and its result limit."""
    if date_debut.tzinfo is None or date_debut.utcoffset() is None:
        raise ValueError("date_debut must include a timezone offset")
    if date_fin.tzinfo is None or date_fin.utcoffset() is None:
        raise ValueError("date_fin must include a timezone offset")
    if date_debut > date_fin:
        raise ValueError("date_debut must be earlier than or equal to date_fin")
    if limit < 1 or limit > _INSPECTION_LIMIT_MAX:
        raise ValueError(f"limit must be between 1 and {_INSPECTION_LIMIT_MAX}")
    return date_debut, date_fin, limit


def _isoformat_or_none(value: Any) -> str | None:
    """Serialize datetime-like values without changing their timezone."""
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


async def _resolve_llm_call(llm_call_id: str | UUID) -> LLMCall | None:
    """Resolve an LLM call by full UUID or a unique prefix."""
    raw_id = str(llm_call_id).strip()
    try:
        call_uuid = llm_call_id if isinstance(llm_call_id, UUID) else UUID(raw_id)
    except ValueError:
        if len(raw_id) < 8:
            raise ValueError(f"Invalid LLM-call UUID or prefix: {llm_call_id}") from None
        result = await get_db().execute(
            select(LLMCall)
            .where(cast(LLMCall.id, String).ilike(f"{raw_id}%"))
            .limit(2)
        )
        matches = list(result.scalars().all())
        if len(matches) > 1:
            raise ValueError(f"Ambiguous LLM-call UUID prefix: {llm_call_id}")
        return matches[0] if matches else None
    return await get_db().get(LLMCall, call_uuid)


async def inspect_llm_call(llm_call_id: str | UUID) -> dict[str, Any]:
    """Build the complete, JSON-compatible inspection payload for one LLM call."""
    from app.agent.models import Agent
    from app.llm.provider_models import LLM
    from app.process.models import ProcessRun
    from app.task.models import Task, TaskStatus

    call = await _resolve_llm_call(llm_call_id)
    if call is None:
        raise ValueError(f"LLM call not found: {llm_call_id}")

    db = get_db()
    agent = None
    if call.agent_id is not None:
        result = await db.execute(
            select(
                Agent.id.label("id"),
                Agent.first_name.label("first_name"),
                Agent.last_name.label("last_name"),
                Agent.code.label("code"),
                Agent.job_title.label("job_title"),
            ).where(Agent.id == call.agent_id)
        )
        row = result.mappings().one_or_none()
        agent = dict(row) if row is not None else None

    task = None
    if call.task_id is not None:
        result = await db.execute(
            select(
                Task.id.label("id"),
                Task.label.label("label"),
                Task.objective.label("objective"),
                Task.status.label("status"),
            ).where(Task.id == call.task_id, Task.deleted_at.is_(None))
        )
        row = result.mappings().one_or_none()
        if row is not None:
            status = row["status"]
            task = {
                "id": str(row["id"]),
                "resource_uri": f"galaris://task/{row['id']}",
                "label": row["label"],
                "objective": row["objective"],
                "status": status.value if isinstance(status, TaskStatus) else str(status),
            }

    configured_llm = None
    if call.llm_id is not None:
        result = await db.execute(
            select(
                LLM.id.label("id"),
                LLM.code.label("code"),
                LLM.llm_name.label("llm_name"),
                LLM.label.label("label"),
                LLM.resource_type.label("resource_type"),
                LLM.primary_capability.label("primary_capability"),
                LLM.service_capabilities.label("service_capabilities"),
                LLM.context_length.label("context_length"),
            ).where(LLM.id == call.llm_id)
        )
        row = result.mappings().one_or_none()
        configured_llm = dict(row) if row is not None else None

    process_run = None
    if call.process_run_id is not None:
        result = await db.execute(
            select(
                ProcessRun.id.label("id"),
                ProcessRun.process_id.label("process_id"),
                ProcessRun.task_id.label("task_id"),
                ProcessRun.engine_code.label("engine_code"),
                ProcessRun.engine_run_id.label("engine_run_id"),
                ProcessRun.status.label("status"),
                ProcessRun.started_at.label("started_at"),
                ProcessRun.finished_at.label("finished_at"),
            ).where(
                ProcessRun.id == call.process_run_id,
                ProcessRun.deleted_at.is_(None),
            )
        )
        row = result.mappings().one_or_none()
        if row is not None:
            process_run = {
                "id": str(row["id"]),
                "process_id": row["process_id"],
                "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
                "engine_code": row["engine_code"],
                "engine_run_id": row["engine_run_id"],
                "status": row["status"],
                "started_at": _isoformat_or_none(row["started_at"]),
                "finished_at": _isoformat_or_none(row["finished_at"]),
            }

    payload = LLMCallRead.model_validate(call).model_dump(mode="json")
    if call.task_id is not None:
        payload["task_uri"] = f"galaris://task/{call.task_id}"
    payload.update({
        "agent": agent,
        "owner": agent,
        "task": task,
        "llm": configured_llm,
        "process_run": process_run,
    })
    return payload


async def inspect_llm_calls(
    date_debut: datetime,
    date_fin: datetime,
    *,
    limit: int = 20,
) -> list[str]:
    """List recent LLM-call IDs in an inclusive datetime range."""
    start, end, safe_limit = _inspection_window(date_debut, date_fin, limit)
    result = await get_db().execute(
        select(LLMCall.id)
        .where(LLMCall.started_at >= start, LLMCall.started_at <= end)
        .order_by(LLMCall.started_at.desc(), LLMCall.id.desc())
        .limit(safe_limit)
    )
    return [str(value) for value in result.scalars().all()]
