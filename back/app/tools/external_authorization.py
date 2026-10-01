"""Authorization at the last local boundary before a remote MCP invocation."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid4
from jsonschema import validators  # pyright: ignore[reportMissingTypeStubs]

from fastmcp.prompts import PromptResult
from fastmcp.resources import ResourceResult
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import McpError
from mcp.types import CallToolRequestParams, ErrorData, GetPromptRequestParams, ReadResourceRequestParams

from .authorization import AUTHORIZATION_META_KEY, AuthorizationAction, AuthorizationClosed, AuthorizationRequired, claim_action, finish_action, tool_authorization_configuration
from .contracts import EXECUTION_META_KEY, current_tool_execution
from .mcp_loader import resolve_live_connection


class ExternalAuthorizationMiddleware(Middleware):
    def __init__(self, agent_id: int, connection_id: int, tool_id: int, *, runtime: str,
                 context_key: str, conversation_only: bool, runtime_grant_id: UUID | None = None) -> None:
        self.agent_id, self.connection_id, self.tool_id = agent_id, connection_id, tool_id
        self.runtime, self.context_key, self.conversation_only = runtime, context_key, conversation_only
        self.runtime_grant_id = runtime_grant_id

    async def _claim(self, context: MiddlewareContext[Any], name: str, arguments: dict[str, Any],
                     kind: Literal["tool", "resource", "prompt"], schema: object, *, policy_name: str | None = None) -> UUID | None:
        tool, params, _ = await resolve_live_connection(self.agent_id, self.connection_id, self.tool_id,
                                                       conversation_only=self.conversation_only)
        execution = current_tool_execution()
        callback = execution.operation_id if execution is not None else uuid4()
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        raw: Any = getattr(request.meta, EXECUTION_META_KEY, None) if request is not None and request.meta else None
        authorization_meta: Any = getattr(request.meta, AUTHORIZATION_META_KEY, None) if request is not None and request.meta else None
        continuation = cast(dict[str, Any], authorization_meta).get("continuation") if isinstance(authorization_meta, dict) else None
        if execution is None and isinstance(raw, dict):
            try:
                callback = UUID(str(cast(dict[str, Any], raw).get("operation_id")))
            except ValueError:
                pass
        return await claim_action(AuthorizationAction(
            agent_id=self.agent_id, tool_id=self.tool_id, connection_id=self.connection_id,
            runtime=self.runtime, context_key=self.context_key, callback_key=str(callback),
            name=name, arguments=arguments, kind=kind,
            configuration={"tool": tool_authorization_configuration(tool), "params": params, "schema": schema,
                **({"policy_name": policy_name} if policy_name else {})},
            policy_name=policy_name,
            runtime_grant_id=self.runtime_grant_id,
            preview=f"{tool.label}: {kind} {name}",
            continuation=str(continuation) if continuation else None,
        ))

    @staticmethod
    def _control(exc: AuthorizationRequired | AuthorizationClosed) -> dict[str, Any]:
        return {AUTHORIZATION_META_KEY: {"request_id": str(exc.request_id),
                "status": "pending" if isinstance(exc, AuthorizationRequired) else exc.status,
                "continuation": exc.continuation if isinstance(exc, AuthorizationRequired) else None,
                "disposition": "authorization_required" if isinstance(exc, AuthorizationRequired) else "authorization_closed"}}

    async def on_call_tool(self, context: MiddlewareContext[CallToolRequestParams],
                           call_next: CallNext[CallToolRequestParams, ToolResult]) -> ToolResult:
        identifier: UUID | None = None
        try:
            # Discovery and argument validation precede approval and cannot invoke the tool.
            assert context.fastmcp_context is not None
            tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
            if tool is None:
                raise PermissionError("External MCP tool is unavailable")
            cast(Any, validators).validator_for(tool.parameters)(tool.parameters).validate(context.message.arguments or {})
            identifier = await self._claim(context, context.message.name, context.message.arguments or {}, "tool", tool.parameters)
            result = await call_next(context)
            if result.meta:
                result.meta.pop(AUTHORIZATION_META_KEY, None)
                result.meta.pop(EXECUTION_META_KEY, None)
            await finish_action(identifier, receipt=result, outcome="outcome_unknown" if result.is_error else "completed")
            return result
        except (AuthorizationRequired, AuthorizationClosed) as exc:
            return ToolResult(content=str(exc), is_error=True, meta=self._control(exc))
        except BaseException:
            await finish_action(identifier, outcome="outcome_unknown")
            raise

    async def on_read_resource(self, context: MiddlewareContext[ReadResourceRequestParams],
                               call_next: CallNext[ReadResourceRequestParams, ResourceResult]) -> ResourceResult:
        identifier: UUID | None = None
        try:
            assert context.fastmcp_context is not None
            uri = str(context.message.uri)
            resource = await context.fastmcp_context.fastmcp.get_resource(uri)
            template = None if resource is not None else await context.fastmcp_context.fastmcp.get_resource_template(uri)
            if resource is None and template is None:
                raise PermissionError("External MCP resource is unavailable")
            schema = resource.model_dump(mode="json") if resource is not None else template.model_dump(mode="json") if template else {}
            identifier = await self._claim(context, uri, {"uri": uri}, "resource", schema,
                policy_name=template.uri_template if template else None)
            result = await call_next(context)
            await finish_action(identifier, receipt=result)
            return result
        except (AuthorizationRequired, AuthorizationClosed) as exc:
            raise McpError(ErrorData(code=-32001, message=str(exc), data=self._control(exc))) from exc
        except BaseException:
            await finish_action(identifier, outcome="outcome_unknown")
            raise

    async def on_get_prompt(self, context: MiddlewareContext[GetPromptRequestParams],
                            call_next: CallNext[GetPromptRequestParams, PromptResult]) -> PromptResult:
        identifier: UUID | None = None
        try:
            assert context.fastmcp_context is not None
            prompt = await context.fastmcp_context.fastmcp.get_prompt(context.message.name)
            if prompt is None:
                raise PermissionError("External MCP prompt is unavailable")
            arguments = dict(context.message.arguments or {})
            known = {argument.name for argument in prompt.arguments or []}
            required = {argument.name for argument in prompt.arguments or [] if argument.required}
            if set(arguments) - known or not required.issubset(arguments):
                raise ValueError("Invalid external MCP prompt arguments")
            identifier = await self._claim(context, context.message.name, dict(context.message.arguments or {}), "prompt", prompt.model_dump(mode="json"))
            result = await call_next(context)
            if result.meta:
                result.meta.pop(AUTHORIZATION_META_KEY, None)
                result.meta.pop(EXECUTION_META_KEY, None)
            await finish_action(identifier, receipt=result)
            return result
        except (AuthorizationRequired, AuthorizationClosed) as exc:
            raise McpError(ErrorData(code=-32001, message=str(exc), data=self._control(exc))) from exc
        except BaseException:
            await finish_action(identifier, outcome="outcome_unknown")
            raise
