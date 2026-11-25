"""Public read-only projection of agent-assigned process definitions."""

from __future__ import annotations


from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast, false, or_, select, true

from app.agent import AgentManagementScope
from core.database import get_db

from . import process_service
from .bpmn import Workflow
from .models import ProcessDefinition, ProcessRun


async def read_process_run_resource(
    identity: UUID,
    *,
    actor_agent_id: int,
    management_scope: AgentManagementScope | None = None,
    page: int = 1,
    after_event: int = 0,
) -> dict[str, Any]:
    """Observe an authorized run without refreshing or advancing its engine."""
    from . import native_runs
    from app.services import has_process_admin_access

    run = await process_service.get_run(identity)
    if run is None or run.deleted_at is not None:
        raise FileNotFoundError("Process run not found")
    if run.engine_code == "galaris":
        payload = await native_runs.inspect_run(identity, management_scope or actor_agent_id, page=page, after_event=after_event)
        payload["next_node_page"] = page + 1 if payload["total"] > page * payload["page_size"] else None
        payload["next_event_cursor"] = payload["event_cursor"] if len(payload["events"]) == payload["page_size"] else None
        first_page = ("id", "workflow_id", "label", "status", "operational", "next_node_page", "next_event_cursor")
        payload = {**{key: payload[key] for key in first_page}, **payload}
    else:
        allowed = (management_scope.allows(run.launcher_agent_id) if management_scope is not None
                   else run.launcher_agent_id == actor_agent_id
                   or await has_process_admin_access(actor_agent_id, target_agent_id=run.launcher_agent_id))
        if not allowed:
            raise PermissionError("Run not found in this agent's participation scope")
        if page != 1 or after_event:
            raise ValueError("Only internal runs support occurrence and event paging")
        detail = await process_service.get_run_detail(identity)
        if detail is None:
            raise FileNotFoundError("Process run not found")
        payload = detail.model_dump(mode="json")
    return {**payload, "resource_uri": f"galaris://processes/runs/{identity}"}


async def _service_codes() -> dict[int, str]:
    return {
        tool.id: tool.code
        for tool in await process_service.list_process_tools()
    }


def _payload(
    definition: ProcessDefinition,
    *,
    service_codes: dict[int, str],
) -> dict[str, Any]:
    created_at = definition.created_at
    updated_at = definition.updated_at
    return {
        "workflow_id": definition.engine_process_id,
        "definition_id": definition.id,
        "resource_uri": process_service.process_resource_uri(definition),
        "native_code": definition.code,
        "label": definition.label,
        "description": definition.description,
        "service_id": definition.service_id,
        "service_code": service_codes.get(definition.service_id, ""),
        "created_at": created_at.isoformat(),
        "updated_at": (
            updated_at.isoformat()
            if updated_at is not None
            else None
        ),
    }


async def read_process_resource(
    workflow_id: str,
    *,
    actor_agent_id: int,
    native: bool = False,
    management_scope: AgentManagementScope | None = None,
) -> dict[str, Any] | None:
    from . import native_definitions

    actor = management_scope or actor_agent_id
    if native:
        definition, _ = await native_definitions.get(workflow_id, actor, content=False)
    else:
        definition = await process_service.get_for_agent(actor_agent_id, workflow_id)
    if definition is None:
        return None
    payload = _payload(definition, service_codes=await _service_codes())
    if definition.code is None:
        return payload
    detail = await native_definitions.read(definition.code, actor)
    graph = Workflow.model_validate(detail["graph"])
    activities: list[dict[str, Any]] = []
    bodies = [graph]
    while bodies:
        for node in bodies.pop().nodes:
            if node.kind not in {"start", "end"}:
                activities.append({"id": node.id, "kind": node.kind, "title": node.title,
                    "inputs": node.inputs, "outputs": node.outputs})
            if node.body is not None:
                bodies.append(node.body)
    launch_schema = {"variables": detail["graph"]["variables"], "inputs": graph.inputs,
                     "outputs": graph.outputs} if graph.typed else {}
    return {
        **payload,
        "schema_version": graph.schema_version,
        "activities": activities,
        **launch_schema,
        **detail,
    }


async def list_process_resources(
    *,
    actor_agent_id: int,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
    management_scope: AgentManagementScope | None = None,
) -> list[dict[str, Any]]:
    definitions = await process_service.list_resource_definitions_for_agent(
        actor_agent_id,
        query=query,
        offset=offset,
        limit=limit,
        management_scope=management_scope,
    )
    service_codes = await _service_codes()
    return [_payload(definition, service_codes=service_codes) for definition in definitions]


async def list_process_run_resources(*, actor_agent_id: int | AgentManagementScope, query: str = "", offset: int = 0,
    limit: int = 50) -> list[dict[str, Any]]:
    from . import native_runs
    from .query_policy import prepare_process_read
    from .native_access import administrative_run_clause

    await prepare_process_read()
    administrative = await administrative_run_clause(actor_agent_id)
    if isinstance(actor_agent_id, int):
        external = or_(administrative, ProcessRun.launcher_agent_id == actor_agent_id)
    else:
        ids = actor_agent_id.agent_ids
        scope = true() if ids is None else ProcessRun.launcher_agent_id.in_(ids) if ids else false()
        external = and_(ProcessRun.launcher_agent_id.is_not(None), scope)
    statement = select(ProcessRun.id, ProcessRun.status, ProcessRun.created_at, ProcessDefinition.label).join(
        ProcessDefinition, ProcessDefinition.id == ProcessRun.process_id
    ).where(ProcessRun.deleted_at.is_(None), or_(
        and_(ProcessRun.engine_code == "galaris", native_runs.readable_run_clause(actor_agent_id, administrative=administrative)),
        and_(ProcessRun.engine_code != "galaris", external),
    ))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(or_(
            ProcessDefinition.label.ilike(pattern, escape="\\"),
            ProcessDefinition.engine_process_id.ilike(pattern, escape="\\"),
            ProcessRun.status.ilike(pattern, escape="\\"),
            cast(ProcessRun.id, String).ilike(pattern, escape="\\"),
        ))
    runs = (await get_db().execute(
        statement.order_by(ProcessRun.created_at.desc(), ProcessRun.id).offset(offset).limit(limit)
    )).all()
    return [{"uri": f"galaris://processes/runs/{run.id}",
        "name": f"{run.label} · {run.status} · {str(run.id)[:8]}",
        "created_at": run.created_at.isoformat()} for run in runs]


__all__ = ["list_process_resources", "list_process_run_resources", "read_process_resource", "read_process_run_resource"]
