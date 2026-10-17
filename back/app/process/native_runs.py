"""Resource-scoped run inspection and persisted debugger controls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select, true, or_, and_, literal
from sqlalchemy.dialects.postgresql import JSONB

from app.agent import AgentManagementScope
from app.memory import workflow_document_actor, workflow_document_readable_ids
from app.memory import workflow_document_policy_ids
from app.memory import prepare_workflow_document_read
from app.tools import has_process_admin_access
from sqlalchemy.sql.elements import ColumnElement
from core.database import get_db

from .models import ProcessDefinition, ProcessNodeAttempt, ProcessNodeRun, ProcessRun, ProcessRunEvent
from .process_service import TERMINAL_STATUSES


def _definition_policy(actor: int | AgentManagementScope) -> ColumnElement[bool]:
    allowed = select(ProcessDefinition.id).where(or_(ProcessDefinition.document_id.is_(None),
        ProcessDefinition.document_id.in_(workflow_document_policy_ids(actor))))
    return ProcessRun.process_id.in_(allowed)


def readable_run_clause(actor: int | AgentManagementScope, *, administrative: bool = False) -> ColumnElement[bool]:
    """Filter agent participation or human Dataset policy before counting and pagination."""
    if isinstance(actor, int):
        return true() if administrative else or_(ProcessRun.launcher_agent_id == actor,
            ProcessRun.launch_snapshot["participant_agents"].contains([actor]))
    owner = and_(
        ProcessRun.dataset_document_id.is_(None), or_(ProcessRun.requester_user_id == actor.user_id,
            ProcessRun.launcher_agent_id.in_(actor.agent_ids) if actor.agent_ids is not None else true()))
    return and_(_definition_policy(actor), or_(owner,
        ProcessRun.dataset_document_id.in_(workflow_document_readable_ids(actor))))


async def require_run(identity: UUID, actor: int | AgentManagementScope, *, control: bool = False) -> ProcessRun:
    # Single-run views compose the same ACLs as lists. Bound compilation work
    # before authorization, including the generic run-detail route.
    await prepare_workflow_document_read()
    run = await get_db().get(ProcessRun, identity)
    if run is None or run.engine_code != "galaris":
        raise LookupError("Internal run not found")
    if isinstance(actor, int):
        administrative = await has_process_admin_access(actor)
        clause = ProcessRun.launcher_agent_id == actor if control and not administrative else readable_run_clause(actor, administrative=administrative)
        if not await get_db().scalar(select(ProcessRun.id).where(ProcessRun.id == identity, clause)):
            raise PermissionError("Run not found in this agent's participation scope")
        return run
    definition = await get_db().get(ProcessDefinition, run.process_id)
    if definition is not None and definition.document_id is not None:
        from app.memory import workflow_document_is_orphan
        if await workflow_document_is_orphan(definition.document_id):
            from .native_definitions import get
            await get(definition.code or "", actor)
    if control:
        if not actor.allows(run.launcher_agent_id) and run.requester_user_id != actor.user_id:
            raise PermissionError("Run control access denied")
    elif run.dataset_document_id is not None:
        from app.memory import MemoryNotFoundError, MemoryPermissionError
        try:
            await workflow_document_actor(run.dataset_document_id, actor)
        except (MemoryNotFoundError, MemoryPermissionError) as error:
            raise PermissionError("Run access denied") from error
    elif not actor.allows(run.launcher_agent_id) and run.requester_user_id != actor.user_id:
        raise PermissionError("Run access denied")
    return run


async def control_run(identity: UUID, actor: int | AgentManagementScope,
                      action: Literal["pause", "resume", "step", "breakpoints"], nodes: list[str] | None = None,
                      *, command_key: UUID | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    await require_run(identity, actor, control=True)
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    assert run is not None
    event_key = f"debugger:{command_key}" if command_key else None
    if event_key:
        previous = await get_db().scalar(select(ProcessRunEvent).where(
            ProcessRunEvent.run_id == identity, ProcessRunEvent.event_id == event_key))
        if previous is not None:
            if previous.event_type != "debugger." + action or previous.payload.get("nodes") != (nodes or []):
                raise ValueError("The command key belongs to a different debugger command")
            return dict(previous.payload["receipt"])
    if run.status in TERMINAL_STATUSES:
        raise ValueError("A terminal run cannot be controlled")
    state = deepcopy(run.engine_metadata.get("native", {}))
    if (state.get("status") == "unknown" or state.get("error", {}).get("code") == "effect_outcome_unknown") and action in {"resume", "step"}:
        raise ValueError("An uncertain Tool effect requires reconciliation before another admission")
    revision = int(state.get("debugger_revision", 0))
    if expected_revision is not None and revision != expected_revision:
        from app.memory import MemoryConflictError
        raise MemoryConflictError("Debugger state changed; refresh before issuing another command")
    if action == "breakpoints":
        from .bpmn import Workflow
        graph = Workflow.model_validate(run.launch_snapshot["definition"]["graph"])
        known: set[str] = set()
        pending = [graph]
        while pending:
            body = pending.pop()
            for node in body.nodes:
                known.add(node.id)
                if node.body:
                    pending.append(node.body)
        if not set(nodes or []).issubset(known):
            raise ValueError("Unknown breakpoint node")
        state["breakpoints"] = list(dict.fromkeys(nodes or []))
    else:
        if action == "step" and state.get("step_root"):
            raise ValueError("The current step has not completed")
        state["paused"] = action != "resume"
        state["step_pending"] = action == "step"
        if action != "step":
            state.pop("step_root", None)
        if action == "resume" and state.get("breakpoint_hit"):
            state["breakpoint_skip"] = state["breakpoint_hit"]
    state["debugger_revision"] = revision + 1
    receipt = {"run_id": str(run.id), "paused": state.get("paused", False),
        "breakpoints": state.get("breakpoints", []), "debugger_revision": revision + 1}
    run.engine_metadata = {**run.engine_metadata, "native": state}
    get_db().add(ProcessRunEvent(run_id=run.id, source="native", event_type="debugger." + action,
        event_id=event_key, payload={"nodes": nodes or [], "receipt": receipt}))
    await get_db().commit()
    return receipt


def _occurrence_payload(node: ProcessNodeRun) -> dict[str, Any]:
    return {"id": str(node.id), "node_key": node.node_key, "status": node.status,
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "finished_at": node.finished_at.isoformat() if node.finished_at else None, "output": node.output,
        "body_path": node.context.get("body_path", []), "iteration": node.context.get("loop", {}).get("index")}


async def inspect_run(identity: UUID, actor: int | AgentManagementScope, *, page: int = 1, page_size: int = 50,
                      after_event: int = 0) -> dict[str, Any]:
    run = await require_run(identity, actor)
    nodes = list(await get_db().scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == identity)
        .order_by(ProcessNodeRun.admission_order, ProcessNodeRun.id).offset((page - 1) * page_size).limit(page_size)))
    total = await get_db().scalar(select(func.count()).select_from(ProcessNodeRun).where(ProcessNodeRun.run_id == identity))
    events = list(await get_db().scalars(select(ProcessRunEvent).where(ProcessRunEvent.run_id == identity,
        ProcessRunEvent.id > after_event).order_by(ProcessRunEvent.id).limit(page_size)))
    state: dict[str, Any] = run.engine_metadata.get("native", {})
    can_control = (run.launcher_agent_id == actor or await has_process_admin_access(actor)) if isinstance(actor, int) else actor.allows(run.launcher_agent_id) or run.requester_user_id == actor.user_id
    latest = select(ProcessNodeRun.node_key, ProcessNodeRun.status,
        func.row_number().over(partition_by=ProcessNodeRun.node_key, order_by=(ProcessNodeRun.admission_order.desc(), ProcessNodeRun.id.desc())).label("rank")
    ).where(ProcessNodeRun.run_id == identity).subquery()
    statuses = {str(key): str(status) for key, status in (await get_db().execute(select(latest.c.node_key, latest.c.status).where(latest.c.rank == 1))).all()}
    from .run_observation import observe_run
    visible_children = set(str(value) for value in await get_db().scalars(select(ProcessRun.id).where(
        ProcessRun.parent_run_id == identity, readable_run_clause(actor,
            administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))))
    operational = await observe_run(run, can_control=can_control, visible_children=visible_children)
    visible_parent = await get_db().scalar(select(ProcessRun.id).where(ProcessRun.id == run.parent_run_id,
        readable_run_clause(actor, administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))) if run.parent_run_id else None
    return {"id": str(run.id), "status": run.status, "graph": run.launch_snapshot.get("definition", {}).get("graph"),
        "label": run.launch_snapshot.get("process_label", ""), "workflow_id": run.launch_snapshot.get("workflow_id"),
        "operational": operational,
        "can_control": can_control, "node_statuses": statuses,
        "definition_revision": run.launch_snapshot.get("definition", {}).get("revision"),
        "dataset_uri": f"document://{run.dataset_document_id}" if run.dataset_document_id else None,
        "output": run.output, "error": run.error_message, "error_code": run.error_code, "paused": state.get("paused", False),
        "breakpoints": state.get("breakpoints", []), "debugger_revision": int(state.get("debugger_revision", 0)),
        "parent_run_id": str(visible_parent) if visible_parent else None,
        "nodes": [_occurrence_payload(node) for node in nodes], "total": total, "page": page, "page_size": page_size,
        "events": [{"id": event.id, "type": event.event_type, "payload": event.payload} for event in events],
        "event_cursor": events[-1].id if events else after_event,
        "duration_seconds": max(0.0, ((run.finished_at or datetime.now(timezone.utc)) - run.created_at).total_seconds())}


def _run_result_preview(run: ProcessRun) -> str:
    preview = run.error_message or run.error_code or (
        json.dumps(run.output, ensure_ascii=False) if run.output is not None else ""
    )
    return preview if len(preview) <= 1200 else preview[:1199] + "…"


async def list_runs(actor: int | AgentManagementScope, *, code: str | None = None,
                    page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await prepare_workflow_document_read()
    # Definition visibility never grants Dataset visibility. Orphan definitions
    # are filtered before counting and paging through the Document policy.
    query = select(ProcessRun).join(ProcessDefinition, ProcessDefinition.id == ProcessRun.process_id).where(
        ProcessRun.engine_code == "galaris", readable_run_clause(actor,
            administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))
    if code is not None:
        query = query.where(ProcessDefinition.code == code)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    rows = list(await get_db().scalars(query.order_by(ProcessRun.created_at.desc(), ProcessRun.id).offset((page - 1) * page_size).limit(page_size)))
    return {"items": [{"id": str(run.id), "status": run.status, "process_label": run.launch_snapshot.get("process_label", ""),
        "result_preview": _run_result_preview(run),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat(), "engine_code": run.engine_code} for run in rows],
        "total": total or 0, "page": page, "page_size": page_size}


async def activity_occurrences(identity: UUID, node_key: str, actor: int | AgentManagementScope, *,
                               body_path: list[str] | None = None, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Inspect an activity independently of the run's global occurrence page."""
    await require_run(identity, actor)
    if page < 1 or not 1 <= page_size <= 500:
        raise ValueError("Invalid activity pagination")
    query = select(ProcessNodeRun).where(ProcessNodeRun.run_id == identity, ProcessNodeRun.node_key == node_key,
        func.coalesce(ProcessNodeRun.context["body_path"], literal([], type_=JSONB)) == (body_path or []))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    nodes = await get_db().scalars(query.order_by(ProcessNodeRun.admission_order.desc(), ProcessNodeRun.id.desc())
        .offset((page - 1) * page_size).limit(page_size))
    return {"items": [_occurrence_payload(node) for node in nodes], "total": total, "page": page, "page_size": page_size}


async def inspect_occurrence(identity: UUID, node_identity: UUID, actor: int | AgentManagementScope) -> dict[str, Any]:
    await require_run(identity, actor)
    node = await get_db().get(ProcessNodeRun, node_identity)
    if node is None or node.run_id != identity:
        raise LookupError("Node occurrence not found")
    attempts = list(await get_db().scalars(select(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == node_identity)
        .order_by(ProcessNodeAttempt.number)))
    visible_children = set(await get_db().scalars(select(ProcessRun.id).where(
        ProcessRun.id.in_([attempt.child_run_id for attempt in attempts if attempt.child_run_id]),
        readable_run_clause(actor, administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))))
    return {**_occurrence_payload(node), "attempts": [{"id": str(attempt.id), "number": attempt.number,
        "status": attempt.status, "input": attempt.input, "prompt": attempt.prompt, "receipt": _inspection_receipt(attempt.receipt),
        "task_uri": f"galaris://task/{attempt.task_id}" if attempt.task_id else None,
        "child_run_id": str(attempt.child_run_id) if attempt.child_run_id in visible_children else None, "error": attempt.error} for attempt in attempts]}


def _inspection_receipt(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    """An observer sees approval evidence, without the engine's continuation capability."""
    result = deepcopy(receipt)
    if result is not None and isinstance(result.get("authorization"), dict):
        result["authorization"].pop("continuation", None)
    return result


async def children(identity: UUID, actor: int | AgentManagementScope, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await prepare_workflow_document_read()
    await require_run(identity, actor)
    query = select(ProcessRun).where(ProcessRun.parent_run_id == identity, readable_run_clause(actor,
        administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    rows = await get_db().scalars(query.order_by(ProcessRun.created_at, ProcessRun.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"id": str(run.id), "status": run.status, "process_label": run.launch_snapshot.get("process_label", ""),
             "engine_code": run.engine_code} for run in rows], "total": total, "page": page, "page_size": page_size}


async def run_metrics(identity: UUID, actor: int | AgentManagementScope) -> dict[str, Any]:
    await require_run(identity, actor)
    from app.llm import LLMCall
    descendants = select(ProcessRun.id).where(ProcessRun.id == identity).cte(recursive=True)
    descendants = descendants.union_all(select(ProcessRun.id).join(descendants, ProcessRun.parent_run_id == descendants.c.id))
    visible = select(ProcessRun.id).where(ProcessRun.id.in_(select(descendants.c.id)), readable_run_clause(actor,
        administrative=await has_process_admin_access(actor) if isinstance(actor, int) else False))
    calls = list(await get_db().scalars(select(LLMCall).where(LLMCall.process_run_id.in_(visible))))
    direct = [call for call in calls if call.process_run_id == identity]

    def summarize(rows: list[LLMCall]) -> dict[str, Any]:
        return {"calls": len(rows), "cost": sum(call.cost for call in rows) if rows else None,
            "inference_cost": sum(call.inference_cost for call in rows) if rows else None,
            "llm_duration_seconds": sum(call.duration for call in rows) if rows else None,
            "tokens": sum(call.total_tokens for call in rows) if rows else None,
            "estimated_calls": sum(1 for call in rows if call.cost_estimated)}

    per_task: dict[str, list[LLMCall]] = {}
    for call in direct:
        if call.task_id:
            per_task.setdefault(str(call.task_id), []).append(call)
    count = await get_db().scalar(select(func.count()).select_from(descendants))
    visible_count = await get_db().scalar(select(func.count()).select_from(visible.subquery()))
    activity_tasks = list((await get_db().execute(select(ProcessNodeRun.node_key, ProcessNodeAttempt.task_id)
        .join(ProcessNodeAttempt, ProcessNodeAttempt.node_run_id == ProcessNodeRun.id)
        .where(ProcessNodeRun.run_id == identity, ProcessNodeAttempt.task_id.is_not(None)))).all())
    per_node: dict[str, list[LLMCall]] = {}
    for key, task_id in activity_tasks:
        per_node.setdefault(key, []).extend(call for call in direct if call.task_id == task_id)
    missing = any(str(task_id) not in per_task for _, task_id in activity_tasks)
    durations = (await get_db().execute(select(ProcessNodeRun.node_key,
        func.sum(func.extract("epoch", func.coalesce(ProcessNodeRun.finished_at, func.now()) - ProcessNodeRun.started_at)))
        .where(ProcessNodeRun.run_id == identity, ProcessNodeRun.started_at.is_not(None))
        .group_by(ProcessNodeRun.node_key))).all()
    node_metrics = {key: summarize(rows) for key, rows in per_node.items()}
    for key, duration in durations:
        node_metrics.setdefault(key, summarize([]))["duration_seconds"] = float(duration) if duration is not None else None
    occurrences = list(await get_db().scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == identity)))
    bindings = (await get_db().execute(select(ProcessNodeAttempt.id, ProcessNodeAttempt.node_run_id, ProcessNodeAttempt.task_id)
        .join(ProcessNodeRun).where(ProcessNodeRun.run_id == identity))).all()
    attempt_nodes = {attempt: node for attempt, node, _ in bindings}
    task_nodes = {task: node for _, node, task in bindings if task is not None}
    links = {run_id: (parent, caller) for run_id, parent, caller in (await get_db().execute(
        select(ProcessRun.id, ProcessRun.parent_run_id, ProcessRun.caller_node_attempt_id)
        .where(ProcessRun.id.in_(visible)))).all()}
    own_calls: dict[UUID, list[LLMCall]] = {}
    inclusive_calls: dict[UUID, list[LLMCall]] = {}
    for call in calls:
        node_id = task_nodes.get(call.task_id) if call.process_run_id == identity and call.task_id is not None else None
        if call.process_run_id == identity and node_id is not None:
            own_calls.setdefault(node_id, []).append(call)
        if call.process_run_id != identity:
            cursor = call.process_run_id
            while cursor is not None and cursor in links:
                parent, caller = links[cursor]
                if parent == identity:
                    node_id = attempt_nodes.get(caller) if caller is not None else None
                    break
                cursor = parent
        if node_id is not None:
            inclusive_calls.setdefault(node_id, []).append(call)
    calculated_at = datetime.now(timezone.utc)
    occurrence_metrics = {str(node.id): {"node_key": node.node_key,
        "direct": summarize(own_calls.get(node.id, [])), "inclusive": summarize(inclusive_calls.get(node.id, [])),
        "duration_seconds": max(0.0, ((node.finished_at or calculated_at) - node.started_at).total_seconds()) if node.started_at else None}
        for node in occurrences}
    return {"direct": summarize(direct), "inclusive": summarize(calls),
        "partial": count != visible_count or missing, "nodes": node_metrics,
        "tasks": {key: summarize(rows) for key, rows in per_task.items()}, "occurrences": occurrence_metrics,
        "currency": "USD", "calculated_at": calculated_at.isoformat()}
