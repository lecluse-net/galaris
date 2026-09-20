"""Self-service and restricted administrative business-process MCP tools."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import render_prompt, t

from . import process_service
from .schemas import (
    ProcessDefinitionCreate,
    ProcessDefinitionRead,
    ProcessDefinitionUpdate,
    ProcessFileInput,
    ProcessToolRead,
)


def _run_id(value: str) -> UUID:
    try:
        return UUID(value.strip())
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


@mcp_tool(
    "galaris",
    name="process_list",
    description="List only the business processes assigned to the current agent.",
)
async def process_list(ctx: McpToolContext) -> list[dict[str, Any]]:
    return await process_service.list_for_agent(ctx.agent_id)


@mcp_tool(
    "galaris",
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
    return {
        "workflow_id": process.engine_process_id,
        "label": process.label,
        "description": process.description,
        "tool_id": process.tool_id,
    }


@mcp_tool(
    "galaris",
    name="process_start",
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


@mcp_tool(
    "galaris",
    name="process_list_runs",
    description="List only business-process runs launched for the current agent.",
)
async def process_list_runs(
    ctx: McpToolContext,
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    runs = await process_service.list_runs(
        agent_id=ctx.agent_id, workflow_id=workflow_id, status=status, limit=limit
    )
    return [
        (await process_service._run_read(run)).model_dump(mode="json")  # pyright: ignore[reportPrivateUsage]
        for run in runs
    ]


@mcp_tool(
    "galaris",
    name="process_get_run",
    description="Return one run belonging to the current agent and refresh it when needed.",
)
async def process_get_run(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    run = await process_service.get_run(_run_id(run_id))
    if run is None or run.launcher_agent_id != ctx.agent_id:
        raise PermissionError(t("process.errors.run_not_visible", await context_language(ctx)))
    detail = await process_service.get_run_detail(_run_id(run_id), refresh_if_stale=True)
    if detail is None or detail.launcher_agent_id != ctx.agent_id:
        raise PermissionError(t("process.errors.run_not_visible", await context_language(ctx)))
    return detail.model_dump(mode="json", exclude={"events"})


@mcp_tool(
    "galaris",
    name="process_analyze_run",
    description="Explain the result and errors of one run belonging to the current agent.",
)
async def process_analyze_run(ctx: McpToolContext, run_id: str) -> dict[str, Any]:
    run = await process_service.get_run(_run_id(run_id))
    if run is None or run.launcher_agent_id != ctx.agent_id:
        raise PermissionError(t("process.errors.run_not_visible", await context_language(ctx)))
    return (await process_service.analyze_run(run.id)).model_dump(mode="json")


@mcp_tool(
    "process_admin",
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


@mcp_tool(
    "process_admin",
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


@mcp_tool(
    "process_admin",
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
    return [_definition_payload(item, tool_codes) for item in definitions]


@mcp_tool(
    "process_admin",
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
    tool_codes = await _process_tool_codes()
    return _definition_payload(definition, tool_codes)


@mcp_tool(
    "process_admin",
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


@mcp_tool(
    "process_admin",
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


@mcp_tool(
    "process_admin",
    name="process_admin_delete",
    description="Soft-delete any agent's process definition while preserving run history.",
)
async def process_admin_delete(
    ctx: McpToolContext,  # noqa: ARG001
    process_id: int,
) -> dict[str, Any]:

    if process_id <= 0:
        raise ValueError("process_id must be greater than zero")
    deleted = await process_service.delete_definition(process_id)
    if not deleted:
        raise ValueError(f"Process definition not found: {process_id}")
    return {"process_id": process_id, "deleted": True}


@mcp_tool(
    "process_admin",
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


@mcp_tool(
    "process_admin",
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
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )
    return [
        dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]
        for run in runs
    ]


@mcp_tool(
    "process_admin",
    name="process_admin_get_run",
    description="Return the complete details of any agent's process run.",
)
async def process_admin_get_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
    refresh_if_stale: bool = True,
) -> dict[str, Any]:

    detail = await process_service.get_run_detail(
        _run_id(run_id),
        refresh_if_stale=refresh_if_stale,
    )
    if detail is None:
        raise ValueError(f"Process run not found: {run_id}")
    return dict(detail.model_dump(mode="json"))


@mcp_tool(
    "process_admin",
    name="process_admin_refresh_run",
    description="Refresh any agent's active process run from its engine.",
)
async def process_admin_refresh_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    run = await process_service.refresh_run(_run_id(run_id))
    return dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]


@mcp_tool(
    "process_admin",
    name="process_admin_cancel_run",
    description="Cancel any agent's active process run.",
)
async def process_admin_cancel_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    run = await process_service.cancel_run(_run_id(run_id))
    return dict((await process_service._run_read(run)).model_dump(mode="json"))  # pyright: ignore[reportPrivateUsage]


@mcp_tool(
    "process_admin",
    name="process_admin_retry_run",
    description="Retry any agent's failed or cancelled process run.",
)
async def process_admin_retry_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    response = await process_service.retry_run(_run_id(run_id))
    return dict(response.model_dump(mode="json"))


@mcp_tool(
    "process_admin",
    name="process_admin_analyze_run",
    description="Analyze the result and errors of any agent's process run.",
)
async def process_admin_analyze_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    analysis = await process_service.analyze_run(_run_id(run_id))
    return dict(analysis.model_dump(mode="json"))


@mcp_tool(
    "process_admin",
    name="process_admin_delete_run",
    description="Permanently delete any terminal process run.",
)
async def process_admin_delete_run(
    ctx: McpToolContext,  # noqa: ARG001
    run_id: str,
) -> dict[str, Any]:

    identifier = _run_id(run_id)
    deleted = await process_service.delete_run(identifier)
    if not deleted:
        raise ValueError(f"Process run not found: {run_id}")
    return {"run_id": str(identifier), "deleted": True}
