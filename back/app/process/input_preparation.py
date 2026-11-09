"""Reserve a native business run while its selected inputs are collected."""

from copy import deepcopy
import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from core.database import get_db
from . import process_service
from .process_service import _append_event as append_event, _transition as transition, _start_response as start_response  # pyright: ignore[reportPrivateUsage]
from .bpmn import Workflow, selected_variables
from .models import ProcessRun, ProcessStartJob
from .native_actors import validate_assignments
from .native_definitions import read
from .native_runs import require_run
from .run_participants import participant_agents
from .schemas import ProcessStartResponse
from .values import initialize_variables, normalize_patch, conversational_patch


def waiting_for_inputs(run: ProcessRun) -> bool:
    return run.status == "waiting" and run.engine_metadata.get("input_preparation", {}).get("status") in {"collecting", "ready"}


def _prepared_data(graph: Workflow, values: dict[str, Any]) -> dict[str, Any]:
    selected = normalize_patch(selected_variables(graph, graph.inputs), values, path="process.input")
    return initialize_variables(graph.variables, selected)


async def input_run(agent_id: int, identity: UUID) -> ProcessRun:
    run = await require_run(identity, agent_id)
    if run.launcher_agent_id != agent_id or "input_preparation" not in run.engine_metadata:
        raise PermissionError("This run is not the agent's input preparation")
    return run


async def validate_input_run_replay(agent_id: int, identity: UUID, values: dict[str, Any], *, typed_values: bool = False) -> str:
    """Read an existing receipt without re-opening its now possibly unavailable sources."""
    run = await input_run(agent_id, identity)
    if waiting_for_inputs(run):
        raise ValueError("This run still awaits input completion")
    graph = Workflow.model_validate(run.launch_snapshot["definition"]["graph"])
    checked = conversational_patch(selected_variables(graph, graph.inputs), values, path="process.input", typed_values=typed_values)
    if any(value != run.input.get(name) for name, value in checked.items()):
        raise ValueError("An already released run cannot accept different input values")
    return run.status


async def sync_input_run(*, agent_id: int, workflow_id: str, invocation_key: str,
                         values: dict[str, Any], missing: list[str], issues: dict[str, str], question: str,
                         identity: UUID | None = None, cancelled: bool = False,
                         expected_revision: int | None = None,
                         origins: dict[str, dict[str, Any]] | None = None,
                         resource_metadata: dict[str, dict[str, Any]] | None = None) -> ProcessRun:
    """Mutate in the caller's transaction, alongside its conversation dossier/link."""
    if cancelled and identity is None:
        raise ValueError("Cancellation requires an existing input preparation")
    db = get_db()
    if identity is None:
        definition = await process_service.get_for_agent(agent_id, workflow_id)
        if definition is None or definition.code is None:
            raise PermissionError("An assigned native process is required")
        saved = await read(workflow_id, agent_id)
        graph = Workflow.model_validate(saved["graph"])
        if not graph.typed:
            raise ValueError("Input collection requires a typed native process")
        await validate_assignments(graph, agent_id)
        data = _prepared_data(graph, values)
        snapshot: dict[str, Any] = {"version": 1, "workflow_id": workflow_id,
            "process_label": saved["title"], "tool_code": "galaris", "input": values, "files": [],
            "definition": {key: saved[key] for key in ("xml", "graph", "revision")}}
        snapshot["participant_agents"] = participant_agents(snapshot, agent_id)
        run = ProcessRun(id=uuid4(), process_id=definition.id, launcher_agent_id=agent_id,
            engine_code="galaris", launch_snapshot=snapshot, input={}, data={},
            engine_metadata={}, execution_state={}, data_revision=1, correlation_id=f"proc-{uuid4().hex}",
            idempotency_key=invocation_key, callback_token=secrets.token_urlsafe(42)[:64], status="waiting")
        db.add(run)
        await append_event(run, "run.created", payload={"workflow_id": workflow_id})
    else:
        await input_run(agent_id, identity)
        run = await db.scalar(select(ProcessRun).where(ProcessRun.id == identity)
            .with_for_update().execution_options(populate_existing=True))
        if run is None or not waiting_for_inputs(run):
            raise ValueError("This input preparation is no longer waiting")
        if expected_revision is not None and run.data_revision != expected_revision:
            from .run_data import RunDataConflictError
            raise RunDataConflictError("Process inputs changed concurrently; read them again before updating")
        if run.launch_snapshot["workflow_id"] != workflow_id:
            raise PermissionError("This input preparation belongs to another process")
        graph = Workflow.model_validate(run.launch_snapshot["definition"]["graph"])
        data = _prepared_data(graph, values)
    if cancelled:
        await transition(run, "cancelled", event_type="run.inputs.cancelled")
    else:
        missing = [name for name in graph.inputs if name not in data]
        changed = {name: value for name, value in data.items() if name in graph.inputs and run.input.get(name) != value}
        from .input_provenance import record_inputs
        await record_inputs(run, changed, origins=origins, metadata=resource_metadata)
        run.input = data
        if run.data != data:
            run.data = deepcopy(data)
            if identity is not None:
                run.data_revision += 1
        run.launch_snapshot = {**run.launch_snapshot, "input": data}
        run.engine_metadata = {**run.engine_metadata, "input_preparation": {
            **run.engine_metadata.get("input_preparation", {}),
            "status": "collecting" if missing or issues else "ready", "missing": missing, "names": graph.inputs,
            "issues": issues, "question": question}}
        await append_event(run, "run.inputs.waiting", payload={"missing": missing})
    return run


async def start_input_run(agent_id: int, identity: UUID, values: dict[str, Any], *,
                          typed_values: bool = False, requester_user_id: int | None = None,
                          expected_revision: int | None = None) -> ProcessStartResponse:
    """Release exactly this run after the existing conversation launch permission."""
    await input_run(agent_id, identity)
    db = get_db()
    run = await db.scalar(select(ProcessRun).where(ProcessRun.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    assert run is not None
    definition = await process_service.get_definition(run.process_id)
    if definition is None:
        raise LookupError("Process definition no longer exists")
    if not waiting_for_inputs(run):
        return await start_response(run, definition, deduplicated=True)
    if expected_revision is not None and run.data_revision != expected_revision:
        from .run_data import RunDataConflictError
        raise RunDataConflictError("Process inputs changed before release; read them again")
    if await process_service.get_for_agent(agent_id, run.launch_snapshot["workflow_id"]) is None:
        raise PermissionError("This process is no longer assigned or available")
    graph = Workflow.model_validate(run.launch_snapshot["definition"]["graph"])
    await validate_assignments(graph, agent_id)
    from .facade import validate_launch_input_patch
    declarations = [item.model_dump(mode="json") for item in graph.variables if item.name in graph.inputs]
    supplied = await validate_launch_input_patch(agent_id, declarations, values, typed_values=typed_values)
    data = initialize_variables(graph.variables, supplied, inputs=graph.inputs)
    snapshot = {**run.launch_snapshot, "input": data}
    from app.tools.facade import register_deferred_dispatch
    permit = await register_deferred_dispatch(snapshot)
    if permit is not None:
        snapshot["authorization_permit"] = str(permit)
    run.launch_snapshot = snapshot
    run.input = data
    if run.data != data:
        run.data = deepcopy(data)
        run.data_revision += 1
    run.requester_user_id = requester_user_id
    await transition(run, "queued", event_type="run.inputs.completed")
    run.engine_metadata = {**run.engine_metadata, "input_preparation": {
        **run.engine_metadata["input_preparation"], "status": "completed", "missing": [], "issues": {}}}
    db.add(ProcessStartJob(run_id=run.id))
    await append_event(run, "engine.start.requested", payload={"tool_code": run.engine_code})
    await db.flush()
    return await start_response(run, definition, deduplicated=False)
