"""Expose governed tools through Claude's in-process MCP transport."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput, HookMatcher, McpSdkServerConfig, McpServerConfig
from fastmcp.client.client import CallToolResult as ClientToolResult
from loguru import logger
from mcp.server import Server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool

from app.agent import AIMessage, ConversationReplyFilter
from app.agent.contracts import ToolEffectPolicy
from app.services.contracts import ToolExecutionContext, tool_execution
from app.services.facade import AuthorizationClosed, AuthorizationRequired, canonical_authorization_snapshot

from .claude_checkpoint import ClaudeEffectJournal, EffectStatus
from .claude_skills import SKILL_TOOLS, ClaudeSkills
from .claude_tool_discovery import CALL_TOOL, DISCOVERY_TOOLS, SEARCH_TOOLS, ClaudeToolDiscovery
from .mcp_toolset import ExecutionEvidenceClient
from .task_tool_scope import CONSOLE_RECOVERY_TOOLS, console_replay_key
from .tool_results import compact_tool_return, reported_tool_failure


def _replay_key(name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    if name in CONSOLE_RECOVERY_TOOLS:
        return "console_exec", console_replay_key(arguments)
    return name, canonical_authorization_snapshot(arguments)


_SERVER = "galaris"
_PREFIX = f"mcp__{_SERVER}__"
_TOOL_LIMIT_REACHED = "The Galaris tool call limit has been reached."
RESERVED_TOOLS = SKILL_TOOLS | DISCOVERY_TOOLS


class ClaudeMcp:
    """Bind each physical MCP call to the permission hook for that SDK tool ID."""

    def __init__(
        self, client: ExecutionEvidenceClient, definitions: dict[str, Tool], *,
        authorize: Callable[[], Awaitable[None]], tool_limit: int,
        policies: dict[str, ToolEffectPolicy] | None = None, journal: ClaudeEffectJournal | None = None,
        tool_lock: asyncio.Lock | None = None,
        conversation: bool = False,
        skills: ClaudeSkills | None = None,
        discovery: ClaudeToolDiscovery | None = None,
        durable_tool_budget: bool = False,
        reserve_tool: Callable[[int], Awaitable[bool]] | None = None,
    ) -> None:
        self.client = client
        self._skills = skills
        self._discovery = discovery
        self.definitions = {name: tool for name, tool in definitions.items() if name not in RESERVED_TOOLS}
        self._physical_names = frozenset(self.definitions)
        if discovery is not None:
            self._physical_names |= discovery.candidate_names
            self.definitions.update(discovery.definitions)
        if skills is not None:
            self.definitions.update(skills.definitions)
        self.authorize = authorize
        self.tool_limit = tool_limit
        self._durable_tool_budget = durable_tool_budget
        self._reserve_tool = reserve_tool
        self._prior_tool_calls = journal.tool_calls_used if journal is not None and durable_tool_budget else 0
        self._policies: dict[str, ToolEffectPolicy] = {
            name: policy for name, policy in (policies or {}).items() if name in self._physical_names
        }
        self._journal = journal
        self._effect_lock = tool_lock if tool_lock is not None else asyncio.Lock()
        self._turn_boundary = _ClaudeTurnBoundary() if conversation else None
        self._proposals: dict[str, tuple[str, str]] = {}
        self._dispatched: set[str] = set()
        self._previous: set[tuple[str, str]] = set()
        if journal is not None:
            self._previous.update(_replay_key(name, arguments) for name, arguments in journal.previous_calls())
        self._completed: list[AIMessage] = []

    @property
    def allowed_tools(self) -> list[str]:
        return [f"{_PREFIX}{name}" for name in self.definitions]

    def server_config(self) -> dict[str, McpServerConfig]:
        server = Server[dict[str, Any]](_SERVER, on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        return {_SERVER: McpSdkServerConfig(type="sdk", name=_SERVER, instance=server)}

    def hook(self) -> HookMatcher:
        return HookMatcher(hooks=[self._pre_tool], on_failure="block")

    async def observe_assistant(self, event: dict[str, Any]) -> None:
        if self._turn_boundary is not None:
            await self._turn_boundary.observe(event)

    def _has_proposal_slot(self, call_id: str) -> bool:
        return call_id not in self._proposals and not self._tool_limit_reached()

    def _tool_limit_reached(self) -> bool:
        return self._prior_tool_calls + len(self._proposals) >= self.tool_limit

    async def _pre_tool(self, event: HookInput, tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        reason = "This tool invocation was not admitted by Galaris."
        if event["hook_event_name"] == "PreToolUse":
            name = event["tool_name"].removeprefix(_PREFIX)
            call_id = event["tool_use_id"]
            discovery = self._discovery
            if (event["tool_name"].startswith(_PREFIX) and name in self.definitions and
                call_id == tool_use_id and 0 < len(call_id) <= 500 and self._has_proposal_slot(call_id)):
                boundary = self._turn_boundary
                if name == CALL_TOOL and (discovery is None or discovery.revealed_call(event["tool_input"]) is None):
                    reason = "Use an exact tool name from a search result in this task attempt and pass its arguments."
                elif boundary is not None and not await boundary.permits(call_id):
                    reason = "Use tools only for the current authenticated message. Answer without the invented turn."
                elif self._has_proposal_slot(call_id):
                    # Parallel hooks can wake together when the assistant message closes.
                    self._proposals[call_id] = (name, canonical_authorization_snapshot(event["tool_input"]))
                    return {}
            if self._tool_limit_reached():
                reason = _TOOL_LIMIT_REACHED
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}

    async def _list_tools(self, _context: object, _params: object) -> ListToolsResult:
        return ListToolsResult(tools=list(self.definitions.values()))

    async def _call_tool(self, _context: object, params: CallToolRequestParams) -> CallToolResult:
        meta = params.meta or {}
        call_id: object = meta.get("claudecode/toolUseId")
        arguments = params.arguments or {}
        if (not isinstance(call_id, str) or self._proposals.get(call_id) != (
                params.name, canonical_authorization_snapshot(arguments),
            )
            or call_id in self._dispatched):
            return _tool_error("This call did not match an authorized tool invocation.")
        self._dispatched.add(call_id)
        name = params.name
        if name == CALL_TOOL:
            discovery = self._discovery
            target = discovery.revealed_call(arguments) if discovery is not None else None
            if target is None:
                return _tool_error("This tool was not discovered in this Galaris attempt.")
            name, arguments = target.name, target.arguments
        if _replay_key(name, arguments) in self._previous:
            return _tool_error("This exact tool call is already recorded in an earlier Galaris attempt.")
        started = monotonic()
        execution = ToolExecutionContext(uuid4(), name)
        async with self._effect_lock if self._journal is not None else nullcontext():
            wire = await self._dispatch(call_id, execution, arguments)
        self._record_result(execution, call_id, arguments, wire, started)
        return wire

    def _record_result(self, execution: ToolExecutionContext, call_id: str, arguments: dict[str, Any],
                       wire: CallToolResult, started: float) -> None:
        text = "\n".join(part.text for part in wire.content if isinstance(part, TextContent))
        if execution.tool_name in SKILL_TOOLS and not wire.is_error:
            text = "Galaris skill accessed."
        if execution.tool_name == SEARCH_TOOLS and not wire.is_error:
            text = "Galaris tool search completed."
        data = compact_tool_return(wire.structured_content)
        self._completed.append(AIMessage(
            type="tool", content=text[:4_000], tool_name=execution.tool_name, tool_arguments=arguments,
            tool_result=cast(dict[str, Any], data) if isinstance(data, dict) else None,
            tool_call_external_id=call_id, execution_time=monotonic() - started,
            success=not wire.is_error, stream_id=f"claude-tool:{execution.operation_id}", stream_mode="snapshot",
        ))

    async def resolve_pending(self, decision: str) -> dict[str, object]:
        async with self._effect_lock:
            return await self._resolve_pending(decision)

    async def _resolve_pending(self, decision: str) -> dict[str, object]:
        journal = self._journal
        pending = journal.pending if journal is not None else None
        if pending is None or journal is None:
            raise ValueError("There is no Claude tool authorization to continue.")
        started = monotonic()
        await self.authorize()
        execution = ToolExecutionContext(pending.operation_id, pending.name)
        if decision in {"executing", "completed", "outcome_unknown"}:
            wire = _tool_error("Galaris cannot reconcile the earlier tool result.")
            status, receipt = "outcome_unknown", {"authorization_status": decision}
        elif (decision != "approved" or pending.name not in self._physical_names
                or self._policies.get(pending.name, "read") != pending.policy):
            wire = _tool_error("The Galaris tool authorization is no longer available.")
            status, receipt = "rejected", {"authorization_status": decision, "available": False}
        else:
            execution.authorization_continuation = pending.continuation(journal.run_id)
            await journal.resume_effect()
            await self.authorize()
            wire, status, receipt = await self._invoke(execution, pending.arguments)
            if status == "waiting_for_authorization":
                status, receipt = "outcome_unknown", None
        await journal.finish(status, receipt=receipt, wait_for_children=execution.wait_for_children)
        self._record_result(execution, pending.tool_id, pending.arguments, wire, started)
        return {"tool_call_id": pending.tool_id, "tool_name": pending.name, "status": status, "receipt": receipt}

    async def _dispatch(self, call_id: str, execution: ToolExecutionContext, arguments: dict[str, Any]) -> CallToolResult:
        try:
            await self.authorize()
        except PermissionError:
            return _tool_error("This Galaris attempt is no longer active.")
        journal = self._journal
        if journal is not None and journal.unresolved:
            return _tool_error("Earlier effects or authorization must be reconciled before another tool can run.")
        policy = self._policies.get(execution.tool_name, "read")
        effect = policy != "read"
        if effect and journal is None:
            return _tool_error("This tool requires a durable Galaris effect journal.")
        if self._reserve_tool is not None:
            try:
                reserved = await self._reserve_tool(journal.tool_calls_used if journal is not None else 0)
            except PermissionError:
                return _tool_error("This Galaris attempt is no longer active.")
            if not reserved:
                return _tool_error(_TOOL_LIMIT_REACHED)
        if journal is not None and (effect or self._durable_tool_budget):
            if effect:
                await journal.start(operation_id=execution.operation_id, tool_id=call_id,
                                    name=execution.tool_name, arguments=arguments, effect_policy=policy,
                                    count_tool=self._durable_tool_budget)
            else:
                await journal.reserve_tool()
            try:
                await self.authorize()
            except PermissionError:
                if effect:
                    await journal.finish("rejected", receipt={"reason": "attempt_no_longer_active"})
                return _tool_error("This Galaris attempt is no longer active.")
        wire, status, receipt = await self._invoke(execution, arguments)
        if journal is not None and (policy != "read" or status == "waiting_for_authorization" or execution.wait_for_children):
            if policy == "read":
                await journal.start(operation_id=execution.operation_id, tool_id=call_id,
                                    name=execution.tool_name, arguments=arguments, effect_policy=policy)
            await journal.finish(status, receipt=receipt, wait_for_children=execution.wait_for_children)
        return wire

    async def _invoke(
        self, execution: ToolExecutionContext, arguments: dict[str, Any],
    ) -> tuple[CallToolResult, EffectStatus, object]:
        skills = self._skills
        if skills is not None and execution.tool_name in skills.definitions:
            wire = await skills.call(execution.tool_name, arguments)
            return wire, "rejected" if wire.is_error else "completed", None
        discovery = self._discovery
        try:
            if discovery is not None:
                if execution.tool_name == SEARCH_TOOLS:
                    wire = await discovery.search(arguments, self.authorize)
                    return wire, "rejected" if wire.is_error else "completed", None
                if execution.tool_name in discovery.candidate_names and not await discovery.is_live(execution.tool_name):
                    return _tool_error("This discovered Galaris tool is no longer available."), "rejected", None
            with tool_execution(execution):
                result = cast(ClientToolResult, await self.client.call_tool(execution.tool_name, arguments))
        except AuthorizationRequired as exc:
            journal = self._journal
            receipt = journal.authorization_receipt(execution.operation_id, exc.request_id, exc.continuation) if journal else None
            return (_tool_error("This Galaris tool requires authorization."), "waiting_for_authorization",
                    receipt)
        except AuthorizationClosed as exc:
            status = "outcome_unknown" if exc.status in {"executing", "completed", "outcome_unknown"} else "rejected"
            return (_tool_error("The authorization for this Galaris tool is no longer available."),
                    status, {"authorization_status": exc.status})
        except Exception as exc:
            if execution.tool_name == SEARCH_TOOLS and isinstance(exc, PermissionError):
                return _tool_error("This Galaris attempt is no longer active."), "rejected", None
            logger.warning("Embedded tool {} failed: {}", execution.tool_name, type(exc).__name__)
            status: EffectStatus = "rejected" if execution.outcome == "rejected" else "outcome_unknown"
            return _tool_error("Galaris could not confirm the tool result."), status, None
        content = list(result.content)
        if not content and result.structured_content is not None:
            content.append(TextContent(type="text", text=json.dumps(result.structured_content, ensure_ascii=False)))
        evidence = result.structured_content if result.structured_content is not None else "\n".join(
            part.text for part in content if isinstance(part, TextContent)
        )
        failed = result.is_error or reported_tool_failure(evidence) is not None
        status = ("rejected" if execution.outcome == "rejected" else "outcome_unknown") if failed else "completed"
        wire = CallToolResult(content=content, structured_content=result.structured_content, is_error=failed)
        return wire, status, compact_tool_return(evidence)

    def drain(self) -> list[AIMessage]:
        messages, self._completed = self._completed, []
        return messages


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


class _ClaudeTurnBoundary:
    """Pair the complete assistant response with the IDs admitted by PreToolUse."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._reply = ConversationReplyFilter(strip_leading=False)
        self._calls: set[str] = set()
        self._decisions: dict[str, bool] = {}

    async def observe(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self._reply = ConversationReplyFilter(strip_leading=False)
            self._calls.clear()
        elif kind == "content_block_start":
            block = event.get("content_block")
            if isinstance(block, dict):
                data = cast(dict[str, object], block)
                if data.get("type") == "tool_use" and isinstance(identifier := data.get("id"), str):
                    self._calls.add(identifier)
        elif kind == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, dict):
                data = cast(dict[str, object], delta)
                if data.get("type") == "text_delta" and isinstance(content := data.get("text"), str):
                    self._reply.feed(content)
        elif kind == "message_stop":
            self._reply.finish()
            async with self._condition:
                self._decisions.update((identifier, not self._reply.truncated) for identifier in self._calls)
                self._condition.notify_all()

    async def permits(self, call_id: str) -> bool:
        try:
            async with asyncio.timeout(4), self._condition:
                await self._condition.wait_for(lambda: call_id in self._decisions)
                return self._decisions[call_id]
        except TimeoutError:
            return False
