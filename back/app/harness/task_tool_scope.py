"""Select the Task tool presentation shared by the embedded harnesses."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from app.agent.contracts import AgentRunRequest
from app.console import ConsoleResult, ConsoleRunResource, resolve_ssh_connection
from app.file_share import ResourceContext, resource_accessible
from app.services import list_enabled_native_mcp_definitions
from app.services.facade import canonical_authorization_snapshot, canonical_service_call


_DELIVERY_TOOLS = frozenset({
    "messenger_room_send_message", "messenger_send_message_to_user", "messenger_room_send_file",
    "messenger_send_file_to_user",
})
_SCOPED_PROCESS_TOOLS = frozenset({"process_start", "process_analyze_run"})
_FILE_COMPANIONS = frozenset({"file_schemes", "file_list", "file_info", "file_read"})
CONSOLE_RECOVERY_TOOLS = frozenset({"console_exec", "console_start"})
_SCOPED_TOOL_COMPANIONS: dict[str, frozenset[str]] = {
    # Artifact authors need read and inspection tools to verify the result.
    "file_write": _FILE_COMPANIONS,
    "file_create": _FILE_COMPANIONS,
    "file_append": _FILE_COMPANIONS,
    "file_edit": _FILE_COMPANIONS,
    # Mail recipients can require an authorized Memory lookup.
    "mail_send": frozenset({"file_search", "file_read"}),
    "process_start": frozenset({"file_list", "file_read"}),
}


@dataclass(frozen=True)
class TaskToolScope:
    eager_names: set[str] | None
    excluded_names: frozenset[str]
    delivery_recovery: bool


def task_tool_scope(task: AgentRunRequest) -> TaskToolScope:
    data = task.data
    selected: set[str] = set()
    raw_plan_tools = data.get("plan_tools")
    if isinstance(raw_plan_tools, list):
        selected.update(str(item).strip() for item in cast(list[Any], raw_plan_tools) if str(item).strip())
    # Older plans can name exact MCP functions directly in the objective.
    if task.parent_id is not None and not selected:
        selected.update(re.findall(r"(?<![\w])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)(?![\w])", task.objective or ""))
    if data.get("goal_referrer_type") == "AGENT":
        selected.add("task_run")

    excluded: frozenset[str] = frozenset()
    if task.parent_id is not None:
        allowed_delivery: set[str] = selected if data.get("delivery_policy") == "required" else set()
        excluded = _DELIVERY_TOOLS - allowed_delivery
    if not selected:
        return TaskToolScope(None, excluded, False)
    legacy = selected & {"task_stop", "task_work_update"}
    selected.difference_update(legacy | excluded)
    selected.update(canonical_service_call(name, {})[0] for name in legacy)
    recovery = data.get("delivery_recovery")
    if isinstance(recovery, Mapping) and cast(Mapping[str, object], recovery).get("status") == "running":
        return TaskToolScope(selected, excluded, True)
    for name in tuple(selected):
        selected.update(_SCOPED_TOOL_COMPANIONS.get(name, ()))
    return TaskToolScope(selected | _SCOPED_PROCESS_TOOLS, excluded, False)


def console_replay_key(arguments: dict[str, Any]) -> str:
    # Both tool variants can dispatch the same command. Waiting for its
    # completion or changing the timeout does not create a different operation.
    normalized = {**arguments, "cwd": arguments.get("cwd", ".")}
    normalized.pop("timeout_s", None)
    return canonical_authorization_snapshot(normalized)


async def recover_console_receipt(console: ConsoleRunResource | None, name: str, operation_id: UUID) -> ConsoleResult | None:
    if console is None:
        return None
    allow_running = name == "console_start"
    try:
        receipt = await console.execution.recover_operation(operation_id, allow_running=allow_running)
    except Exception:
        # A failed remote lookup cannot establish the outcome of this operation.
        return None
    if (receipt is None or receipt.run_id != operation_id or receipt.status == "outcome_unknown"
            or (receipt.status == "running" and not allow_running)):
        return None
    return receipt


async def task_receipts_are_current(
    agent_id: int, task_id: UUID, names: set[str], documents: set[str], *, console_scope: str | None = None,
) -> bool:
    """Check current tool and resource access before using recorded Task effects."""
    if names & CONSOLE_RECOVERY_TOOLS:
        connection = await resolve_ssh_connection(agent_id)
        if connection is None or connection.recovery_scope != console_scope:
            return False
    allowed = await list_enabled_native_mcp_definitions(
        agent_id, runtime="internal", task_id=task_id, allowed_tool_names=names,
    )
    if not names <= {definition.name for definition in allowed}:
        return False
    context = ResourceContext(agent_id, "internal", task_id)
    for uri in documents:
        if not await resource_accessible(context, uri, "read"):
            return False
    return True
