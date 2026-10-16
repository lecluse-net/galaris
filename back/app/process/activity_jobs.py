"""Durable external activities outside native graph progression passes."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from core.database import get_db, get_db_session
from app.tools.facade import RestRequest, execute_rest_request, execute_workflow_tool
from app.task import task_service
from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from .process_service import TERMINAL_STATUSES


async def execute_external_activity(identity: UUID) -> None:
    """Run one claimed intent; an acquired response never causes a second HTTP call."""
    attempt = await get_db().get(ProcessNodeAttempt, identity)
    occurrence = await get_db().get(ProcessNodeRun, attempt.node_run_id) if attempt else None
    if occurrence is None:
        return
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == occurrence.run_id)
        .with_for_update().execution_options(populate_existing=True))
    attempt = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    if run is None or attempt is None or attempt.status not in {"rest_ready", "tool_ready"}:
        await get_db().commit()
        return
    state: dict[str, Any] = run.engine_metadata.get("native", {})
    if run.status in TERMINAL_STATUSES or state.get("cancel_requested"):
        attempt.status = "cancelled"
        await get_db().commit()
        return
    from .native_engine import local_graph
    from .native_actors import execution_agent
    graph = local_graph(run, occurrence)
    node = graph.node(occurrence.node_key)
    if not graph.typed or node.kind not in {"rest", "tool_call"}:
        raise ValueError("This intent does not belong to a typed external activity")
    agent_id = execution_agent(graph, node, run.launcher_agent_id)
    prepared = dict(attempt.receipt or {})
    token = uuid4().hex
    # Tools enforces an absolute HTTP timeout of at most 300 seconds. This
    # recovery deadline never authorizes a replay of an unacknowledged request.
    attempt.receipt = {**prepared, "worker_token": token, "lease_until": (datetime.now(timezone.utc) + timedelta(seconds=360)).isoformat()}
    attempt.status = "claiming"
    run_id = run.id
    await get_db().commit()
    result: dict[str, Any] | None = None
    tool_receipt: dict[str, Any] | None = None
    error: str | None = None
    safe_failure = False

    async def mark_dispatched() -> bool:
        current = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == run_id)
            .with_for_update().execution_options(populate_existing=True))
        effect = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.id == identity)
            .with_for_update().execution_options(populate_existing=True))
        if (current is None or effect is None or effect.status != "claiming"
                or (effect.receipt or {}).get("worker_token") != token):
            await get_db().commit()
            return False
        if current.status in TERMINAL_STATUSES or current.engine_metadata.get("native", {}).get("cancel_requested"):
            effect.status = "cancelled"
            await get_db().commit()
            return False
        effect.status = "started"
        await get_db().commit()
        return True

    try:
        if node.kind == "rest":
            request = RestRequest.model_validate(prepared["request"])
            if not await mark_dispatched():
                return
            response = await execute_rest_request(agent_id=agent_id, tool_code=str(node.config["tool_code"]), request=request)
            result = response.model_dump(mode="json")
        else:
            assert attempt.task_id is not None
            async with task_service.workflow_operation(attempt.task_id) as admitted:
                if not admitted:
                    attempt.status = "authorization" if "authorization" in prepared else "tool_ready"
                    attempt.receipt = prepared
                    await get_db().commit()
                    return
                if not await mark_dispatched():
                    await task_service.complete_workflow_operation(attempt.task_id, {}, error="Workflow stopped before dispatch")
                    return
                tool_receipt = await execute_workflow_tool(agent_id=agent_id, task_id=attempt.task_id,
                    tool_name=str(node.config["tool"]), arguments=prepared["arguments"], operation_id=attempt.id,
                    continuation=prepared.get("authorization", {}).get("continuation"))
                if tool_receipt["status"] == "completed":
                    result = tool_receipt["output"]
    except PermissionError as exc:
        safe_failure = node.kind == "rest" or attempt.status == "claiming"
        error = str(exc) if safe_failure else "Tool outcome is unknown; reconcile before retrying"
    except Exception:
        # A transport interruption may follow a remote effect. Keep its intent
        # unresolved, without leaking transport credentials into diagnostics.
        safe_failure = attempt.status == "claiming"
        error = "External activity admission failed" if safe_failure else "External effect outcome is unknown; reconcile the remote operation before retrying"
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == run_id)
        .with_for_update().execution_options(populate_existing=True))
    attempt = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    if run is None or attempt is None or (attempt.receipt or {}).get("worker_token") != token:
        await get_db().commit()
        return
    if run.status in TERMINAL_STATUSES:
        await get_db().commit()
        return
    if tool_receipt is not None and tool_receipt["status"] == "waiting":
        attempt.status = "authorization"
        attempt.receipt = {**tool_receipt, "arguments": prepared["arguments"]}
    elif tool_receipt is not None and tool_receipt["status"] == "rejected":
        attempt.status = "failed"
        attempt.receipt = tool_receipt
        attempt.error = str(tool_receipt.get("error", "Tool activity rejected"))
    elif result is not None:
        attempt.status = "returned"
        attempt.receipt = {"output": result}
    elif safe_failure:
        attempt.status = "failed"
        attempt.error = error
    else:
        # "started" remains an uncertainty blocker even after the worker exits.
        attempt.receipt = {**(attempt.receipt or {}), "lease_until": datetime.now(timezone.utc).isoformat()}
        attempt.error = error
    await get_db().commit()
    if node.kind == "tool_call" and attempt.task_id is not None:
        if attempt.status in {"authorization", "returned"}:
            await task_service.suspend_workflow_operation(attempt.task_id)
        elif attempt.status == "failed":
            await task_service.complete_workflow_operation(attempt.task_id, attempt.receipt or {}, error=attempt.error)


async def run_external_activity_jobs() -> int:
    """Scheduler root: each concurrent HTTP activity owns its DB session."""
    identities = list(await get_db().scalars(select(ProcessNodeAttempt.id)
        .join(ProcessNodeRun, ProcessNodeRun.id == ProcessNodeAttempt.node_run_id)
        .join(ProcessRun, ProcessRun.id == ProcessNodeRun.run_id)
        .where(ProcessNodeAttempt.status.in_(("rest_ready", "tool_ready")), ProcessNodeRun.status == "waiting",
            ProcessRun.status.not_in(TERMINAL_STATUSES))
        .order_by(ProcessNodeAttempt.created_at, ProcessNodeAttempt.id).limit(4)))
    await get_db().commit()

    async def execute(identity: UUID) -> None:
        async with get_db_session():
            await execute_external_activity(identity)

    async with asyncio.TaskGroup() as group:
        for identity in identities:
            group.create_task(execute(identity))
    return len(identities)
