"""Self-service and restricted administrative business-process MCP tools."""

from __future__ import annotations
from app.agent import EffectDescriptorV1

from typing import Any, Optional, Literal
from uuid import UUID

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import render_prompt, t
from core.database import get_db

from . import process_service
from . import native_definitions, native_runs
from .bpmn import Workflow, compile_bpmn, validate_graph
from .values import Variable
from .schemas import (
    ProcessDefinitionCreate,
    ProcessDefinitionRead,
    ProcessDefinitionUpdate,
    ProcessFileInput,
    ProcessToolRead,
)


@mcp_tool("galaris", name="processus_get", approval="enabled", effect_policy="read", concurrency_policy="safe",
    description="Inspect an internal run's progress, active activities, human/authorization/Task/child waits, blockers, last activity and available controls. Only participating agents or an agent with active process_admin access may read it. Omit run_id inside an activity Task to inspect its owning run.")
async def processus_get(ctx: McpToolContext, run_id: str | None = None) -> dict[str, Any]:
    if run_id is None:
        from sqlalchemy import select
        from .models import ProcessNodeAttempt, ProcessNodeRun
        identity = await get_db().scalar(select(ProcessNodeRun.run_id)
            .join(ProcessNodeAttempt, ProcessNodeAttempt.node_run_id == ProcessNodeRun.id)
            .where(ProcessNodeAttempt.task_id == ctx.task_id)) if ctx.task_id else None
        if identity is None:
            raise ValueError("Provide run_id outside an internal process activity Task")
    else:
        identity = _run_id(run_id)
    snapshot = await native_runs.inspect_run(identity, ctx.agent_id, page_size=10)
    return {key: snapshot[key] for key in ("id", "label", "workflow_id", "status", "can_control", "operational", "definition_revision", "error", "error_code")}


def _run_id(value: str) -> UUID:
    try:
        return UUID(value.strip().removeprefix("galaris://processes/runs/"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid process-run UUID: {value}") from exc


def _definition_payload(
    definition: Any,
    tool_codes: dict[int, str],
) -> dict[str, Any]:
    payload = dict(
        ProcessDefinitionRead.model_validate(definition).model_dump(mode="json")
    )
    payload["tool_code"] = tool_codes.get(definition.tool_id, "")
    return payload


async def _process_tool_codes() -> dict[int, str]:
    return {
        tool.id: tool.code
        for tool in await process_service.list_process_tools()
    }


async def _admin_native_definition(ctx: McpToolContext, identity: int, *, write: bool = False) -> None:
    record = await process_service.get_definition(identity)
    if record is not None and record.code is not None:
        await native_definitions.get(record.code or "", ctx.agent_id, write=write)


async def _admin_native_run(ctx: McpToolContext, identity: UUID, *, control: bool = False) -> None:
    run = await process_service.get_run(identity)
    if run is not None and run.engine_code == "galaris":
        await native_runs.require_run(identity, ctx.agent_id, control=control)


async def _require_visible_run(ctx: McpToolContext, identity: UUID) -> None:
    from app.tools import has_process_admin_access

    run = await process_service.get_run(identity)
    if run is None:
        raise PermissionError("Run not found in this agent's participation scope")
    if run.engine_code == "galaris":
        await native_runs.require_run(identity, ctx.agent_id)
    elif run.launcher_agent_id != ctx.agent_id and not await has_process_admin_access(ctx.agent_id):
        raise PermissionError("Run not found in this agent's participation scope")


@mcp_tool("galaris", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_list",
    description="List only the business processes assigned to the current agent.",
)
async def process_list(ctx: McpToolContext) -> list[dict[str, Any]]:
    return await process_service.list_for_agent(ctx.agent_id)


@mcp_tool("galaris", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_get",
    description="Describe one workflow assigned to the current agent.",
)
async def process_get(ctx: McpToolContext, workflow_id: str) -> dict[str, Any]:
    allowed = await process_service.get_for_agent(ctx.agent_id, workflow_id)
    if allowed is None:
        language = await context_language(ctx)
        raise PermissionError(
            render_prompt(t("process.errors.not_allowed", language), process_code=workflow_id)
        )
    process = allowed
    result: dict[str, Any] = {
        "workflow_id": process.engine_process_id,
        "label": process.label,
        "description": process.description,
        "tool_id": process.tool_id,
    }
    if process.code is not None:
        definition = await native_definitions.read(workflow_id, ctx.agent_id)
        graph = Workflow.model_validate(definition["graph"])
        result["schema_version"] = graph.schema_version
        # Global inputs/outputs alone say nothing about the executable content.
        # Supply a compact inventory without copying prompts or script bodies.
        activities: list[dict[str, str]] = []
        def collect(body: Workflow) -> None:
            for node in body.nodes:
                if node.kind not in {"start", "end"}:
                    activities.append({"id": node.id, "kind": node.kind, "title": node.title})
                if node.body is not None:
                    collect(node.body)
        collect(graph)
        result["activities"] = activities
        result["diagnostics"] = definition["diagnostics"]
        if graph.typed:
            result["inputs"] = [variable.model_dump(mode="json") for variable in graph.inputs or []]
            result["outputs"] = [variable.model_dump(mode="json") for variable in graph.outputs or []]
    return result


@mcp_tool("galaris", approval="enabled", approval_reason="Submit the current activity's validated output",
    conversation_policy="forbidden", effect_policy="idempotent", name="process_activity_complete",
    description="For your current native Process activity Task only: submit its declared output variables as ordinary JSON (for example output={\"age\": 42}). Optionally provide a concise user-facing message. The engine validates and stores typed data; your final prose is not parsed as JSON. Stop after acceptance.")
async def process_activity_complete(ctx: McpToolContext, output: dict[str, Any], message: str = "") -> dict[str, Any]:
    if len(message) > 12_000:
        raise ValueError("The activity message exceeds 12000 characters")
    from .activity_controls import submit_result
    from .values import ValueContractError
    from app.tools import RecoverableToolError
    try:
        return await submit_result(ctx.task_id, ctx.agent_id, output, message)
    except ValueContractError as error:
        raise RecoverableToolError(str(error)) from error


@mcp_tool("galaris", approval="enabled", approval_reason="Ask the authenticated requester for activity input",
    conversation_policy="forbidden", effect_policy="idempotent", name="process_activity_question",
    description="For your current native Process activity Task only: ask its authenticated human requester a question and wait durably for the answer in messaging. Supply expected variables (name, type, nullable); omitted variables use the activity's outputs. Stop this turn after waiting_for_human. If answered=true, use the returned response and continue to process_activity_complete. Rephrasing a question for the same variables reuses its answer. Only to intentionally request a new answer, supply a new stable question_key (max 128 characters); reuse that key on retries and resumption. Never invent the answer or return the question as data.")
async def process_activity_question(ctx: McpToolContext, question: str,
                                    variables: list[Variable] | None = None, question_key: str | None = None) -> dict[str, Any]:
    from .activity_controls import ask_input
    return await ask_input(ctx.task_id, ctx.agent_id, question, variables, question_key=question_key)


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-authorized process definition read", effect_policy="read",
    name="process_definition_read", description="Read the current saved BPMN definition, graph, task instructions and actors to audit a process you can read.")
async def process_definition_read(ctx: McpToolContext, process_code: str) -> dict[str, Any]:
    return await native_definitions.read(process_code, ctx.agent_id)


@mcp_tool("galaris", approval="ask", approval_reason="Create a governed business process",
    name="process_create", description="Create your private internal BPMN process from a typed graph or BPMN XML; its code is immutable.")
async def process_create(ctx: McpToolContext, title: str, graph: dict[str, Any] | None = None,
                         xml: str | None = None, code: str | None = None) -> dict[str, Any]:
    record = await native_definitions.create(actor_agent_id=ctx.agent_id, title=title,
        graph=Workflow.model_validate(graph) if graph is not None else None, xml=xml, code=code)
    return await native_definitions.read(record.code or "", ctx.agent_id)


@mcp_tool("galaris", approval="ask", approval_reason="Edit a governed business process",
    name="process_update", description="Update a process you may edit with the read expected_revision. Future launches use this save; active runs keep their original graph.")
async def process_update(ctx: McpToolContext, process_code: str, expected_revision: int,
                         graph: dict[str, Any] | None = None, xml: str | None = None, title: str | None = None) -> dict[str, Any]:
    return await native_definitions.update(process_code, ctx.agent_id, expected_revision=expected_revision,
        graph=Workflow.model_validate(graph) if graph is not None else None, xml=xml, title=title)


@mcp_tool("galaris", approval="enabled", approval_reason="Pure profile validation", effect_policy="read",
    name="process_validate", description="Validate BPMN or a typed graph without saving or executing effects.")
async def process_validate(ctx: McpToolContext, graph: dict[str, Any] | None = None, xml: str | None = None) -> dict[str, Any]:
    validated = validate_graph(Workflow.model_validate(graph)) if graph is not None else compile_bpmn(xml or "")
    return {"valid": True, "diagnostics": [], "graph": validated.model_dump(mode="json")}


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-authorized Process history", effect_policy="read",
    name="process_history", description="Read a Process definition's saved BPMN history for review. Launches have no selectable version.")
async def process_history(ctx: McpToolContext, process_code: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    if page < 1 or page_size not in {10, 20, 50, 100, 500}:
        raise ValueError("Invalid history pagination")
    return await native_definitions.history(process_code, ctx.agent_id, limit=page_size, offset=(page - 1) * page_size)


@mcp_tool("galaris", approval="ask", approval_reason="Restore Process BPMN",
    name="process_restore", description="Restore a readable Process revision as a new current BPMN save, if you may edit the process.")
async def process_restore(ctx: McpToolContext, process_code: str, revision: int, expected_revision: int) -> dict[str, Any]:
    return await native_definitions.restore(process_code, ctx.agent_id, revision, expected_revision)


@mcp_tool("galaris", approval="ask", approval_reason="Archive a governed process",
    name="process_archive", description="Archive or reactivate a process you can edit. Existing runs retain their history.")
async def process_archive(ctx: McpToolContext, process_code: str, archived: bool = True) -> dict[str, Any]:
    return await native_definitions.archive(process_code, ctx.agent_id, archived)


@mcp_tool("galaris", approval="ask", approval_reason="Change Process definition sharing",
    name="process_share", description="As the Process definition owner, grant an agent read/edit access or remove its Process grant.")
async def process_share(ctx: McpToolContext, process_code: str, target_agent_id: int,
                        access: Literal["read", "edit", "none"]) -> dict[str, object]:
    from .native_sharing import grant_agent
    return await grant_agent(process_code, ctx.agent_id, target_agent_id,
        can_write=access == "edit", revoke=access == "none")


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-scoped live run read", effect_policy="read",
    name="process_run_inspect", description="Inspect a readable native run, its frozen graph, occurrences, run data and event cursor.")
async def process_run_inspect(ctx: McpToolContext, run_id: str, page: int = 1, page_size: int = 50, after_event: int = 0) -> dict[str, Any]:
    if page < 1 or page_size not in {10, 20, 50, 100, 500} or after_event < 0:
        raise ValueError("Invalid run pagination")
    return await native_runs.inspect_run(_run_id(run_id), ctx.agent_id, page=page, page_size=page_size, after_event=after_event)


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-scoped child run read", effect_policy="read",
    name="process_run_children", description="Read one authorized page of a run's immediate child processes, without a depth limit.")
async def process_run_children(ctx: McpToolContext, run_id: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    if page < 1 or page_size not in {10, 20, 50, 100, 500}:
        raise ValueError("Invalid child pagination")
    return await native_runs.children(_run_id(run_id), ctx.agent_id, page=page, page_size=page_size)


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-scoped occurrence read", effect_policy="read",
    name="process_run_occurrence", description="Read one authorized activity occurrence, including actual prompts, attempt receipts, Tasks and child runs.")
async def process_run_occurrence(ctx: McpToolContext, run_id: str, occurrence_id: str) -> dict[str, Any]:
    return await native_runs.inspect_occurrence(_run_id(run_id), _run_id(occurrence_id), ctx.agent_id)


@mcp_tool("galaris", approval="enabled", approval_reason="Resource-scoped accounting read", effect_policy="read",
    name="process_run_metrics", description="Read direct and inclusive recorded costs and tokens, with partial coverage and per-Task accounting.")
async def process_run_metrics(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    return await native_runs.run_metrics(_run_id(run_id), ctx.agent_id)


@mcp_tool("galaris", approval="ask", approval_reason="Control a launched native process",
    name="process_run_control", description="Persist pause, resume, step or breakpoints for your run. Reuse command_key if the reply is lost; expected_revision detects concurrent debugger changes.")
async def process_run_control(ctx: McpToolContext, run_id: str,
                              action: Literal["pause", "resume", "step", "breakpoints"], nodes: list[str] | None = None,
                              command_key: UUID | None = None, expected_revision: int | None = None) -> dict[str, Any]:
    return await native_runs.control_run(_run_id(run_id), ctx.agent_id, action, nodes,
        command_key=command_key, expected_revision=expected_revision)


@mcp_tool("galaris", approval="ask", approval_reason="Cancel a launched process",
    name="process_run_cancel", description="Request cancellation of your run and confirm actual termination of its admitted activities.")
async def process_run_cancel(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    await native_runs.require_run(_run_id(run_id), ctx.agent_id, control=True)
    run = await process_service.cancel_run(_run_id(run_id))
    return {"id": str(run.id), "status": run.status}


@mcp_tool("galaris", approval="ask", approval_reason="Launch another current process run",
    name="process_run_retry", description="Launch a terminal native run again using its inputs and canonical files with the latest saved process. Reuse the same idempotency key if the reply is lost.")
async def process_run_retry(ctx: McpToolContext, run_id: str, idempotency_key: str) -> dict[str, Any]:
    run = await native_runs.require_run(_run_id(run_id), ctx.agent_id, control=True)
    if run.status not in process_service.TERMINAL_STATUSES:
        raise ValueError("Only a terminal run can be retried")
    response = await process_service.start_process(agent_id=ctx.agent_id,
        workflow_id=str(run.launch_snapshot["workflow_id"]), input_data=run.input,
        files=[ProcessFileInput(uri=str(item["uri"]), slot=item.get("slot"), description=str(item.get("description") or ""))
            for item in run.launch_snapshot.get("files", [])], idempotency_key=idempotency_key, task_id=ctx.task_id)
    return response.model_dump(mode="json")


@mcp_tool("galaris", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_start",
    effect_descriptor=EffectDescriptorV1(capability="process.start", kind="process", target_arguments=("workflow_id",), target_prefix="galaris://process/", visibility="external", receipt="process", domain_assigned_selection=True),
    conversation_policy="forbidden",
    description=(
        "Start a business process assigned to the current agent and return its tracking ID. "
        "Each files item uses {uri, description}; uri accepts any authorized canonical "
        "file_schemes resource and is transferred transparently when the process downloads it."
    ),
)
async def process_start(
    ctx: McpToolContext,
    workflow_id: str,
    input: Optional[dict[str, Any]] = None,
    files: Optional[list[dict[str, str]]] = None,
    wait_for_completion: bool = False,
    idempotency_key: Optional[str] = None,
) -> dict[str, Any]:
    refs = [ProcessFileInput.model_validate(item) for item in (files or [])]
    try:
        response = await process_service.start_process(
            agent_id=ctx.agent_id,
            workflow_id=workflow_id,
            input_data=input or {},
            files=refs,
            wait_for_completion=wait_for_completion,
            idempotency_key=idempotency_key,
            task_id=ctx.task_id,
            runtime=ctx.runtime,
        )
    except Exception as exc:
        language = await context_language(ctx)
        raise RuntimeError(render_prompt(
            t("process.errors.start_failed", language),
            process_code=workflow_id,
            reason=str(exc),
        )) from exc
    return response.model_dump(mode="json")


@mcp_tool("galaris", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_list_runs",
    description="List participating internal runs and the current agent's external runs. An active process_admin grant permits global visibility.",
)
async def process_list_runs(
    ctx: McpToolContext,
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    runs = await process_service.list_runs(
        participant_agent_id=ctx.agent_id, workflow_id=workflow_id, status=status, limit=limit
    )
    visible: list[dict[str, Any]] = []
    for run in runs:
        try:
            await _admin_native_run(ctx, run.id)
        except (PermissionError, LookupError):
            continue
        visible.append((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]
    return visible


@mcp_tool("galaris", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_get_run",
    description="Return a run allowed by its Process sharing policy or dedicated Process administration and refresh it when needed.",
)
async def process_get_run(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    await _require_visible_run(ctx, _run_id(run_id))
    detail = await process_service.get_run_detail(_run_id(run_id), refresh_if_stale=True)
    if detail is None:
        raise PermissionError(t("process.errors.run_not_visible", await context_language(ctx)))
    return detail.model_dump(mode="json", exclude={"events"})


@mcp_tool("galaris", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_analyze_run",
    description="Explain the result and errors of a run allowed by its Process sharing policy or dedicated Process administration.",
)
async def process_analyze_run(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    await _require_visible_run(ctx, _run_id(run_id))
    run = await process_service.get_run(_run_id(run_id))
    if run is None:
        raise PermissionError(t("process.errors.run_not_visible", await context_language(ctx)))
    await _admin_native_run(ctx, run.id)
    return (await process_service.analyze_run(run.id)).model_dump(mode="json")


@mcp_tool("process_admin", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_admin_engines",
    description="List process engines that can back an administrative process definition.",
)
async def process_admin_engines(
    ctx: McpToolContext,  # noqa: ARG001
) -> list[dict[str, Any]]:

    tools = await process_service.list_process_tools()
    return [
        dict(ProcessToolRead.model_validate(tool).model_dump(mode="json"))
        for tool in tools
    ]


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_sync",
    description=(
        "Read the workflows currently exposed by one process engine before creating or updating "
        "their Galaris assignments."
    ),
)
async def process_admin_sync(
    ctx: McpToolContext,  # noqa: ARG001
    tool_code: str = "n8n",
) -> list[dict[str, Any]]:

    await process_service.get_process_tool_by_code(tool_code)
    return await process_service.sync_tool_definitions(tool_code)


@mcp_tool("process_admin", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_admin_list",
    description=(
        "List process definitions for every agent, optionally filtered by assigned agent."
    ),
)
async def process_admin_list(
    ctx: McpToolContext,  # noqa: ARG001
    agent_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:

    if agent_id is not None and agent_id <= 0:
        raise ValueError("agent_id must be greater than zero")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    definitions = await process_service.list_definitions(
        agent_id=agent_id,
        limit=limit,
    )
    tool_codes = await _process_tool_codes()
    visible: list[dict[str, Any]] = []
    for item in definitions:
        if item.code is not None:
            try:
                await native_definitions.get(item.code or "", ctx.agent_id)
            except (PermissionError, LookupError):
                continue
        visible.append(_definition_payload(item, tool_codes))
    return visible


@mcp_tool("process_admin", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_admin_get",
    description="Return any agent's process definition by its Galaris process ID.",
)
async def process_admin_get(
    ctx: McpToolContext,  # noqa: ARG001
    process_id: int,
) -> dict[str, Any]:

    if process_id <= 0:
        raise ValueError("process_id must be greater than zero")
    definition = await process_service.get_definition(process_id)
    if definition is None:
        raise ValueError(f"Process definition not found: {process_id}")
    await _admin_native_definition(ctx, process_id)
    tool_codes = await _process_tool_codes()
    return _definition_payload(definition, tool_codes)


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_create",
    description="Create and assign a process definition to the selected agent.",
)
async def process_admin_create(
    ctx: McpToolContext,  # noqa: ARG001
    agent_id: int,
    workflow_id: str,
    label: str,
    description: str = "",
    tool_code: str = "n8n",
) -> dict[str, Any]:

    tool = await process_service.get_process_tool_by_code(tool_code)
    definition = await process_service.create_definition(
        ProcessDefinitionCreate(
            agent_id=agent_id,
            tool_id=tool.id,
            engine_process_id=workflow_id,
            label=label,
            description=description or None,
        )
    )
    return _definition_payload(definition, {tool.id: tool.code})


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_update",
    description=(
        "Update the assignment, engine workflow, label, or description of any process "
        "definition. Omitted fields are preserved."
    ),
)
async def process_admin_update(
    ctx: McpToolContext,  # noqa: ARG001
    process_id: int,
    agent_id: int | None = None,
    workflow_id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    tool_code: str | None = None,
    clear_description: bool = False,
) -> dict[str, Any]:

    if process_id <= 0:
        raise ValueError("process_id must be greater than zero")
    await _admin_native_definition(ctx, process_id, write=True)
    if clear_description and description is not None:
        raise ValueError("description and clear_description cannot be supplied together")
    values: dict[str, Any] = {}
    for key, value in (
        ("agent_id", agent_id),
        ("engine_process_id", workflow_id),
        ("label", label),
        ("description", description),
    ):
        if value is not None:
            values[key] = value
    if clear_description:
        values["description"] = None

    if tool_code is not None:
        tool = await process_service.get_process_tool_by_code(tool_code)
        values["tool_id"] = tool.id
    if not values:
        raise ValueError("At least one process field must be supplied")
    definition = await process_service.update_definition(
        process_id,
        ProcessDefinitionUpdate(**values),
    )
    if definition is None:
        raise ValueError(f"Process definition not found: {process_id}")
    tool_codes = await _process_tool_codes()
    return _definition_payload(definition, tool_codes)


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_delete",
    description="Soft-delete any agent's process definition while preserving run history.",
)
async def process_admin_delete(
    ctx: McpToolContext,  # noqa: ARG001
    process_id: int,
) -> dict[str, Any]:

    if process_id <= 0:
        raise ValueError("process_id must be greater than zero")
    await _admin_native_definition(ctx, process_id, write=True)
    deleted = await process_service.delete_definition(process_id)
    if not deleted:
        raise ValueError(f"Process definition not found: {process_id}")
    return {"process_id": process_id, "deleted": True}


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_start",
    description=(
        "Start a process assigned to the selected agent and return its tracking ID. Each files "
        "item uses {uri, description}; file_share resolves the canonical source URI."
    ),
)
async def process_admin_start(
    ctx: McpToolContext,
    agent_id: int,
    workflow_id: str,
    input: dict[str, Any] | None = None,
    files: list[dict[str, str]] | None = None,
    wait_for_completion: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:

    refs = [ProcessFileInput.model_validate(item) for item in (files or [])]
    if agent_id <= 0:
        raise ValueError("agent_id must be greater than zero")
    definition = await process_service.get_for_agent(agent_id, workflow_id)
    if definition is not None and definition.code is not None and agent_id != ctx.agent_id:
        raise PermissionError("An Agent administrator cannot impersonate another internal process launcher")
    if refs and agent_id != ctx.agent_id:
        raise ValueError(
            "Cross-agent process starts cannot reference another runtime's private filesystem"
        )
    response = await process_service.start_process(
        agent_id=agent_id,
        workflow_id=workflow_id,
        input_data=input or {},
        files=refs,
        wait_for_completion=wait_for_completion,
        idempotency_key=idempotency_key,
        task_id=ctx.task_id if agent_id == ctx.agent_id else None,
        runtime=ctx.runtime,
    )
    return dict(response.model_dump(mode="json"))


@mcp_tool("process_admin", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_admin_list_runs",
    description="List process runs for every agent, optionally filtered by agent or workflow.",
)
async def process_admin_list_runs(
    ctx: McpToolContext,  # noqa: ARG001
    agent_id: int | None = None,
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:

    if agent_id is not None and agent_id <= 0:
        raise ValueError("agent_id must be greater than zero")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    runs = await process_service.list_runs(
        agent_id=agent_id,
        participant_agent_id=ctx.agent_id,
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )
    visible: list[process_service.ProcessRun] = []
    for run in runs:
        try:
            await _admin_native_run(ctx, run.id)
        except (PermissionError, LookupError):
            continue
        visible.append(run)
    return [
        dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]
        for run in visible
    ]


@mcp_tool("process_admin", approval='enabled', approval_reason='Governed bounded read or polling',

    name="process_admin_get_run",
    description="Return the complete details of any agent's process run.",
)
async def process_admin_get_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
    refresh_if_stale: bool = True,
) -> dict[str, Any]:
    await _admin_native_run(ctx, _run_id(run_id))
    detail = await process_service.get_run_detail(
        _run_id(run_id),
        refresh_if_stale=refresh_if_stale,
    )
    if detail is None:
        raise ValueError(f"Process run not found: {run_id}")
    return dict(detail.model_dump(mode="json"))


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_refresh_run",
    description="Refresh any agent's active process run from its engine.",
)
async def process_admin_refresh_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:
    await _admin_native_run(ctx, _run_id(run_id), control=True)
    run = await process_service.refresh_run(_run_id(run_id))
    return dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_cancel_run",
    description="Cancel any agent's active process run.",
)
async def process_admin_cancel_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:
    await _admin_native_run(ctx, _run_id(run_id), control=True)
    run = await process_service.cancel_run(_run_id(run_id))
    return dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_retry_run",
    description="Retry any agent's failed or cancelled process run.",
)
async def process_admin_retry_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:
    await _admin_native_run(ctx, _run_id(run_id), control=True)
    response = await process_service.retry_run(_run_id(run_id))
    return dict(response.model_dump(mode="json"))


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_analyze_run",
    description="Analyze the result and errors of any agent's process run.",
)
async def process_admin_analyze_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:
    await _admin_native_run(ctx, _run_id(run_id))
    analysis = await process_service.analyze_run(_run_id(run_id))
    return dict(analysis.model_dump(mode="json"))


@mcp_tool("process_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval",

    name="process_admin_delete_run",
    description="Permanently delete any terminal process run.",
)
async def process_admin_delete_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    identifier = _run_id(run_id)
    await _admin_native_run(ctx, identifier, control=True)
    deleted = await process_service.delete_run(identifier)
    if not deleted:
        raise ValueError(f"Process run not found: {run_id}")
    return {"run_id": str(identifier), "deleted": True}
