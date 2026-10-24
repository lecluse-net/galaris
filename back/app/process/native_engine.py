"""Short, durable BPMN scheduling passes. No Python recursion across process calls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
import json
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from app.task import TaskCreate, TaskStatus, task_service, get_task_outcome_observation
from core.database import get_db

from . import process_service
from .bpmn import Node, Workflow, decision_activity
from .llm_decisions import simple_llm, observe_decision, stop_decision
from .values import normalize, validate_values, loads_values, unwrap, external_outputs, ValueContractError
from .expressions import evaluate, resolve
from .engine import ProcessEngineError
from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from .run_data import (integrate_workflow_values, workflow_attachment_receipt,
    create_workflow_attachment, read_run_workspace, initialize_run_data)
from .schemas import (EngineError, EngineProcessDefinition, EngineRunReference, EngineRunSnapshot,
                      EngineStartResult, ProcessEngineHealth, ProcessStartPayload, ProcessFileInput)


def now() -> datetime:
    return datetime.now(timezone.utc)


def local_graph(run: ProcessRun, occurrence: ProcessNodeRun) -> Workflow:
    # Keep frozen activity identities for cancellation and lost-receipt recovery.
    # Definition editing separately removes retired, unreachable recovery paths.
    frozen: dict[str, Any] = deepcopy(run.launch_snapshot["definition"]["graph"])
    pending = [frozen]
    while pending:
        body = pending.pop()
        body.pop("error_handler", None)
        for node in cast(list[dict[str, Any]], body.get("nodes", [])):
            cast(dict[str, Any], node.get("config", {})).pop("catch", None)
            if isinstance(node.get("body"), dict):
                pending.append(cast(dict[str, Any], node["body"]))
    graph = Workflow.model_validate(frozen)
    for key in occurrence.context.get("body_path", []):
        body = graph.node(key).body
        if body is None:
            raise ValueError("Subprocess graph is missing")
        if body.execution_agent_id is None:
            body.execution_agent_id = graph.execution_agent_id
        graph = body
    return graph


def enqueue(run: ProcessRun, node_key: str, context: dict[str, Any], *, occurrence: UUID | None = None) -> ProcessNodeRun:
    identity = occurrence or uuid4()
    state = deepcopy(run.engine_metadata.get("native", {}))
    order = int(state.get("frontier_sequence", 0)) + 1
    state["frontier_sequence"] = order
    run.engine_metadata = {**run.engine_metadata, "native": state}
    node = ProcessNodeRun(id=identity, run_id=run.id, node_key=node_key,
        occurrence=str(identity), admission_order=order, status="ready", context=deepcopy(context))
    get_db().add(node)
    return node


def expression_context(occurrence: ProcessNodeRun) -> dict[str, Any]:
    return occurrence.context.get("values", {})


def snapshot(run: ProcessRun) -> EngineRunSnapshot:
    state = run.engine_metadata.get("native", {})
    status = state.get("status", run.status)
    return EngineRunSnapshot(status=status, engine_run_id=str(run.id),
        output=state.get("output"), error=EngineError(**state["error"]) if state.get("error") else None,
        raw={"paused": state.get("paused", False)})


class NativeProcessEngine:
    code = "galaris"
    supports_cancel = True
    cancel_mode = "supported"
    start_timeout_seconds = 30.0
    refresh_timeout_seconds = 45.0

    async def health(self) -> ProcessEngineHealth:
        return ProcessEngineHealth(tool_code=self.code, status="healthy", reachable=True,
            authenticated=True, supports_cancel=True, cancel_mode="supported",
            message="Durable internal BPMN engine", checked_at=now())

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return []

    async def prepare_input(self, agent_id: int, workflow_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return input_data

    async def start_run(self, engine_process_id: str, run: EngineRunReference, payload: ProcessStartPayload) -> EngineStartResult:
        try:
            return await self._start_run(engine_process_id, run, payload)
        except Exception as error:
            code = error.code if isinstance(error, ProcessEngineError) else "process_start_failed"
            raise ProcessEngineError(code, str(error), retryable=False) from error

    async def _start_run(self, engine_process_id: str, run: EngineRunReference, payload: ProcessStartPayload) -> EngineStartResult:
        # Admission already froze current content. Prepare durable input copies
        # before creating the frontier; business activities are admitted later.
        record = await get_db().get(ProcessRun, run.id)
        if record is None:
            raise ValueError("Process run not found")
        if record.status in process_service.TERMINAL_STATUSES or record.engine_metadata.get("native", {}).get("initialized"):
            return EngineStartResult(accepted=True, engine_run_id=str(run.id))
        graph = Workflow.model_validate(record.launch_snapshot["definition"]["graph"])
        initial_files = [{key: item[key] for key in ("uri", "description") if key in item}
            for item in record.launch_snapshot.get("files", [])] if graph.typed else []
        await initialize_run_data(record.id, initial_files)
        files = initial_files if graph.typed else await self._prepare_files(record)
        record = await self._lock(run.id)
        if files is None or record.status in process_service.TERMINAL_STATUSES or record.engine_metadata.get("native", {}).get("cancel_requested"):
            await get_db().commit()
            return EngineStartResult(accepted=True, engine_run_id=str(run.id))
        if not record.engine_metadata.get("native", {}).get("initialized"):
            controls: dict[str, Any] = record.engine_metadata.get("native", {})
            record.engine_metadata = {**record.engine_metadata, "native": {"schema": 1, "status": "running",
                "paused": False, "breakpoints": [], **controls, "initialized": True,
                "sequence": 1}}
            start = next(node for node in graph.nodes if node.kind == "start")
            enqueue(record, start.id, {"body_path": [], "forks": [], "values": {
                "input": record.input, "data": record.input, "results": {}, "files": files}})
            await get_db().commit()
        return EngineStartResult(accepted=True, engine_run_id=str(run.id))

    async def _workspace_values(self, run: ProcessRun, occurrence: ProcessNodeRun) -> dict[str, Any]:
        data, files = await read_run_workspace(run.id)
        if local_graph(run, occurrence).typed:
            data = validate_values(data, path="process.data")
        values = {**expression_context(occurrence), "input": run.input, "data": data, "files": files}
        occurrence.context = {**occurrence.context, "values": values}
        return values

    async def _prepare_files(self, record: ProcessRun) -> list[dict[str, Any]] | None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from app.file_share import ResourceContext, materialize_resource, parse_resource_uri
        from app.console import build_run_resource
        prepared: list[dict[str, Any]] = []
        for item in record.launch_snapshot.get("files", []):
            record = await self._lock(record.id)
            stopped = record.status in process_service.TERMINAL_STATUSES or record.engine_metadata.get("native", {}).get("cancel_requested")
            await get_db().commit()
            if stopped:
                return None
            key = str(item["id"])
            receipt = await workflow_attachment_receipt(record.id, key)
            if receipt is None:
                console = await build_run_resource(record.launcher_agent_id) if parse_resource_uri(item["uri"]).scheme == "console" else None
                try:
                    context = ResourceContext(agent_id=record.launcher_agent_id, runtime=item.get("runtime", "internal"),
                        task_id=record.task_id, console_resource=console)
                    with TemporaryDirectory(prefix="galaris_process_input_") as directory:
                        path = Path(directory) / "source"
                        source = await materialize_resource(context, item["uri"], path, max_bytes=process_service.PROCESS_FILE_MAX_BYTES)
                        record = await self._lock(record.id)
                        if record.status in process_service.TERMINAL_STATUSES or record.engine_metadata.get("native", {}).get("cancel_requested"):
                            await get_db().commit()
                            return None
                        receipt = await create_workflow_attachment(record.id, key=key, source_uri=item["uri"],
                            path=path, name=source.name, media_type=source.media_type)
                finally:
                    if console is not None:
                        await console.close()
            prepared.append({**receipt, "slot": item.get("slot"), "description": item.get("description", "")})
        return prepared

    async def _lock(self, identity: UUID) -> ProcessRun:
        run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == identity)
            .with_for_update().execution_options(populate_existing=True))
        if run is None:
            raise ValueError("Process run not found")
        return run

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        reference = run
        record = await self._lock(reference.id)
        if record.engine_metadata.get("native", {}).get("cancel_requested"):
            await get_db().commit()
            return await self.cancel_run(reference)
        if not record.engine_metadata.get("native", {}).get("initialized") or record.status in process_service.TERMINAL_STATUSES:
            await get_db().commit()
            return snapshot(record)
        state: dict[str, Any] = deepcopy(record.engine_metadata["native"])
        if state.get("lease_until") and datetime.fromisoformat(state["lease_until"]) > now():
            await get_db().commit()
            return snapshot(record)
        claim = uuid4().hex
        state.update(lease=claim, lease_until=(now() + timedelta(seconds=120)).isoformat())
        record.engine_metadata = {**record.engine_metadata, "native": state}
        await get_db().commit()
        try:
            if state.get("status") in process_service.TERMINAL_STATUSES:
                occurrences = []
            else:
                occurrences = await self._frontier(record.id, claim)
            for occurrence in occurrences:
                if occurrence.status not in {"ready", "waiting"}:
                    continue
                current = await self._fenced(record.id, claim)
                if current is None:
                    break
                state = deepcopy(current.engine_metadata["native"])
                if state.get("cancel_requested"):
                    break
                if state.get("status") in process_service.TERMINAL_STATUSES:
                    break
                # Active effects finish under pause. A step admits one occurrence;
                # its composite descendants are admitted until its own completion.
                if occurrence.status == "ready":
                    if await self._ancestor_paused(current):
                        await get_db().commit()
                        continue
                    step = state.get("step_root")
                    descendant = step is not None and str(step) in occurrence.context.get("ancestors", [])
                    if state.get("paused") and not descendant and not state.get("step_pending"):
                        continue
                    if occurrence.node_key in state.get("breakpoints", []) and not descendant and not state.get("step_pending") and state.get("breakpoint_skip") != str(occurrence.id):
                        state["paused"] = True
                        state["breakpoint_hit"] = str(occurrence.id)
                        current.engine_metadata = {**current.engine_metadata, "native": state}
                        await get_db().commit()
                        continue
                    if state.get("breakpoint_skip") == str(occurrence.id):
                        state.pop("breakpoint_skip", None)
                        state.pop("breakpoint_hit", None)
                        current.engine_metadata = {**current.engine_metadata, "native": state}
                    if state.get("step_pending"):
                        state.update(step_pending=False, step_root=str(occurrence.id), paused=True)
                        current.engine_metadata = {**current.engine_metadata, "native": state}
                        await get_db().commit()
                await self._advance(current, occurrence, claim)
                current = await self._fenced(reference.id, claim)
                if current is None or current.engine_metadata["native"].get("cancel_requested") or current.engine_metadata["native"].get("status") != "running":
                    break
            current = await self._fenced(record.id, claim)
            if current is not None:
                state = deepcopy(current.engine_metadata["native"])
                if not state.get("paused") and not await self._ancestor_paused(current) and state.get("status") == "running":
                    pending = list(await get_db().scalars(select(ProcessNodeRun).where(
                        ProcessNodeRun.run_id == current.id, ProcessNodeRun.status.in_(("ready", "waiting")))))
                    if pending and all(item.status == "waiting" and (local_graph(current, item).node(item.node_key).kind in {"parallel", "for", "while"}
                        or local_graph(current, item).typed and len(local_graph(current, item).incoming(item.node_key)) > 1
                        and not item.context.get("converged")) for item in pending):
                        state.update(status="error", error={"code": "unmatched_parallel_join",
                            "message": "Parallel convergence cannot receive the remaining branches"})
                state.pop("lease", None)
                state.pop("lease_until", None)
                current.engine_metadata = {**current.engine_metadata, "native": state}
                await get_db().commit()
                return snapshot(current)
            return snapshot(await self._lock(record.id))
        except Exception:
            # A committed intent is deliberately retained. Task admission is
            # idempotent; ambiguous tool effects are never blindly repeated.
            await get_db().rollback()
            current = await self._fenced(reference.id, claim)
            if current is not None:
                state = deepcopy(current.engine_metadata["native"])
                state.pop("lease", None)
                state.pop("lease_until", None)
                current.engine_metadata = {**current.engine_metadata, "native": state}
                await get_db().commit()
            raise

    async def _frontier(self, identity: UUID, claim: str) -> list[ProcessNodeRun]:
        """Rotate a bounded snapshot of the frontier, including waiting effects.

        New admissions join the next cycle. They cannot indefinitely overtake
        older work, and waiting rows cannot monopolize the first batch.
        """
        current = await self._fenced(identity, claim)
        if current is None:
            return []
        state = deepcopy(current.engine_metadata["native"])
        cutoff = int(state.get("frontier_cutoff", state.get("frontier_sequence", 0)))
        cursor = int(state.get("frontier_cursor", 0))

        async def batch() -> list[ProcessNodeRun]:
            return list(await get_db().scalars(select(ProcessNodeRun).where(
                ProcessNodeRun.run_id == identity, ProcessNodeRun.status.in_(("ready", "waiting")),
                ProcessNodeRun.admission_order > cursor, ProcessNodeRun.admission_order <= cutoff,
            ).order_by(ProcessNodeRun.admission_order, ProcessNodeRun.id).limit(50)))

        occurrences = await batch()
        if not occurrences:
            cursor = 0
            cutoff = int(state.get("frontier_sequence", 0))
            occurrences = await batch()
        state.update(frontier_cursor=occurrences[-1].admission_order if occurrences else 0, frontier_cutoff=cutoff)
        current.engine_metadata = {**current.engine_metadata, "native": state}
        await get_db().commit()
        return occurrences

    async def _ancestor_paused(self, run: ProcessRun) -> bool:
        """Walk persisted ancestry iteratively; never recurse through engine calls."""
        child = run
        while child.parent_run_id is not None:
            parent = await get_db().get(ProcessRun, child.parent_run_id)
            if parent is None:
                raise ValueError("Parent process run is missing")
            state: dict[str, Any] = parent.engine_metadata.get("native", {})
            if state.get("paused"):
                caller = await get_db().get(ProcessNodeAttempt, child.caller_node_attempt_id) if child.caller_node_attempt_id else None
                node = await get_db().get(ProcessNodeRun, caller.node_run_id) if caller else None
                step = state.get("step_root")
                if node is None or step is None or step != str(node.id) and step not in node.context.get("ancestors", []):
                    return True
            child = parent
        return False

    async def _fenced(self, identity: UUID, claim: str) -> ProcessRun | None:
        record = await self._lock(identity)
        if record.status in process_service.TERMINAL_STATUSES or record.engine_metadata.get("native", {}).get("lease") != claim:
            await get_db().commit()
            return None
        return record

    async def _advance(self, run: ProcessRun, occurrence: ProcessNodeRun, claim: str) -> None:
        graph = local_graph(run, occurrence)
        node = graph.node(occurrence.node_key)
        run_id, occurrence_id = run.id, occurrence.id
        values = deepcopy(expression_context(occurrence))
        try:
            if occurrence.context.get("handling_error"):
                raise ValueError("Legacy recovery activities are no longer executed")
            if graph.typed and node.kind != "parallel" and len(graph.incoming(node.id)) > 1 and not occurrence.context.get("converged"):
                if not await self._join(run, occurrence, graph, claim, admit_activity=True):
                    return
            values = await self._workspace_values(run, occurrence)
            if node.kind == "if" and node.config.get("mode") is not None:
                result = await self._effect(run, occurrence, decision_activity(node), claim)
                if result is None:
                    return
                decision = unwrap(result["decision"])
                if type(decision) is not bool:
                    raise ValueError("An IF result must be a boolean")
                values["decision"] = decision
                values["output"] = result
            if node.kind in {"task", "human_task", "call", "tool_call", "rest", "code", "program"}:
                result = await self._effect(run, occurrence, node, claim)
                if result is None:
                    return
                if graph.typed:
                    current = await self._fenced(run.id, claim)
                    if current is None or current.engine_metadata.get("native", {}).get("cancel_requested"):
                        return
                    changes = result
                    output_files: list[dict[str, Any]] = occurrence.context.get("output_files", [])
                    remove: list[str] = []
                    files_mode: Literal["append", "replace"] = "append"
                    if "postprocess" in node.config:
                        changes = {}
                        output_files = []
                        if node.config["postprocess"].strip():
                            transformed = await self._code_phase(run, occurrence, node, claim, "postprocess", node.config["postprocess"], {
                                "data": deepcopy(occurrence.context["integration_baseline"]), "files": deepcopy(occurrence.context.get("input_files", [])),
                                "output": result, "output_files": occurrence.context.get("output_files", [])})
                            if transformed is None:
                                return
                            new_data = validate_values(transformed.get("data", {}), path=f"{node.id}.postprocess.data")
                            baseline: dict[str, Any] = occurrence.context["integration_baseline"]
                            changes = {key: value for key, value in new_data.items() if key not in baseline or baseline[key] != value}
                            remove = list(set(baseline) - set(new_data))
                            output_files = self._file_references(transformed.get("files", []))
                            files_mode = "replace"
                    # Result and intent are already durable. Repeating this port
                    # after a lost acknowledgement never runs the activity again.
                    candidate = {**values["data"], **changes}
                    for name in remove:
                        candidate.pop(name, None)
                    validate_values(candidate, path=f"{node.id}.data")
                    await integrate_workflow_values(run.id,
                        command=f"activity:{occurrence.id}", baseline=occurrence.context["integration_baseline"],
                        changes=changes, files=output_files, remove=remove, files_mode=files_mode,
                        baseline_files=occurrence.context.get("input_files", []))
                values["output"] = result
                values.setdefault("results", {})[node.id] = result
                values = {**await self._workspace_values(run, occurrence), "output": result,
                    "results": values["results"]}
            if node.kind in {"for", "while"}:
                await self._loop(run, occurrence, node, claim)
                return
            if node.kind == "parallel" and len(graph.incoming(node.id)) > 1:
                await self._join(run, occurrence, graph, claim)
                return
            if node.kind == "end":
                await self._end(run, occurrence, graph, values, claim)
                return
            await self._complete(run, occurrence, graph, values, claim)
        except Exception as error:
            if isinstance(error, SQLAlchemyError) or not get_db().is_active:
                await get_db().rollback()
            current = await self._fenced(run_id, claim)
            if current is None:
                return
            reloaded = await get_db().get(ProcessNodeRun, occurrence_id)
            if reloaded is None:
                return
            occurrence = reloaded
            occurrence.status = "error"
            occurrence.finished_at = now()
            state = deepcopy(current.engine_metadata["native"])
            attempt = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == occurrence.id)
                .order_by(ProcessNodeAttempt.number.desc()).limit(1))
            if node.kind in {"tool_call", "rest", "program"} and attempt is not None and attempt.status == "started":
                occurrence.status = "unknown"
                occurrence.finished_at = None
                state.update(status="cancelling", paused=True, cancel_requested=True, failure=True,
                    error={"code": "effect_outcome_unknown", "message": str(error), "node_name": node.id})
                current.engine_metadata = {**current.engine_metadata, "native": state}
                await get_db().commit()
                return
            state.update(status="cancelling", cancel_requested=True, failure=True,
                error={"code": error.code if isinstance(error, ProcessEngineError) else "node_failed",
                    "message": str(error), "node_name": node.id})
            current.engine_metadata = {**current.engine_metadata, "native": state}
            await get_db().commit()

    async def _effect(self, run: ProcessRun, occurrence: ProcessNodeRun, node: Node, claim: str) -> dict[str, Any] | None:
        attempt = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == occurrence.id)
            .order_by(ProcessNodeAttempt.number.desc()).limit(1).execution_options(populate_existing=True))
        if attempt is not None and attempt.status == "failed" and local_graph(run, occurrence).typed:
            raise ProcessEngineError("node_failed", attempt.error or "Activity failed")
        if attempt is not None and attempt.status == "failed" and node.kind == "tool_call" and attempt.task_id:
            await task_service.complete_workflow_operation(attempt.task_id, attempt.receipt or {},
                error=attempt.error or "Tool activity failed")
        if attempt is None or attempt.status == "failed":
            # Recheck live sharing before admitting another effect. Already
            # accepted effects retain their receipt and are still observed.
            from .native_definitions import get as get_definition
            actor: Any = run.launcher_agent_id
            if run.requester_user_id is not None:
                from app.agent import management_scope_for
                from core.user import get_user_record
                user = await get_user_record(run.requester_user_id)
                if user is None or not user.is_active:
                    raise PermissionError("The human workflow launcher is inactive")
                actor = await management_scope_for(user, get_db())
                actor.require(run.launcher_agent_id)
            await get_definition(str(run.launch_snapshot["workflow_id"]), actor)
            from .native_actors import validate_assignments
            await validate_assignments(local_graph(run, occurrence), actor)
            previous = attempt
            workspace = occurrence.context.get("preparation_snapshot")
            if workspace is None:
                workspace = await self._workspace_values(run, occurrence)
                if local_graph(run, occurrence).typed:
                    occurrence.context = {**occurrence.context, "preparation_snapshot": deepcopy(workspace)}
                    occurrence.status = "waiting"
                    await get_db().commit()
            inputs: Any = resolve(node.config.get("input", {"$expr": "data"}), workspace) if node.kind in {"tool_call", "program"} else workspace["data"]
            typed = local_graph(run, occurrence).typed
            if typed:
                assert node.inputs is not None
                inputs = resolve(node.config.get("input_mapping", {"$expr": "data"}), workspace)
                input_files = workspace["files"]
                if "preprocess" in node.config:
                    inputs = {}
                    input_files = []
                    if node.config["preprocess"].strip():
                        transformed = await self._code_phase(run, occurrence, node, claim, "preprocess", node.config["preprocess"],
                            {"data": workspace["data"], "files": workspace["files"], "input": {}, "input_files": []})
                        if transformed is None:
                            return None
                        inputs = transformed.get("input", {})
                        input_files = self._file_references(transformed.get("input_files", []))
                inputs = normalize(node.inputs, inputs, path=f"{node.id}.input", allow_extra=True)
                if local_graph(run, occurrence).node(node.id).kind == "if" and node.config.get("mode") is not None:
                    inputs = validate_values(workspace["data"], path=f"{node.id}.dataset")
                occurrence.context = {**occurrence.context, "integration_baseline": deepcopy(workspace["data"]),
                    "input_files": deepcopy(input_files)}
            if not isinstance(inputs, dict):
                raise ValueError("Activity input must be an object")
            attempt = ProcessNodeAttempt(id=uuid4(), node_run_id=occurrence.id, number=previous.number + 1 if previous else 1,
                input=inputs, status="intent")
            if node.kind in {"task", "human_task"}:
                prompt = str(node.config["prompt"])
                if typed:
                    prompt += "\n\nActivity inputs (typed JSON, immutable):\n" + json.dumps(inputs, ensure_ascii=False)
                    prompt += "\nExpected output variables (type, nullable, optional default):\n" + json.dumps(
                        [item.model_dump(mode="json") for item in node.outputs or []], ensure_ascii=False)
                    prompt += "\nFile values are canonical file_share URIs, never bytes or local paths."
                    if node.kind != "task":
                        prompt += "\nWork only on these local inputs. Return only the typed JSON object of output variables, without prose or Markdown fences."
                    if node.kind == "task":
                        prompt += "\nRun data context (typed JSON, read-only):\n" + json.dumps(workspace["data"], ensure_ascii=False)
                        prompt += ("\nUse process_activity_complete(output={...}, message='...') to submit ordinary JSON values "
                            "matching the declared outputs; the engine applies their types. Do not encode the result in final prose. "
                            "If human information is needed, call process_activity_question(question='...', variables=[...]) "
                            "and stop this turn. That call sends the question and durably waits for the authenticated requester. "
                            "On resumption use the supplied answer, continue work, and call process_activity_complete. "
                            "A nullable output is not permission to skip requested information. "
                            "Never merely write a question as your final answer. A final message alone does not contact the human.")
                    prompt += "\nLocal input files (canonical URIs):\n" + json.dumps(occurrence.context["input_files"], ensure_ascii=False)
                else:
                    prompt = self._legacy_prompt(prompt, run, node, cast(dict[str, Any], inputs), workspace)
                attempt.prompt = prompt
            if node.kind == "human_task":
                assigned = next(item for item in local_graph(run, occurrence).actors if item.id == node.config["actor"])
                occurrence.context = {**occurrence.context, "human_user_id": assigned.user_id,
                    "human_title": node.title or node.id, "human_request_sent": None,
                    "human_request_retry_at": None, "human_request_closed": None}
                attempt.status = "human_waiting"
            occurrence.status = "waiting"
            occurrence.started_at = now()
            get_db().add(attempt)
            await get_db().commit()
        if attempt.status == "completed":
            if node.kind == "tool_call" and attempt.task_id:
                await task_service.complete_workflow_operation(attempt.task_id, attempt.receipt or {})
            return attempt.receipt
        return await self._execute_effect(run, occurrence, node, attempt, claim)

    def _legacy_prompt(self, prompt: str, run: ProcessRun, node: Node, inputs: dict[str, Any], workspace: dict[str, Any]) -> str:
        prompt += f"\n\nShared run data: galaris://processes/runs/{run.id}/data"
        prompt += f"\nShared attachments: galaris://processes/runs/{run.id}/attachments/"
        if node.kind == "human_task":
            prompt += "\nAll tasks in this run share its data and attachments. Submit the activity result through the process response."
        else:
            prompt += "\nAll tasks in this run use this same workspace. Read its current JSON with file_read and update it with file_write or file_edit, using expected_revision. If a revision conflicts, reread and preserve other tasks' changes before retrying. Add or read shared files in the attachments collection. Store your work there; your final message is only a completion summary."
        prompt += "\nCurrent shared data (JSON):\n" + json.dumps(inputs, ensure_ascii=False)
        prompt += "\nCurrent files (canonical URIs):\n" + json.dumps(workspace["files"], ensure_ascii=False)
        if "item" in workspace or "index" in workspace:
            prompt += "\nLoop context (JSON):\n" + json.dumps({key: workspace[key] for key in ("item", "index") if key in workspace}, ensure_ascii=False)
        return prompt

    async def _execute_effect(self, run: ProcessRun, occurrence: ProcessNodeRun, node: Node,
                              attempt: ProcessNodeAttempt, claim: str) -> dict[str, Any] | None:
        from .native_actors import execution_agent
        graph = local_graph(run, occurrence)
        assigned_agent = execution_agent(graph, node, run.launcher_agent_id)
        current = await self._fenced(run.id, claim)
        if current is None or current.engine_metadata.get("native", {}).get("cancel_requested"):
            await get_db().commit()
            return None
        if graph.typed and attempt.status == "returned":
            assert node.outputs is not None
            raw_output = (attempt.receipt or {})["output"]
            if node.kind == "rest" and raw_output["status_code"] >= 400:
                raise ProcessEngineError("rest_http_error", f"REST API returned HTTP {raw_output['status_code']}")
            mapped = resolve(node.config.get("external_output", {"$expr": "result"}),
                {"result": raw_output})
            result = external_outputs(node.outputs, mapped, path=f"{node.id}.output", typed_values=node.config.get("external_output_typed", False))
            attempt.status = "completed"
            attempt.receipt = result
            attempt.finished_at = now()
            await get_db().commit()
            if node.kind == "tool_call" and attempt.task_id:
                await task_service.complete_workflow_operation(attempt.task_id, result)
            return result
        if node.kind == "human_task":
            return None
        if graph.typed and node.kind == "tool_call":
            if attempt.status in {"started", "claiming"}:
                until = (attempt.receipt or {}).get("lease_until")
                if until and datetime.fromisoformat(until) > now():
                    return None
                if attempt.status == "started":
                    raise ProcessEngineError("effect_outcome_unknown", "Tool outcome is unknown; reconcile before retrying")
            if attempt.status == "tool_ready":
                return None
            if attempt.status == "authorization":
                from app.tools.facade import authorization_status
                authorization = (attempt.receipt or {}).get("authorization", {})
                if await authorization_status(UUID(str(authorization["request_id"])), agent_id=assigned_agent) == "pending":
                    return None
                task = await task_service.get_by_id(attempt.task_id) if attempt.task_id else None
                if task is not None and task_service.is_held_by_user(task):
                    return None
            if attempt.task_id is None:
                task = await task_service.create(TaskCreate(label=(node.title or node.id)[:400],
                    agent_id=assigned_agent, requester_agent_id=run.launcher_agent_id, ai=False, paused=True,
                    status=TaskStatus.DISPATCH, source_task_id=run.task_id,
                    data={"process_run_id": str(run.id), "workflow_operation": True, "pause_reasons": ["workflow_operation"]}),
                    idempotency_key=f"process-tool:{attempt.id}", requester_user_id=run.requester_user_id)
                if await self._fenced(run.id, claim) is None:
                    return None
                attempt.task_id = task.id
            plain_input = {key: unwrap(value) for key, value in attempt.input.items()}
            arguments = resolve(node.config.get("tool_arguments", {"$expr": "input"}), {"input": plain_input})
            if not isinstance(arguments, dict):
                raise ValueError(f"{node.id}: Tool arguments must be an object")
            attempt.receipt = {**(attempt.receipt or {}), "arguments": arguments}
            attempt.status = "tool_ready"
            await get_db().commit()
            return None
        if node.kind == "task" and simple_llm(node):
            result = await observe_decision(run, occurrence, node, attempt, assigned_agent,
                lambda: self._fenced(run.id, claim))
            if result is None:
                return None
        elif node.kind == "task":
            question = occurrence.context.get("activity_question", {})
            if question.get("status") == "pending":
                task = await task_service.get_by_id(attempt.task_id) if attempt.task_id else None
                if task is None or task.agent_id is None or task.status == TaskStatus.ERROR:
                    raise ProcessEngineError("human_input_cancelled", "The activity awaiting human input was stopped")
                if question.get("wait_task_id"):
                    from app.task.facade import replace_legacy_input_wait
                    await replace_legacy_input_wait(task_id=task.id, agent_id=task.agent_id,
                        request_key=question["id"], wait_task_id=UUID(question["wait_task_id"]))
                    occurrence.context = {**occurrence.context, "activity_question": {
                        key: value for key, value in question.items() if key != "wait_task_id"}}
                    await get_db().commit()
                return None
            if attempt.task_id is None:
                from .native_actors import execution_agent
                assigned_agent = execution_agent(local_graph(run, occurrence), node, run.launcher_agent_id)
                task = await task_service.create(TaskCreate(label=(node.title or node.id)[:400],
                    objective="<p>" + escape(attempt.prompt or "") + "</p>", agent_id=assigned_agent,
                    requester_agent_id=run.launcher_agent_id, status=TaskStatus.DISPATCH, ai=True,
                    forced_route="EXEC", source_task_id=run.task_id,
                    data={"process_run_id": str(run.id), "process_node_run_id": str(occurrence.id)}),
                    idempotency_key=f"process-node:{attempt.id}", requester_user_id=run.requester_user_id)
                if await self._fenced(run.id, claim) is None:
                    return None
                attempt.task_id = task.id
                attempt.status = "accepted"
                await get_db().commit()
            observation = await get_task_outcome_observation(attempt.task_id)
            if observation is None or observation.status not in {"SUCCESS", "ERROR"}:
                return None
            if observation.status == "ERROR":
                task = await task_service.get_by_id(attempt.task_id)
                if task is not None and task.lease_owner:
                    return None
                attempt.status = "failed"
                attempt.error = observation.error
                attempt.finished_at = now()
                await get_db().commit()
                raise ValueError(observation.error or "Task failed")
            if graph.typed:
                submitted = occurrence.context.get("activity_result")
                if submitted is not None:
                    result: Any = submitted["output"]
                    summary = submitted["message"] or observation.result
                elif not node.outputs:
                    result = {}
                    summary = observation.result
                else:
                    try:
                        result = loads_values(observation.result or "{}", path=f"{node.id}.output")
                    except ValueContractError as error:
                        raise ValueError(f"{error}. The activity must submit its declared outputs with process_activity_complete(output={{...}}).") from error
                    summary = ""
                if summary:
                    occurrence.context = {**occurrence.context, "activity_summary": summary[:12_000]}
            else:
                result = {"text": observation.result}
        elif node.kind == "call":
            if attempt.child_run_id is None:
                workspace = await self._workspace_values(run, occurrence)
                file_values = occurrence.context.get("input_files", workspace["files"]) if graph.typed else workspace["files"]
                if not isinstance(file_values, list):
                    raise ValueError("Child process files must be a list of canonical URI references")
                forwarded: list[ProcessFileInput] = []
                for file_value in cast(list[Any], file_values):
                    if not isinstance(file_value, dict):
                        raise ValueError("Every child process file requires a canonical URI")
                    item = cast(dict[str, Any], file_value)
                    if not isinstance(item.get("uri"), str):
                        raise ValueError("Every child process file requires a canonical URI")
                    forwarded.append(ProcessFileInput(uri=item["uri"], slot=item.get("slot"),
                        description=str(item.get("description") or "")))
                response = await process_service.start_process(agent_id=assigned_agent,
                    workflow_id=str(node.config["process_code"]), input_data=attempt.input if graph.typed else workspace["data"],
                    files=forwarded,
                    idempotency_key=f"process-node:{attempt.id}", requester_user_id=run.requester_user_id,
                    parent_run_id=run.id, root_run_id=run.root_run_id or run.id, caller_node_attempt_id=attempt.id,
                    typed_input=graph.typed)
                current = await self._fenced(run.id, claim)
                if current is None:
                    return None
                child = await get_db().get(ProcessRun, response.run_id)
                assert child is not None
                child.parent_run_id = run.id
                child.root_run_id = run.root_run_id or run.id
                attempt.child_run_id = child.id
                attempt.status = "accepted"
                await get_db().commit()
            child = await process_service.get_run(attempt.child_run_id)
            if child is None or child.status not in process_service.TERMINAL_STATUSES:
                return None
            if child.status != "success":
                attempt.status = "failed"
                attempt.error = child.error_message or child.status
                attempt.finished_at = now()
                await get_db().commit()
                raise ProcessEngineError(child.error_code or "child_process_failed", child.error_message or "Child process failed")
            result = child.output or {}
            if graph.typed:
                child_typed = child.launch_snapshot.get("definition", {}).get("graph", {}).get("schema_version") == "galaris.bpmn/v2"
                if child_typed:
                    _, child_files = await read_run_workspace(child.id)
                    occurrence.context = {**occurrence.context, "output_files": deepcopy(child_files)}
                else:
                    assert node.outputs is not None
                    mapped = resolve(node.config.get("external_output", {"$expr": "result"}), {"result": result})
                    result = external_outputs(node.outputs, mapped, path=f"{node.id}.output", typed_values=node.config.get("external_output_typed", False))
        elif node.kind == "tool_call":
            if attempt.status == "started":
                raise ValueError("Tool effect outcome is unknown; reconcile it before retrying")
            from app.tools.facade import execute_workflow_tool
            if attempt.status == "authorization":
                from app.tools.facade import authorization_status
                authorization = (attempt.receipt or {}).get("authorization", {})
                if await authorization_status(UUID(str(authorization["request_id"])), agent_id=assigned_agent) == "pending":
                    return None
            if attempt.task_id is None:
                task = await task_service.create(TaskCreate(label=(node.title or node.id)[:400],
                    agent_id=assigned_agent, requester_agent_id=run.launcher_agent_id,
                    ai=False, paused=True, status=TaskStatus.DISPATCH,
                    source_task_id=run.task_id,
                    data={"process_run_id": str(run.id), "workflow_operation": True,
                        "pause_reasons": ["workflow_operation"]}),
                    idempotency_key=f"process-tool:{attempt.id}", requester_user_id=run.requester_user_id)
                if await self._fenced(run.id, claim) is None:
                    return None
                attempt.task_id = task.id
            if run.engine_metadata.get("native", {}).get("cancel_requested"):
                await get_db().commit()
                return None
            async with task_service.workflow_operation(attempt.task_id) as admitted:
                if not admitted:
                    return None
                attempt.status = "started"
                await get_db().commit()
                arguments = attempt.input
                if graph.typed:
                    plain_input = {key: unwrap(value) for key, value in attempt.input.items()}
                    arguments = resolve(node.config.get("tool_arguments", {"$expr": "input"}), {"input": plain_input})
                    if not isinstance(arguments, dict):
                        raise ValueError(f"{node.id}: Tool arguments must be an object")
                receipt = await execute_workflow_tool(agent_id=assigned_agent, task_id=attempt.task_id,
                    tool_name=str(node.config.get("tool", "")), arguments=cast(dict[str, Any], arguments), operation_id=attempt.id,
                    continuation=(attempt.receipt or {}).get("authorization", {}).get("continuation"))
                if await self._fenced(run.id, claim) is None:
                    return None
                if receipt["status"] == "waiting":
                    attempt.status = "authorization"
                    attempt.receipt = receipt
                    await get_db().commit()
                    await task_service.suspend_workflow_operation(attempt.task_id)
                    return None
                if receipt["status"] == "rejected":
                    attempt.status = "failed"
                    attempt.receipt = receipt
                    attempt.error = str(receipt.get("error", "Tool authorization was denied or expired"))
                    attempt.finished_at = now()
                    await get_db().commit()
                    await task_service.complete_workflow_operation(attempt.task_id, receipt, error=attempt.error)
                    raise PermissionError(attempt.error)
            result = receipt["output"]
            if graph.typed:
                attempt.status = "returned"
                attempt.receipt = {"output": result}
                await get_db().commit()
                assert node.outputs is not None
                mapped = resolve(node.config.get("external_output", {"$expr": "result"}), {"result": result})
                result = external_outputs(node.outputs, mapped, path=f"{node.id}.output", typed_values=node.config.get("external_output_typed", False))
        elif node.kind == "code":
            source = str(node.config["code"])
            code_values: dict[str, Any] = {"input": attempt.input, "input_files": occurrence.context.get("input_files", []), "output": {}, "output_files": []}
            if node.config.get("dataset_code") is True:
                from .isolated_code import dataset_program
                baseline = occurrence.context["integration_baseline"]
                dataset = {name: unwrap(value) for name, value in baseline.items()}
                source = dataset_program(source, dataset)
                code_values = {"dataset": dataset}
            code_result = await self._code_phase(run, occurrence, node, claim, "activity", source, code_values)
            if code_result is None:
                return None
            result = code_result.get("output", {})
            if node.config.get("dataset_code") is True:
                if node.config.get("mode") == "code" and local_graph(run, occurrence).node(node.id).kind == "if":
                    if type(result) is not bool:
                        raise ValueError("An IF code result must be a boolean")
                    result = {"decision": {"type": "bool", "value": result}}
                else:
                    assert node.outputs is not None
                    result = external_outputs(node.outputs, result, path=f"{node.id}.output")
            occurrence.context = {**occurrence.context, "output_files": self._file_references(code_result.get("output_files", []))}
        elif node.kind == "rest":
            if attempt.status in {"started", "claiming"}:
                until = (attempt.receipt or {}).get("lease_until")
                if until and datetime.fromisoformat(until) > now():
                    return None
                if attempt.status == "started":
                    raise ProcessEngineError("effect_outcome_unknown", "REST outcome is unknown; reconcile before retrying")
            if attempt.status == "rest_ready":
                return None
            from app.tools.facade import RestRequest
            plain_input = {key: unwrap(value) for key, value in attempt.input.items()}
            request = RestRequest.model_validate(resolve(node.config.get("request", {}), {"input": plain_input}))
            attempt.status = "rest_ready"
            attempt.receipt = {"request": request.model_dump(mode="json", exclude_unset=True)}
            await get_db().commit()
            return None
        else:
            from .program_contracts import program_executor
            executor = program_executor()
            if executor is None:
                raise ValueError("Documentary programs are not installed; a qualified program executor is required")
            result = await executor.execute(agent_id=assigned_agent,
                program_uri=str(node.config.get("program_uri", "")), input_data=attempt.input, invocation_key=attempt.id)
        if await self._fenced(run.id, claim) is None:
            return None
        if graph.typed:
            assert node.outputs is not None
            try:
                result = normalize(node.outputs, result, path=f"{node.id}.output")
            except ValueContractError as error:
                if node.kind == "task":
                    raise ValueError(f"{error}. The activity must submit its declared outputs with process_activity_complete(output={{...}}).") from error
                raise
        attempt.status = "completed"
        attempt.receipt = result
        attempt.finished_at = now()
        await get_db().commit()
        if node.kind == "tool_call" and attempt.task_id:
            await task_service.complete_workflow_operation(attempt.task_id, result)
        return result

    @staticmethod
    def _file_references(raw: object) -> list[dict[str, Any]]:
        from app.file_share import parse_resource_uri
        if not isinstance(raw, list):
            raise ValueError("Activity files must be a list of canonical URI references")
        result: list[dict[str, Any]] = []
        for raw_item in cast(list[object], raw):
            if not isinstance(raw_item, dict):
                raise ValueError("Every activity file requires a canonical URI")
            item = cast(dict[str, Any], raw_item)
            uri = item.get("uri")
            if not isinstance(uri, str) or set(item) - {"uri", "description"}:
                raise ValueError("File references contain uri and an optional description")
            parsed = parse_resource_uri(uri)
            if parsed.is_collection or str(parsed) != uri:
                raise ValueError("A file reference requires an exact canonical URI")
            result.append({"uri": uri, "description": str(item.get("description", ""))})
        return result

    async def _code_phase(self, run: ProcessRun, occurrence: ProcessNodeRun, node: Node, claim: str,
                          phase: Literal["preprocess", "activity", "postprocess"], source: str, values: dict[str, Any]) -> dict[str, Any] | None:
        from .isolated_code import CodeInvocation, require_isolated_code_runner
        from .native_actors import execution_agent
        runner = require_isolated_code_runner()
        jobs: dict[str, Any] = deepcopy(occurrence.context.get("code_jobs", {}))
        if phase not in jobs:
            jobs[phase] = {"id": str(uuid5(occurrence.id, phase)), "values": deepcopy(values), "submitted": False}
            occurrence.context = {**occurrence.context, "code_jobs": deepcopy(jobs)}
            await get_db().commit()
        job: dict[str, Any] = jobs[phase]
        if "result" in job:
            return deepcopy(job["result"])
        invocation = CodeInvocation(id=UUID(job["id"]), run_id=run.id, occurrence_id=occurrence.id,
            agent_id=execution_agent(local_graph(run, occurrence), node, run.launcher_agent_id),
            phase=phase, source=source, values=deepcopy(job["values"]))
        observation = await runner.observe(invocation.id) if job["submitted"] and not getattr(runner, "replay_safe", False) else await runner.submit(invocation)
        if await self._fenced(run.id, claim) is None:
            return None
        if len(json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, allow_nan=False).encode()) > 2_000_000:
            raise ValueError("Isolated execution response exceeds the JSON limit")
        job["submitted"] = True
        job["stopped"] = observation.stopped
        job["status"] = observation.status
        if observation.stopped and observation.status == "success":
            job["result"] = deepcopy(observation.result)
        occurrence.context = {**occurrence.context, "code_jobs": deepcopy(jobs)}
        await get_db().commit()
        if observation.status in {"error", "cancelled", "unknown"}:
            raise ProcessEngineError("isolated_code_failed", observation.diagnostic or "Isolated execution did not succeed")
        return deepcopy(job["result"]) if "result" in job else None

    async def _complete(self, run: ProcessRun, occurrence: ProcessNodeRun, graph: Workflow,
                        values: dict[str, Any], claim: str, *, forward: bool = True) -> None:
        current = await self._fenced(run.id, claim)
        if current is None or current.engine_metadata.get("native", {}).get("cancel_requested"):
            return
        occurrence.status = "success"
        occurrence.output = values.get("output")
        occurrence.finished_at = now()
        context = {key: value for key, value in occurrence.context.items() if key not in {
            "loop", "converged", "integration_baseline", "input_files", "output_files", "preparation_snapshot", "code_jobs", "human_user_id", "human_title",
            "human_request_sent", "human_request_retry_at", "human_request_closed"}}
        context.pop("activity_question", None)
        context.pop("activity_question_history", None)
        context.pop("activity_result", None)
        context["values"] = values
        flows = graph.outgoing(occurrence.node_key) if forward else []
        node = graph.node(occurrence.node_key)
        if node.kind == "if":
            flows = [next((flow for flow in flows if flow.condition is not None and evaluate(flow.condition, values)),
                next(flow for flow in flows if flow.condition is None))]
        if len(flows) > 1:
            context["forks"] = [*context.get("forks", []), {"key": str(occurrence.id), "base": deepcopy(values), "count": len(flows)}]
        for flow in flows:
            enqueue(current, flow.target, {**context, "incoming_flow": flow.id})
        state = deepcopy(current.engine_metadata["native"])
        if state.get("step_root") == str(occurrence.id):
            state.pop("step_root", None)
        state["sequence"] += 1
        current.engine_metadata = {**current.engine_metadata, "native": state}
        from .models import ProcessRunEvent
        get_db().add(ProcessRunEvent(run_id=current.id, event_id=f"node:{occurrence.id}:success", source="native",
            event_type="node.completed", payload={"node": occurrence.node_key, "occurrence": str(occurrence.id)}))
        await get_db().commit()

    async def _join(self, run: ProcessRun, occurrence: ProcessNodeRun, graph: Workflow, claim: str,
                    *, admit_activity: bool = False) -> bool:
        if graph.typed:
            return await self._join_typed(run, occurrence, graph, claim, admit_activity=admit_activity)
        forks: list[dict[str, Any]] = occurrence.context.get("forks", [])
        if not forks:
            raise ValueError("Parallel join requires a matching split")
        fork = forks[-1]
        siblings = list(await get_db().scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id,
            ProcessNodeRun.node_key == occurrence.node_key, ProcessNodeRun.status.in_(("ready", "waiting")))))
        arrivals = [item for item in siblings if item.context.get("forks", []) and item.context["forks"][-1]["key"] == fork["key"]]
        occurrence.status = "waiting"
        count = len(graph.incoming(occurrence.node_key)) if graph.typed else fork["count"]
        if len(arrivals) < count:
            await get_db().commit()
            return False
        if len(arrivals) != count or len({item.context.get("incoming_flow") for item in arrivals}) != len(arrivals):
            raise ValueError("Parallel join has duplicate or incompatible arrivals")
        merged: dict[str, Any] = deepcopy(fork["base"])
        for section in ("results",):
            changed: dict[str, Any] = {}
            baseline: dict[str, Any] = fork["base"].get(section, {})
            for arrival in sorted(arrivals, key=lambda item: str(item.id)):
                for key, value in expression_context(arrival).get(section, {}).items():
                    if key in baseline and baseline[key] == value:
                        continue
                    if key in changed and changed[key] != value:
                        raise ValueError(f"Parallel branches both write {section}.{key}")
                    changed[key] = value
            merged.setdefault(section, {}).update(changed)
        for arrival in arrivals:
            arrival.status = "success"
            arrival.finished_at = now()
        occurrence.context = {**occurrence.context, "forks": forks[:-1], "values": merged}
        if admit_activity:
            occurrence.context = {**occurrence.context, "converged": True}
            occurrence.status = "ready"
            occurrence.finished_at = None
            await get_db().commit()
            return True
        merged = await self._workspace_values(run, occurrence)
        await self._complete(run, occurrence, graph, merged, claim)
        return True

    async def _join_typed(self, run: ProcessRun, occurrence: ProcessNodeRun, graph: Workflow, claim: str,
                          *, admit_activity: bool) -> bool:
        """Converge activated predecessors in this invocation, including nested splits.

        An undecided IF can still reach the join. Once decided, only its admitted
        branch remains in the frontier; an unselected branch cannot block it.
        Loop invocations have their own frame and are never joined together.
        """
        active = list(await get_db().scalars(select(ProcessNodeRun).where(
            ProcessNodeRun.run_id == run.id, ProcessNodeRun.status.in_(("ready", "waiting")))))
        frame = (occurrence.context.get("body_path", []), occurrence.context.get("return_node"))
        active = [item for item in active if
            (item.context.get("body_path", []), item.context.get("return_node")) == frame]

        def reaches_target(source: str) -> bool:
            pending, seen = [source], set[str]()
            while pending:
                node_key = pending.pop()
                if node_key == occurrence.node_key:
                    return True
                if node_key not in seen:
                    seen.add(node_key)
                    pending.extend(flow.target for flow in graph.outgoing(node_key))
            return False

        arrivals = [item for item in active if item.node_key == occurrence.node_key]
        if any(item.node_key != occurrence.node_key and reaches_target(item.node_key) for item in active):
            occurrence.status = "waiting"
            await get_db().commit()
            return False
        if len({item.context.get("incoming_flow") for item in arrivals}) != len(arrivals):
            raise ValueError("Parallel join has duplicate arrivals")
        canonical = max(arrivals, key=lambda item: item.admission_order)
        common: list[dict[str, Any]] = deepcopy(arrivals[0].context.get("forks", []))
        for arrival in arrivals[1:]:
            other: list[dict[str, Any]] = arrival.context.get("forks", [])
            length = 0
            for left, right in zip(common, other):
                if left["key"] != right["key"]:
                    break
                length += 1
            common = common[:length]
        merged: dict[str, Any] = deepcopy(common[-1]["base"] if common else expression_context(canonical))
        results: dict[str, Any] = {}
        baseline: dict[str, Any] = common[-1]["base"].get("results", {}) if common else {}
        for arrival in arrivals:
            for key, value in expression_context(arrival).get("results", {}).items():
                if key in baseline and baseline[key] == value:
                    continue
                if key in results and results[key] != value:
                    raise ValueError(f"Parallel branches both write results.{key}")
                results[key] = value
        merged["results"] = {**baseline, **results}
        for arrival in arrivals:
            if arrival is not canonical:
                arrival.status = "success"
                arrival.finished_at = now()
        canonical.context = {**canonical.context, "forks": common[:-1], "values": merged, "converged": True}
        canonical.status = "ready"
        canonical.finished_at = None
        await get_db().commit()
        if canonical.id != occurrence.id:
            return False
        if not admit_activity:
            merged = await self._workspace_values(run, occurrence)
            await self._complete(run, occurrence, graph, merged, claim)
        return True

    async def _loop(self, run: ProcessRun, occurrence: ProcessNodeRun, node: Node, claim: str) -> None:
        if occurrence.status == "waiting":
            return
        assert node.body is not None
        context = deepcopy(occurrence.context)
        values = context.get("values", {})
        loop: dict[str, Any] = context.get("loop", {"index": 0, "results": []})
        if node.kind == "for":
            if "items" not in loop:
                items: Any = evaluate(str(node.config["items"]), values)
                if not isinstance(items, list):
                    raise ValueError("FOR requires an array")
                loop["items"] = cast(list[Any], items)
            proceed = loop["index"] < len(loop["items"])
            if proceed:
                values.update(item=loop["items"][loop["index"]], index=loop["index"])
        else:
            values["index"] = loop["index"]
            proceed = bool(evaluate(str(node.config["condition"]), values))
        context["loop"] = loop
        occurrence.context = context
        if not proceed:
            values["output"] = {"iterations": loop["results"]}
            values.setdefault("results", {})[node.id] = values["output"]
            await self._complete(run, occurrence, local_graph(run, occurrence), values, claim)
            return
        current = await self._fenced(run.id, claim)
        if current is None:
            return
        occurrence.status = "waiting"
        occurrence.started_at = occurrence.started_at or now()
        start = next(item for item in node.body.nodes if item.kind == "start")
        body_context = {key: value for key, value in context.items() if key != "loop"}
        enqueue(current, start.id, {**body_context, "values": values,
            "body_path": [*context.get("body_path", []), node.id], "return_node": str(occurrence.id),
            "ancestors": [*context.get("ancestors", []), str(occurrence.id)], "forks": []})
        await get_db().commit()

    async def _end(self, run: ProcessRun, occurrence: ProcessNodeRun, graph: Workflow,
                   values: dict[str, Any], claim: str) -> None:
        returning = occurrence.context.get("return_node")
        output = values["data"]
        if not isinstance(output, dict):
            raise ValueError("Process output must be an object")
        values["output"] = output
        if returning:
            parent = await get_db().get(ProcessNodeRun, UUID(returning))
            assert parent is not None
            context = deepcopy(parent.context)
            loop: dict[str, Any] = context["loop"]
            ends: dict[str, Any] = {**loop.get("ends", {}), str(occurrence.id): values}
            loop["ends"] = ends
            siblings = list(await get_db().scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id,
                ProcessNodeRun.id != occurrence.id, ProcessNodeRun.id != parent.id,
                ProcessNodeRun.status.in_(("ready", "waiting")))))
            pending = any(item.context.get("return_node") == returning or returning in item.context.get("ancestors", []) for item in siblings)
            if not pending:
                baseline: dict[str, Any] = context["values"]
                merged: dict[str, Any] = {"results": deepcopy(baseline.get("results", {}))}
                writes: dict[str, dict[str, Any]] = {"results": {}}
                for end_values in ends.values():
                    for section in merged:
                        for field, value in end_values.get(section, {}).items():
                            if section != "output" and field in baseline.get(section, {}) and baseline[section][field] == value:
                                continue
                            if field in writes[section] and writes[section][field] != value:
                                raise ValueError(f"Loop end events both write {section}.{field}")
                            writes[section][field] = value
                            merged[section][field] = value
                loop["index"] += 1
                loop["results"].append(output)
                loop.pop("ends", None)
                context["values"] = {**context["values"], "data": output, "results": merged["results"]}
                parent.status = "ready"
            parent.context = context
        else:
            pending = await get_db().scalar(select(func.count()).select_from(ProcessNodeRun).where(
                ProcessNodeRun.run_id == run.id, ProcessNodeRun.id != occurrence.id,
                ProcessNodeRun.status.in_(("ready", "waiting"))))
            if graph.typed and not pending:
                assert graph.outputs is not None
                output = normalize(graph.outputs, cast(dict[str, Any], output), path="process.output", allow_extra=True)
                values["output"] = output
            state = deepcopy(run.engine_metadata["native"])
            ends: dict[str, Any] = {**state.get("end_results", {}), str(occurrence.id): output}
            state["end_results"] = ends
            if not pending:
                state.update(status="success", output=output)
                if occurrence.context.get("activity_summary"):
                    state["summary"] = occurrence.context["activity_summary"]
            run.engine_metadata = {**run.engine_metadata, "native": state}
        await self._complete(run, occurrence, graph, values, claim, forward=False)

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        reference = run
        record = await self._lock(reference.id)
        state = deepcopy(record.engine_metadata.get("native", {}))
        state["cancel_requested"] = True
        state["paused"] = True
        state["status"] = "cancelling"
        record.engine_metadata = {**record.engine_metadata, "native": state}
        await get_db().commit()
        attempts = list(await get_db().scalars(select(ProcessNodeAttempt).join(ProcessNodeRun,
            ProcessNodeRun.id == ProcessNodeAttempt.node_run_id).where(ProcessNodeRun.run_id == record.id)
            .execution_options(populate_existing=True)))
        # A worker may be between committed intent and admission receipt. It
        # observes cancellation and releases its claim; a crashed claim expires.
        stopped = not (state.get("lease_until") and datetime.fromisoformat(state["lease_until"]) > now())
        from .isolated_code import isolated_code_runner
        code_occurrences = list(await get_db().scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == record.id)))
        for occurrence in code_occurrences:
            stopped = await stop_decision(occurrence) and stopped
            jobs = deepcopy(occurrence.context.get("code_jobs", {}))
            for job in jobs.values():
                if job.get("stopped"):
                    continue
                runner = isolated_code_runner()
                if runner is None:
                    stopped = False
                    continue
                observation = await runner.cancel(UUID(job["id"]))
                job.update(stopped=observation.stopped, status=observation.status)
                stopped = stopped and observation.stopped
            occurrence.context = {**occurrence.context, "code_jobs": jobs}
        await get_db().commit()
        for attempt in attempts:
            if attempt.task_id is None:
                occurrence = await get_db().get(ProcessNodeRun, attempt.node_run_id)
                assert occurrence is not None
                kind = decision_activity(local_graph(record, occurrence).node(occurrence.node_key)).kind
                if kind in {"task", "tool_call"} and not simple_llm(local_graph(record, occurrence).node(occurrence.node_key)):
                    prefix = "process-node" if kind == "task" else "process-tool"
                    from .native_actors import execution_agent
                    admitted = await task_service.get_submission(execution_agent(local_graph(record, occurrence),
                        local_graph(record, occurrence).node(occurrence.node_key), record.launcher_agent_id), f"{prefix}:{attempt.id}")
                    if admitted is not None:
                        attempt.task_id = admitted.id
                        await get_db().commit()
            if attempt.task_id:
                task = await task_service.get_by_id(attempt.task_id)
                if task and task.status not in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
                    await task_service.cancel(task.id, task.revision)
                    stopped = False
                if task and task.lease_owner:
                    stopped = False
            if attempt.status == "started":
                stopped = False
        # Tasks may launch processes through MCP as well as call activities.
        # The persisted run lineage is the complete cancellation authority.
        linked = list(await get_db().scalars(select(ProcessRun).where(ProcessRun.parent_run_id == record.id)))
        for child in linked:
            if child.status in process_service.TERMINAL_STATUSES:
                continue
            if child.engine_code == self.code:
                child.engine_metadata = {**child.engine_metadata, "native": {
                    **child.engine_metadata.get("native", {}), "cancel_requested": True, "paused": True}}
                await get_db().commit()
            else:
                child = await process_service.cancel_run(child.id)
            stopped = stopped and child.status in process_service.TERMINAL_STATUSES
        record = await self._lock(reference.id)
        state = deepcopy(record.engine_metadata.get("native", {}))
        if stopped:
            state["status"] = "error" if state.get("failure") else "cancelled"
            record.engine_metadata = {**record.engine_metadata, "native": state}
        await get_db().commit()
        if stopped:
            return snapshot(record)
        return EngineRunSnapshot(status="cancelling", engine_run_id=str(record.id),
            error=EngineError(**state["error"]) if state.get("error") else None)
