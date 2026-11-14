"""Public current-definition and durable-run port for the Lab and other domains."""

from typing import Any
from collections.abc import Collection
from uuid import UUID

from app.agent import AgentManagementScope
from core.authorize import check_privilege
from core.database import get_db
from core.user import get_user_record

from . import native_definitions, native_runs, process_service
from .schemas import ProcessFileInput
from .dataset_usage import find_dataset_run_usages as find_dataset_run_usages
from .dataset_usage import find_dataset_definition_usages as find_dataset_definition_usages
from .values import ValueContractError as ValueContractError
from .input_provenance import read_input_provenance as read_input_provenance
from .input_preparation import (input_run as input_run, sync_input_run as sync_input_run,
    start_input_run as start_input_run, validate_input_run_replay as validate_input_run_replay)


async def active_work_for_agent(agent_id: int, *, reader: AgentManagementScope | None = None) -> tuple[dict[str, object], ...]:
    """Current work in the agent's participation scope, without administrative expansion."""
    from sqlalchemy import and_, or_, select
    from .models import ProcessRun
    from .native_runs import readable_run_clause
    from .run_observation import observe_run

    query = select(ProcessRun).where(
        or_(
            and_(ProcessRun.engine_code == "galaris", readable_run_clause(agent_id),
                or_(ProcessRun.launcher_agent_id == agent_id,
                    ProcessRun.launch_snapshot["participant_agents"].contains([agent_id]))),
            and_(ProcessRun.engine_code != "galaris", ProcessRun.launcher_agent_id == agent_id),
        ),
        ProcessRun.status.in_(("queued", "running", "waiting", "unknown")),
        ProcessRun.engine_metadata["native"]["cancel_requested"].as_boolean().is_not(True),
        ProcessRun.engine_metadata["native"]["paused"].as_boolean().is_not(True),
    )
    if reader is not None:
        external_scope = (ProcessRun.launcher_agent_id.is_not(None) if reader.agent_ids is None
                          else ProcessRun.launcher_agent_id.in_(reader.agent_ids))
        query = query.where(or_(
            and_(ProcessRun.engine_code == "galaris", readable_run_clause(reader)),
            and_(ProcessRun.engine_code != "galaris", external_scope),
        ))
    runs = list(await get_db().scalars(ProcessRun.histo_filter(query.order_by(ProcessRun.created_at.desc(), ProcessRun.id))))
    visible = {str(run.id) for run in runs}
    items: list[dict[str, object]] = []
    for run in runs:
        observation = await observe_run(run, can_control=False, visible_children=visible) if run.engine_code == "galaris" else {}
        phase = observation.get("phase", run.status)
        waits: list[dict[str, object]] = []
        if observation.get("input_preparation"):
            waits.append({"kind": "process_inputs", **observation["input_preparation"]})
        for activity in observation.get("activities", []):
            wait: dict[str, object] = {key: activity[key] for key in
                ("kind", "node_key", "question", "task_uri", "run_id", "since") if key in activity}
            task = activity.get("task", {})
            if task.get("waits"):
                wait["task_waits"] = task["waits"]
            waits.append(wait)
        items.append({"kind": "process", "id": str(run.id), "run_id": str(run.id), "engine_code": run.engine_code,
            "workflow_id": str(run.launch_snapshot.get("workflow_id") or run.launch_snapshot.get("engine_process_id") or ""),
            "label": str(run.launch_snapshot.get("process_label") or ""),
            "status": run.status, "operational_state": str(phase).upper(), "waits": waits,
            "created_at": run.created_at.isoformat(),
            "state_since": observation.get("last_activity_at") or (run.updated_at or run.started_at or run.created_at).isoformat()})
    return tuple(items)


def normalize_human_reply(declarations: list[dict[str, Any]] | None,
                          response: dict[str, Any], *, typed_values: bool = False,
                          partial: bool = False) -> dict[str, Any]:
    """Adapt a conversational JSON reply to the frozen Process value contract."""
    if declarations is None:
        return response
    from .values import Variable, conversational_patch, normalize_reply, normalize_patch
    variables = [Variable.model_validate(item) for item in declarations]
    validator = normalize_patch if partial else normalize_reply
    selected = conversational_patch(variables, response, path="output", typed_values=typed_values)
    return validator(variables, selected, path="output")


async def complete_human_activity(identity: UUID, *, user_id: int, output: dict[str, Any],
                                  question_id: UUID | None = None) -> None:
    """Stage a human reply inside Messenger's atomic response transaction."""
    from .native_actors import complete_human_work
    await complete_human_work(identity, AgentManagementScope(user_id, frozenset()), output,
        commit=False, question_id=question_id)


async def human_activity_pending(identity: UUID, *, question_id: UUID | None = None) -> bool:
    from sqlalchemy import select
    from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
    query = select(ProcessNodeAttempt, ProcessRun)
    query = (query
        .join(ProcessNodeRun, ProcessNodeRun.id == ProcessNodeAttempt.node_run_id)
        .join(ProcessRun, ProcessRun.id == ProcessNodeRun.run_id)
        .where(ProcessNodeAttempt.id == identity,
            (ProcessNodeAttempt.status == "human_waiting") | ((ProcessNodeAttempt.status == "accepted")
                & (ProcessNodeRun.context["activity_question"]["status"].as_string() == "pending")),
            ProcessNodeRun.status == "waiting", ProcessRun.status.not_in(process_service.TERMINAL_STATUSES)))
    if question_id is not None:
        query = query.where(ProcessNodeRun.context["activity_question"]["id"].as_string() == str(question_id))
    row = (await get_db().execute(query)).first()
    return row is not None and not row[1].engine_metadata.get("native", {}).get("cancel_requested")


async def current_definition(code: str, actor: int | AgentManagementScope) -> dict[str, Any]:
    return await native_definitions.read(code, actor)


async def prepare_launch_inputs(agent_id: int, workflow_id: str, values: dict[str, Any], *,
                                typed_values: bool = False, run_id: UUID | None = None,
                                validate_defaults: bool = True) -> dict[str, Any] | None:
    """Read the live assigned input contract and validate a partial preparation, without a run."""
    from .bpmn import Workflow, selected_variables
    if run_id is not None:
        run = await input_run(agent_id, run_id)
        if run.launch_snapshot.get("workflow_id") != workflow_id:
            raise PermissionError("Input run belongs to a different workflow")
        current = run.launch_snapshot["definition"]
        label = str(run.launch_snapshot["process_label"])
    else:
        definition = await process_service.get_for_agent(agent_id, workflow_id)
        if definition is None:
            raise PermissionError("This process is not assigned or readable")
        if definition.code is None:
            return None
        current = await native_definitions.read(workflow_id, agent_id)
        label = definition.label
    graph = Workflow.model_validate(current["graph"])
    if not graph.typed:
        return None
    variables = selected_variables(graph, graph.inputs)
    prepared = {variable.name: variable.default.model_dump(mode="json") for variable in variables if variable.default is not None}
    declarations = [variable.model_dump(mode="json") for variable in variables]
    if values:
        prepared.update(await validate_launch_input_patch(agent_id, declarations, values, typed_values=typed_values))
    if validate_defaults:
        await validate_launch_input_patch(agent_id, declarations, prepared, typed_values=True)
    return {"workflow_id": workflow_id, "label": label,
        "declarations": declarations, "values": prepared,
        "missing": [variable.name for variable in variables if variable.name not in prepared]}


async def validate_launch_input_patch(agent_id: int, declarations: list[dict[str, Any]], values: dict[str, Any], *,
                                      typed_values: bool = False) -> dict[str, Any]:
    result, _ = await validate_launch_input_fields(agent_id, declarations, values, typed_values=typed_values, fail_fast=True)
    return result


async def validate_launch_input_fields(agent_id: int, declarations: list[dict[str, Any]], values: dict[str, Any], *,
                                       typed_values: bool = False, fail_fast: bool = False,
                                       resource_metadata: dict[str, dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate independent fields in linear work; metadata is shared only within this call."""
    from .values import Variable, conversational_patch, validate_declarations
    from app.file_share import ResourceContext, resource_info, ResourceDescriptor
    parsed = [Variable.model_validate(raw) for raw in declarations]
    validate_declarations(parsed, path="process.input")
    variables = {item.name: item for item in parsed}
    result: dict[str, Any] = {}
    issues: dict[str, str] = {}
    metadata: dict[str, ResourceDescriptor | Exception] = {}
    context = ResourceContext(agent_id=agent_id, runtime="internal")
    for name, value in values.items():
        try:
            variable = variables.get(name)
            if variable is None:
                raise ValueContractError(f"process.input: undeclared variable {name}")
            checked = conversational_patch([variable], {name: value}, path="process.input", typed_values=typed_values)[name]
            if variable.type in {"File", "Document"} and checked["value"] is not None:
                uri = str(checked["value"])
                if uri not in metadata:
                    try:
                        metadata[uri] = await resource_info(context, uri)
                    except (ValueError, PermissionError, FileNotFoundError) as error:
                        metadata[uri] = error
                descriptor = metadata[uri]
                if isinstance(descriptor, Exception):
                    raise descriptor
                if descriptor.is_collection:
                    raise ValueContractError(f"process.input.{name}: expected a resource, not a directory")
                from app.document import document_format_definition
                expected = variable.mime_type or (document_format_definition(variable.document_format).media_type
                    if variable.document_format is not None else None)
                if variable.document_format is not None:
                    actual_format = descriptor.metadata.get("document_format")
                    if actual_format != variable.document_format:
                        raise ValueContractError(f"process.input.{name}: expected document format {variable.document_format}")
                actual = descriptor.media_type.split(";", 1)[0].strip().lower()
                if expected and actual != expected and not (expected.endswith("/*") and actual.startswith(expected[:-1])):
                    raise ValueContractError(f"process.input.{name}: expected media type {expected}, received {actual}")
                if resource_metadata is not None:
                    resource_metadata[uri] = {key: entry for key, entry in {
                        "revision": descriptor.revision, "checksum": descriptor.checksum, "etag": descriptor.etag,
                    }.items() if entry is not None and (not isinstance(entry, str) or len(entry) <= 256)}
            result[name] = checked
        except (ValueError, PermissionError, FileNotFoundError) as error:
            if fail_fast:
                raise
            issues[name] = str(error)
    return result, issues


def plain_launch_inputs(values: dict[str, Any]) -> dict[str, Any]:
    from .values import unwrap
    return {name: unwrap(value) for name, value in values.items()}


async def launch_current(code: str, actor: int | AgentManagementScope, *, agent_id: int,
                         input_data: dict[str, Any], invocation_key: str,
                         files: list[ProcessFileInput] | None = None) -> UUID:
    await native_definitions.get(code, actor)
    if isinstance(actor, AgentManagementScope):
        actor.require(agent_id)
        user = await get_user_record(actor.user_id)
        if user is None or not await check_privilege(user, ["PROCESS_LAUNCH", "PROCESS_ADMIN"], get_db()):
            raise PermissionError("The human launcher requires the process launch privilege")
    elif actor != agent_id:
        raise PermissionError("An agent cannot impersonate another workflow launcher")
    result = await process_service.start_process(agent_id=agent_id, workflow_id=code, input_data=input_data,
        files=files or [], idempotency_key=invocation_key,
        requester_user_id=actor.user_id if isinstance(actor, AgentManagementScope) else None)
    return result.run_id


async def run_evidence(identity: UUID, actor: int | AgentManagementScope) -> dict[str, Any]:
    run = await native_runs.require_run(identity, actor)
    return {"id": str(run.id), "status": run.status, "output": run.output, "error": run.error_message,
        "definition_revision": run.launch_snapshot.get("definition", {}).get("revision"),
        "data": run.data, "data_uri": f"galaris://processes/runs/{run.id}/data",
        "duration_seconds": ((run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None),
        "metrics": await native_runs.run_metrics(identity, actor)}


async def stop_run(identity: UUID, actor: int | AgentManagementScope) -> None:
    await native_runs.require_run(identity, actor, control=True)
    await process_service.cancel_run(identity)


async def is_activity_inference_agent(run_id: UUID, agent_id: int, correlation_ref: str | None) -> bool:
    """A delegated LLM call must identify its real, admitted Process activity."""
    from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun

    run = await get_db().get(ProcessRun, run_id)
    if run is None:
        return False
    if correlation_ref is None or not correlation_ref.startswith("process-attempt:"):
        return False
    try:
        identity = UUID(correlation_ref.removeprefix("process-attempt:"))
    except ValueError:
        return False
    attempt = await get_db().get(ProcessNodeAttempt, identity)
    occurrence = await get_db().get(ProcessNodeRun, attempt.node_run_id) if attempt else None
    if (attempt is None or occurrence is None or occurrence.run_id != run.id
            or attempt.status != "llm_waiting" or attempt.task_id is not None):
        return False
    from .native_engine import local_graph
    from .native_actors import execution_agent
    from .llm_decisions import simple_llm

    graph = local_graph(run, occurrence)
    node = graph.node(occurrence.node_key)
    return simple_llm(node) and execution_agent(graph, node, run.launcher_agent_id) == agent_id


async def definition_options(*, agent_ids: Collection[int] | None) -> list[dict[str, Any]]:
    """Bounded metadata for selecting an external process in another domain."""
    records = await process_service.list_definitions(agent_ids=agent_ids)
    return [{"agent_id": item.agent_id, "engine_process_id": item.engine_process_id, "label": item.label}
            for item in records if item.code is None]
