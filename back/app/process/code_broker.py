"""Durable capability calls made by a remote Python activity."""

from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import DateTime, and_, cast, func, or_, select

from app.services.facade import (RestEffectIntent, RestRequest, RestRequestRejected, authorization_status,
                                 execute_rest_request, execute_workflow_tool, find_rest_effect,
                                 has_completed_workflow_tool_receipt)
from app.task import TaskCreate, TaskStatus, task_service
from core.database import get_db

from .bpmn import Node
from .code_capabilities import CapabilityCall, capabilities
from .engine import ProcessEngineError
from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun, ProcessRunEvent
from .process_service import TERMINAL_STATUSES
from .sanitizer import sanitize

MAX_CALLS = 16
MAX_ARGUMENT_BYTES = 128_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def stage_call(run: ProcessRun, occurrence: ProcessNodeRun, node: Node, handles: dict[str, str],
                     call: CapabilityCall) -> dict[str, Any] | None:
    """Called under the native run lock after the runner lease is checked."""
    attempt = await get_db().scalar(select(ProcessNodeAttempt).where(
        ProcessNodeAttempt.node_run_id == occurrence.id).order_by(ProcessNodeAttempt.number.desc()).limit(1)
        .with_for_update().execution_options(populate_existing=True))
    if attempt is None:
        raise ProcessEngineError("remote_python_protocol", "Python has no admitted activity")
    request = call.model_dump(mode="json")
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(payload) > MAX_ARGUMENT_BYTES:
        raise ProcessEngineError("remote_python_protocol", "Python capability arguments exceed the message limit")
    signature = sha256(payload).hexdigest()
    receipt = attempt.receipt or {}
    if receipt.get("call") == str(call.id):
        if receipt["signature"] != signature:
            raise ProcessEngineError("remote_python_protocol", "A capability call identity was reused with different arguments")
        if attempt.status == "broker_returned":
            return receipt["reply"]
        if attempt.status == "started" and _now() >= datetime.fromisoformat(receipt["deadline"]):
            raise ProcessEngineError("effect_outcome_unknown", "The Python capability outcome is unknown")
        if attempt.status == "broker_authorization":
            from .native_actors import execution_agent
            from .native_engine import local_graph
            task = await task_service.get_by_id(attempt.task_id) if attempt.task_id else None
            if task is not None and not task_service.is_held_by_user(task):
                status = await authorization_status(UUID(receipt["authorization"]["request_id"]),
                    agent_id=execution_agent(local_graph(run, occurrence), node, run.launcher_agent_id))
                if status != "pending":
                    attempt.status = "broker_ready"
        return None
    if attempt.status not in {"intent", "broker_returned"}:
        raise ProcessEngineError("remote_python_protocol", "A previous capability call is still active")
    seen: list[str] = receipt.get("calls", [])
    if len(seen) >= MAX_CALLS or str(call.id) in seen:
        raise ProcessEngineError("remote_python_protocol", "Python capability call is expired or over its limit")
    name = next((alias for alias, handle in handles.items() if handle == str(call.handle)), None)
    declared = capabilities.validate_python(node.config.get("capabilities", {}))
    if name is None or name not in declared:
        raise ProcessEngineError("remote_python_protocol", "The capability is unavailable for this execution")
    capability = declared[name]
    arguments = (RestRequest.model_validate(call.arguments).model_dump(mode="json", exclude_unset=True)
                 if capability.kind == "rest" else call.arguments)
    attempt.task_id = None
    attempt.status = "broker_ready"
    attempt.receipt = {"call": str(call.id), "signature": signature, "calls": [*seen, str(call.id)],
                       "capability": name, "arguments": arguments}
    get_db().add(ProcessRunEvent(run_id=run.id, event_id=f"broker-intent:{attempt.id}:{call.id}", source="native",
        event_type="python.capability.intent", payload={"node": node.id, "capability": name, "kind": capability.kind}))
    return None


async def execute_code_capability(attempt_id: UUID) -> None:
    from .native_actors import execution_agent, validate_execution_access
    from .native_engine import local_graph

    db = get_db()
    attempt = await db.get(ProcessNodeAttempt, attempt_id)
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id) if attempt else None
    if occurrence is None:
        return
    run_id = occurrence.run_id

    async def lock() -> tuple[ProcessRun | None, ProcessNodeAttempt | None]:
        run = await db.get(ProcessRun, run_id, with_for_update=True, populate_existing=True)
        locked = await db.get(ProcessNodeAttempt, attempt_id, with_for_update=True, populate_existing=True)
        return run, locked

    async def settle(saved: ProcessNodeAttempt) -> None:
        task_id = saved.task_id
        receipt = dict(saved.receipt or {})
        # The tool already returned. A retry here can only finalize the
        # context Task, even if its resource journal advanced its revision.
        await db.commit()
        if task_id is None:
            raise RuntimeError("A broker receipt is missing its context Task")
        waiting = "reply" not in receipt
        if waiting:
            await task_service.suspend_workflow_operation(task_id)
        else:
            error = receipt["reply"].get("error") if receipt["reply"]["status"] == "rejected" else None
            await task_service.complete_workflow_operation(task_id, {}, error=error)
        _, current = await lock()
        if (current is not None and current.status == "broker_settling"
                and (current.receipt or {}).get("call") == receipt["call"]):
            current.status = "broker_authorization" if waiting else "broker_returned"
        await db.commit()

    run, attempt = await lock()
    if run is None or attempt is None or not attempt.receipt:
        return
    if attempt.status == "broker_settling":
        await settle(attempt)
        return
    if attempt.status == "started" and run.engine_metadata["native"].get("cancel_requested"):
        receipt = dict(attempt.receipt)
        if (run.status in TERMINAL_STATUSES or "rest_effect" not in receipt
                or datetime.fromisoformat(receipt["rest_effect_retry_at"]) > _now()):
            return
        graph = local_graph(run, occurrence)
        node = graph.node(occurrence.node_key)
        capability = capabilities.validate_python(node.config.get("capabilities", {})).get(receipt["capability"])
        if node.kind != "python" or capability is None or capability.kind != "rest":
            return
        agent_id = execution_agent(graph, node, run.launcher_agent_id)
        attempt.receipt = {**receipt, "rest_effect_retry_at": (_now() + timedelta(seconds=30)).isoformat()}
        await db.commit()
        row_id = await find_rest_effect(agent_id=agent_id, service_code=capability.operation,
            request=RestRequest.model_validate(receipt["arguments"]), intent=RestEffectIntent.model_validate(receipt["rest_effect"]))
        if row_id is None:
            return
        run, attempt = await lock()
        if (run is None or run.status in TERMINAL_STATUSES or not run.engine_metadata["native"].get("cancel_requested")
                or attempt is None or attempt.status != "started"
                or (attempt.receipt or {}).get("call") != receipt["call"]
                or (attempt.receipt or {}).get("rest_effect") != receipt["rest_effect"]):
            return
        attempt.status = "broker_returned"
        attempt.receipt = {**receipt, "reply": {"status": "completed", "output": {"row_id": row_id}}, "reconciled": True}
        db.add(ProcessRunEvent(run_id=run.id, event_id=f"broker-receipt:{attempt.id}:{receipt['call']}", source="native",
            event_type="python.capability.receipt", payload={"node": node.id, "capability": receipt["capability"],
                "status": "completed", "reconciled": True}))
        await db.commit()
        return
    if attempt.status != "broker_ready":
        return
    if run.status in TERMINAL_STATUSES or run.engine_metadata["native"].get("cancel_requested"):
        return
    graph = local_graph(run, occurrence)
    node = graph.node(occurrence.node_key)
    if node.kind != "python":
        return
    receipt = dict(attempt.receipt)
    job = occurrence.context["code_jobs"]["activity"]
    try:
        await validate_execution_access(run, graph)
    except (LookupError, PermissionError, ValueError):
        rejection = "The process execution is no longer authorized"
    else:
        rejection = ("Capability expired"
            if _now() >= datetime.fromisoformat(job["created"]) + timedelta(minutes=15) else None)
    if rejection:
        attempt.status = "broker_settling" if attempt.task_id is not None else "broker_returned"
        attempt.receipt = {**receipt, "reply": {"status": "rejected", "error": rejection}}
        await db.commit()
        if attempt.status == "broker_settling":
            await settle(attempt)
        return
    assigned_agent = execution_agent(graph, node, run.launcher_agent_id)
    capability = capabilities.validate_python(node.config.get("capabilities", {}))[receipt["capability"]]
    call_id = uuid5(attempt.id, receipt["call"])
    task_id = attempt.task_id
    # A durable claim precedes any service call. A lost receipt can never enqueue this operation again.
    attempt.status = "started"
    attempt.receipt = {**receipt, "deadline": (_now() + timedelta(minutes=6)).isoformat()}
    await db.commit()
    admission_rejected = False
    if capability.kind == "mcp" and task_id is None:
        try:
            task = await task_service.create(TaskCreate(label=(node.title or node.id)[:400],
                agent_id=assigned_agent, requester_agent_id=run.launcher_agent_id, status=TaskStatus.DISPATCH, ai=False,
                paused=True, source_task_id=run.task_id,
                data={"process_run_id": str(run.id), "workflow_operation": True, "pause_reasons": ["workflow_operation"]}),
                idempotency_key=f"process-python:{call_id}", requester_user_id=run.requester_user_id)
        except PermissionError:
            await db.rollback()
            admission_rejected = True
        else:
            task_id = task.id
            current, attempt = await lock()
            if current is None or attempt is None:
                await db.rollback()
                await task_service.complete_workflow_operation(task_id, {}, error="Process no longer exists")
                return
            attempt.task_id = task_id
            await db.commit()

    async def admit_rest_effect(effect: RestEffectIntent) -> bool:
        current, pending = await lock()
        admitted = (current is not None and current.status not in TERMINAL_STATUSES
            and not current.engine_metadata["native"].get("cancel_requested")
            and pending is not None and pending.status == "started" and (pending.receipt or {}).get("call") == receipt["call"])
        if admitted and pending is not None:
            pending.receipt = {**(pending.receipt or {}), "rest_effect": effect.model_dump(mode="json"),
                "rest_effect_retry_at": _now().isoformat()}
        await db.commit()
        return admitted

    async def dispatch() -> dict[str, Any] | None:
        if capability.kind == "rest":
            try:
                result = await execute_rest_request(agent_id=assigned_agent, service_code=capability.operation,
                    request=RestRequest.model_validate(receipt["arguments"]), admit_effect=admit_rest_effect)
            except RestRequestRejected as error:
                return {"status": "rejected", "error": str(error)}
            except PermissionError:
                return {"status": "rejected", "error": "Service rejected the capability call"}
            return {"status": "completed", "output": result.model_dump(mode="json")}
        assert task_id is not None
        async with task_service.workflow_operation(task_id) as admitted:
            if not admitted:
                return None
            # Recheck cancellation after task admission and before invoking the Service.
            current, pending = await lock()
            stopped = (current is None or pending is None or current.status in TERMINAL_STATUSES
                or bool(current.engine_metadata["native"].get("cancel_requested")))
            await db.commit()
            if stopped:
                return {"status": "rejected", "error": "Process cancelled"}
            return await execute_workflow_tool(agent_id=assigned_agent, task_id=task_id,
                tool_name=capability.operation, arguments=receipt["arguments"], operation_id=call_id,
                continuation=receipt.get("authorization", {}).get("continuation"))

    result = {"status": "rejected"} if admission_rejected else await dispatch()
    run, attempt = await lock()
    if run is None or attempt is None or attempt.status != "started":
        return
    if result is None:
        attempt.status = "broker_ready"
        attempt.receipt = receipt
    elif result["status"] == "waiting":
        attempt.status = "broker_settling"
        attempt.receipt = {**receipt, "authorization": result["authorization"]}
    else:
        attempt.status = "broker_settling" if attempt.task_id is not None else "broker_returned"
        public = {"status": result["status"]}
        if result["status"] == "completed":
            public["output"] = sanitize(result["output"], max_bytes=MAX_ARGUMENT_BYTES)
        elif capability.kind == "rest":
            public["error"] = result["error"]
        else:
            public["error"] = "Service rejected the capability call"
        attempt.receipt = {**receipt, "reply": public}
        get_db().add(ProcessRunEvent(run_id=run.id, event_id=f"broker-receipt:{attempt.id}:{receipt['call']}",
            source="native", event_type="python.capability.receipt", payload={"node": node.id,
                "capability": receipt["capability"], "status": result["status"]}))
    await db.commit()
    if attempt.status == "broker_settling":
        await settle(attempt)


async def reconcile_stopping_file_creation(run_id: UUID, attempt_id: UUID) -> None:
    """Recover a confirmed local file creation after the broker lost the tool's reply."""
    from .native_actors import execution_agent
    from .native_engine import local_graph

    db = get_db()
    run = await db.get(ProcessRun, run_id, with_for_update=True, populate_existing=True)
    if run is None or run.status in TERMINAL_STATUSES or not run.engine_metadata["native"].get("cancel_requested"):
        return
    attempt = await db.get(ProcessNodeAttempt, attempt_id, with_for_update=True, populate_existing=True)
    if attempt is None or attempt.status != "started" or attempt.task_id is None or not attempt.receipt:
        return
    receipt = attempt.receipt
    authorization = receipt.get("authorization", {})
    if not authorization.get("request_id") or receipt.get("arguments", {}).get("path") != "file://":
        return
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    if occurrence is None or occurrence.run_id != run.id:
        return
    graph = local_graph(run, occurrence)
    node = graph.node(occurrence.node_key)
    if node.kind != "python":
        return
    capability = capabilities.validate_python(node.config.get("capabilities", {})).get(receipt.get("capability", ""))
    if capability is None or capability.kind != "mcp" or capability.operation != "file_create":
        return
    if not await has_completed_workflow_tool_receipt(request_id=UUID(authorization["request_id"]),
            agent_id=execution_agent(graph, node, run.launcher_agent_id), task_id=attempt.task_id,
            tool_name=capability.operation, operation_id=uuid5(attempt.id, receipt["call"])):
        return
    attempt.status = "broker_settling"
    attempt.receipt = {**receipt, "reply": {"status": "completed", "output": {}}, "reconciled": True}
    db.add(ProcessRunEvent(run_id=run.id, event_id=f"broker-receipt:{attempt.id}:{receipt['call']}",
        source="native", event_type="python.capability.receipt", payload={"node": node.id,
            "capability": receipt["capability"], "status": "completed", "reconciled": True}))
    await db.commit()
    await execute_code_capability(attempt_id)


async def discover_code_capability_calls(limit: int, exclude: Collection[UUID]) -> list[UUID]:
    cancelled = ProcessRun.engine_metadata["native"]["cancel_requested"].as_boolean()
    next_lookup = cast(ProcessNodeAttempt.receipt["rest_effect_retry_at"].as_string(), DateTime(timezone=True))
    return list(await get_db().scalars(select(ProcessNodeAttempt.id).join(ProcessNodeRun).join(ProcessRun).where(
        ProcessNodeAttempt.id.not_in(exclude),
        or_(ProcessNodeAttempt.status == "broker_settling", and_(ProcessRun.status.not_in(TERMINAL_STATUSES), or_(
            and_(ProcessNodeAttempt.status == "broker_ready", cancelled.is_not(True)),
            and_(ProcessNodeAttempt.status == "started", cancelled.is_(True), next_lookup <= _now())))))
        .order_by(func.coalesce(next_lookup, ProcessNodeAttempt.created_at), ProcessNodeAttempt.id).limit(limit)))
