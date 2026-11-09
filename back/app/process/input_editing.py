"""Authenticated, deterministic contributions to a reserved run's selected inputs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from fastapi import UploadFile

from app.agent import AgentManagementScope
from core.database import get_db
from core.params import runtime_settings
from core.util import complete_io
from .bpmn import Workflow
from .input_preparation import sync_input_run, waiting_for_inputs, start_input_run
from .native_runs import require_run
from .run_data import RunDataConflictError, lock_run, stage_run_file
from .models import ProcessRun


async def editable_input_run(identity: UUID, actor: AgentManagementScope, revision: int, *, released: bool = False) -> tuple[ProcessRun, Workflow]:
    authorized = await require_run(identity, actor, control=True)
    actor.require(authorized.launcher_agent_id)
    run = await lock_run(identity)
    if not waiting_for_inputs(run) and not released:
        raise RunDataConflictError("This run no longer accepts input contributions")
    if waiting_for_inputs(run) and run.data_revision != revision:
        raise RunDataConflictError("Process inputs changed; refresh before saving")
    return run, Workflow.model_validate(run.launch_snapshot["definition"]["graph"])


async def update_inputs(identity: UUID, actor: AgentManagementScope, values: dict[str, Any], *,
                        expected_revision: int, start: bool = False) -> dict[str, Any]:
    run, graph = await editable_input_run(identity, actor, expected_revision, released=start)
    receipt = {"revision": expected_revision, "actor": actor.user_id,
        "digest": hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()}
    if not waiting_for_inputs(run):
        if run.engine_metadata.get("input_preparation", {}).get("human_start") != receipt:
            raise RunDataConflictError("This run has already been released")
        return {"id": str(identity), "status": run.status, "data": deepcopy(run.data), "revision": run.data_revision}
    from .facade import validate_launch_input_patch, validate_launch_input_fields
    declarations = [item.model_dump(mode="json") for item in graph.variables if item.name in graph.inputs]
    patch = await validate_launch_input_patch(run.launcher_agent_id, declarations, values)
    selected = {name: value for name, value in run.input.items() if name in graph.inputs}
    # Revalidate every selected resource at the boundary, including saved files.
    selected.update(patch)
    resource_metadata: dict[str, dict[str, Any]] = {}
    selected, resource_issues = await validate_launch_input_fields(run.launcher_agent_id, declarations, selected,
        typed_values=True, resource_metadata=resource_metadata)
    previous_issues = run.engine_metadata["input_preparation"].get("issues", {})
    issues = {name: error for name, error in previous_issues.items() if name not in patch}
    issues.update(resource_issues)
    missing = [name for name in graph.inputs if name not in selected]
    if start and (missing or issues):
        raise ValueError("Complete every selected input before starting")
    confirmations = {name: value for name, value in patch.items() if name in selected and run.input.get(name) == value}
    await sync_input_run(agent_id=run.launcher_agent_id, workflow_id=run.launch_snapshot["workflow_id"],
        invocation_key=run.idempotency_key or f"input:{run.id}", values=selected, missing=missing, issues=issues, question="",
        identity=run.id, expected_revision=expected_revision, origins={name: {"kind": "human", "actor_user_id": actor.user_id} for name in patch},
        resource_metadata=resource_metadata)
    from .input_provenance import record_inputs
    await record_inputs(run, confirmations,
        origins={name: {"kind": "human", "actor_user_id": actor.user_id} for name in confirmations}, metadata=resource_metadata)
    # Revision advances for a meaningful contribution; no model proof survives it.
    if patch:
        if run.data_revision == expected_revision and issues != previous_issues:
            # Confirming a valid fallback also changes the accepted input state,
            # even when the bytes equal its previous value. Stale collectors and
            # permission snapshots must observe that human correction.
            run.data_revision += 1
        run.engine_metadata = {**run.engine_metadata, "input_preparation": {
            **run.engine_metadata["input_preparation"], "human_revision": run.data_revision}}
    if start:
        run.engine_metadata = {**run.engine_metadata, "input_preparation": {
            **run.engine_metadata["input_preparation"], "human_start": receipt}}
        await start_input_run(run.launcher_agent_id, run.id, selected, typed_values=True, requester_user_id=actor.user_id)
    await get_db().commit()
    from core import websocket
    await websocket.emit("process_run", "update", {"id": str(identity), "status": run.status}, None)
    return {"id": str(identity), "status": run.status, "data": deepcopy(run.data), "revision": run.data_revision}


async def upload_input(identity: UUID, actor: AgentManagementScope, name: str, upload: UploadFile, *,
                       expected_revision: int) -> dict[str, Any]:
    run, graph = await editable_input_run(identity, actor, expected_revision)
    variable = next((item for item in graph.variables if item.name == name and item.name in graph.inputs), None)
    if variable is None or variable.type != "File":
        raise ValueError("Only a selected File input accepts an upload")
    with TemporaryDirectory(prefix="galaris_input_upload_") as directory:
        path = Path(directory) / "upload"
        size = 0
        with path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
                    raise ValueError("Input upload exceeds its file limit")
                await complete_io(output.write, chunk)
        receipt = await stage_run_file(run, path, name=upload.filename or "file", media_type=upload.content_type or "application/octet-stream")
    return await update_inputs(identity, actor, {name: receipt["uri"]}, expected_revision=expected_revision)
