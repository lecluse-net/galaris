"""Public current-definition and durable-run port for the Lab and other domains."""

from typing import Any, cast
from uuid import UUID

from app.agent import AgentManagementScope
from core.authorize import check_privilege
from core.database import get_db
from core.user import get_user_record

from . import native_definitions, native_runs, process_service
from .schemas import ProcessFileInput
from .dataset_usage import find_dataset_run_usages as find_dataset_run_usages
from .values import ValueContractError as ValueContractError


async def active_work_for_agent(agent_id: int, *, reader: AgentManagementScope | None = None) -> tuple[dict[str, object], ...]:
    """Current work in the agent's participation scope, without administrative expansion."""
    from sqlalchemy import select
    from .models import ProcessRun
    from .native_runs import readable_run_clause
    from .run_observation import observe_run

    query = select(ProcessRun).where(
        readable_run_clause(agent_id), ProcessRun.status.in_(("queued", "running", "waiting", "unknown")),
        ProcessRun.engine_metadata["native"]["cancel_requested"].as_boolean().is_not(True),
        ProcessRun.engine_metadata["native"]["paused"].as_boolean().is_not(True),
    )
    if reader is not None:
        query = query.where(readable_run_clause(reader))
    runs = list(await get_db().scalars(ProcessRun.histo_filter(query.order_by(ProcessRun.created_at.desc(), ProcessRun.id))))
    visible = {str(run.id) for run in runs}
    items: list[dict[str, object]] = []
    for run in runs:
        observation = await observe_run(run, can_control=False, visible_children=visible) if run.engine_code == "galaris" else {}
        phase = observation.get("phase", run.status)
        waits: list[dict[str, object]] = []
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
                          response: dict[str, Any], *, typed_values: bool = False) -> dict[str, Any]:
    """Adapt a conversational JSON reply to the frozen Process value contract."""
    if declarations is None:
        return response
    from .values import Variable, external_outputs, normalize
    variables = [Variable.model_validate(item) for item in declarations]
    if typed_values:
        return normalize(variables, response, path="output")
    if set(response) - {variable.name for variable in variables}:
        raise ValueContractError("output: undeclared variable")
    selected: dict[str, Any] = {}
    for variable in variables:
        if variable.name not in response:
            continue
        value = response[variable.name]
        # Historical scalar/File envelopes remain supported. Object values stay
        # ordinary JSON; explicit typed_values removes ambiguity for that type.
        is_typed = (isinstance(value, dict) and set(cast(dict[str, Any], value)) == {"type", "value"}
            and variable.type != "object")
        selected.update(external_outputs([variable], {variable.name: cast(Any, value)},
            path="output", typed_values=is_typed))
    return normalize(variables, selected, path="output")


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
        "dataset_uri": f"document://{run.dataset_document_id}" if run.dataset_document_id else None,
        "duration_seconds": ((run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None),
        "metrics": await native_runs.run_metrics(identity, actor)}


async def stop_run(identity: UUID, actor: int | AgentManagementScope) -> None:
    await native_runs.require_run(identity, actor, control=True)
    await process_service.cancel_run(identity)
