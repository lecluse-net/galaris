"""Authorized native Process references, without copying their state into Documents."""

import re
from typing import Any, Literal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import undefer
from core.database import get_db

from app.agent import AgentManagementScope

from . import native_definitions, native_runs
from .bpmn import compile_bpmn
from .models import ProcessDefinition, ProcessRun
from .native_access import accessible_clause
from .query_policy import prepare_process_read


def process_reference(uri: str) -> tuple[Literal["process", "process_run"], str, str]:
    match = re.fullmatch(r"galaris://process(?:es)?/([A-Za-z_][A-Za-z0-9_.-]{0,254})", uri)
    if match:
        code = match[1]
        return "process", code, f"galaris://processes/{code}"
    match = re.fullmatch(r"galaris://processes/runs/([0-9a-f-]{36})", uri)
    if match and str(UUID(match[1])) == match[1]:
        return "process_run", match[1], uri
    raise ValueError("Expected an internal Process or run reference")


async def process_resource_preview(uri: str, actor: int | AgentManagementScope, *, thumbnail: bool = False) -> dict[str, Any]:
    kind, identity, canonical = process_reference(uri)
    if kind == "process":
        record, _ = await native_definitions.get(identity, actor)
        assert record.bpmn_xml is not None
        graph = compile_bpmn(record.bpmn_xml).model_dump(mode="json")
        return {"uri": canonical, "kind": kind, "id": identity, "title": record.label,
            "description": record.description, "revision": record.revision, "graph": graph,
            "process_uri": canonical}
    run = await native_runs.require_run(UUID(identity), actor)
    definition = await get_db().scalar(select(ProcessDefinition).options(undefer(ProcessDefinition.bpmn_xml))
        .where(ProcessDefinition.id == run.process_id))
    if definition is None or definition.bpmn_xml is None:
        raise LookupError("Process definition unavailable")
    graph = (compile_bpmn(definition.bpmn_xml).model_dump(mode="json") if thumbnail
        else run.launch_snapshot.get("definition", {}).get("graph"))
    if graph is None:
        raise LookupError("Run diagram unavailable")
    return {"uri": canonical, "kind": kind, "id": identity,
        "title": run.launch_snapshot.get("process_label") or definition.label,
        "description": None, "revision": run.launch_snapshot.get("definition", {}).get("revision"),
        "graph": graph, "process_uri": f"galaris://processes/{definition.code}"}


async def process_resource_options(query: str, actor: int | AgentManagementScope) -> list[dict[str, str]]:
    await prepare_process_read()
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    definitions = await get_db().scalars(select(ProcessDefinition).where(accessible_clause(actor),
        ProcessDefinition.bpmn_xml.is_not(None), ProcessDefinition.label.ilike(pattern, escape="\\"))
        .order_by(ProcessDefinition.label, ProcessDefinition.id).limit(25))
    entries = [{"uri": f"galaris://processes/{record.code}", "title": record.label, "context": "process"} for record in definitions]
    runs = await get_db().execute(select(ProcessRun, ProcessDefinition.label).join(ProcessDefinition,
        ProcessDefinition.id == ProcessRun.process_id).where(ProcessRun.engine_code == "galaris",
            native_runs.readable_run_clause(actor), ProcessDefinition.label.ilike(pattern, escape="\\"))
        .order_by(ProcessRun.created_at.desc(), ProcessRun.id).limit(25))
    entries.extend({"uri": f"galaris://processes/runs/{run.id}", "title": f"{label} · {str(run.id)[:8]}",
        "context": "process_run"} for run, label in runs)
    return entries
