"""MCP module routes.

Two endpoint families are exposed:

1. MCP token CRUD under ``/api/agents/{agent_id}/mcp-tokens``, protected by
   ``AGENT_EDIT`` and used by the agent settings UI.

2. The independently authenticated Streamable HTTP endpoint
   ``/api/mcp/{agent_code}``, using a dedicated bearer capability token.
"""

from typing import List

from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from starlette.types import Receive, Scope, Send

from core.authorize import (
    Privileges,
    RequireAllPrivilegesAssertion,
    authorize,
    independent_auth,
)
from core.database import get_db_session
from core.i18n import tr
from app.agent import agent_service, current_management_scope

from . import service as mcp_token_service
from .schemas import (
    AgentMcpTokenCreate,
    AgentMcpTokenUpdate,
    AgentMcpTokenResponse,
    AgentMcpTokenCreateResponse,
)

router = APIRouter(tags=["MCP"])


# ════════════════════════════════════════════════════════════════════════════
# Agent MCP token CRUD (RBAC: AGENT_EDIT and MCP_API_ACCESS)
# ════════════════════════════════════════════════════════════════════════════


async def _get_agent_or_404(agent_id: int):
    scope = await current_management_scope()
    agent = await agent_service.get(agent_id, agent_ids=scope.agent_ids)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("mcp_api.errors.agent_not_found"),
        )
    return agent


@router.get("/agents/{agent_id}/mcp-tokens", response_model=List[AgentMcpTokenResponse])
@authorize(
    privileges=[Privileges.AGENT_EDIT, Privileges.MCP_API_ACCESS],
    assertion=RequireAllPrivilegesAssertion,
    params={
        "required_privileges": [
            Privileges.AGENT_EDIT,
            Privileges.MCP_API_ACCESS,
        ]
    },
)
async def list_agent_mcp_tokens(agent_id: int):
    """List an agent's MCP tokens with masked values."""
    await _get_agent_or_404(agent_id)
    return await mcp_token_service.list_tokens_for_agent(agent_id)


@router.post(
    "/agents/{agent_id}/mcp-tokens",
    response_model=AgentMcpTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=[Privileges.AGENT_EDIT, Privileges.MCP_API_ACCESS],
    assertion=RequireAllPrivilegesAssertion,
    params={
        "required_privileges": [
            Privileges.AGENT_EDIT,
            Privileges.MCP_API_ACCESS,
        ]
    },
)
async def create_agent_mcp_token(agent_id: int, data: AgentMcpTokenCreate = AgentMcpTokenCreate()):
    """Create an agent MCP token; plaintext is returned only once."""
    await _get_agent_or_404(agent_id)
    db_token, plain_token = await mcp_token_service.create_token_for_agent(agent_id, data)
    return AgentMcpTokenCreateResponse(
        id=db_token.id,
        agent_id=db_token.agent_id,
        label=db_token.label,
        token=plain_token,
        enabled=db_token.enabled,
        created_at=db_token.created_at,
    )


@router.put("/agents/{agent_id}/mcp-tokens/{token_id}", response_model=AgentMcpTokenResponse)
@authorize(
    privileges=[Privileges.AGENT_EDIT, Privileges.MCP_API_ACCESS],
    assertion=RequireAllPrivilegesAssertion,
    params={
        "required_privileges": [
            Privileges.AGENT_EDIT,
            Privileges.MCP_API_ACCESS,
        ]
    },
)
async def update_agent_mcp_token(agent_id: int, token_id: int, data: AgentMcpTokenUpdate):
    """Update an MCP token label or enabled state."""
    await _get_agent_or_404(agent_id)
    token = await mcp_token_service.update_token(token_id, agent_id, data)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("mcp_api.errors.token_not_found"),
        )
    return token


@router.delete(
    "/agents/{agent_id}/mcp-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT
)
@authorize(
    privileges=[Privileges.AGENT_EDIT, Privileges.MCP_API_ACCESS],
    assertion=RequireAllPrivilegesAssertion,
    params={
        "required_privileges": [
            Privileges.AGENT_EDIT,
            Privileges.MCP_API_ACCESS,
        ]
    },
)
async def delete_agent_mcp_token(agent_id: int, token_id: int):
    """Delete and revoke an agent MCP token."""
    await _get_agent_or_404(agent_id)
    deleted = await mcp_token_service.delete_token(token_id, agent_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("mcp_api.errors.token_not_found"),
        )
    return None


# ════════════════════════════════════════════════════════════════════════════
# Capability-authenticated per-agent Streamable HTTP MCP endpoint
# ════════════════════════════════════════════════════════════════════════════


class _AlreadySentResponse(Response):
    """Sentinel response for endpoints that write directly to the ASGI channel.

    Streamable HTTP already emits the full response through ``request._send``.
    A normal Starlette response would emit a second ``http.response.start`` and
    break ``BaseHTTPMiddleware``, so this response deliberately writes nothing.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        return


@router.api_route(
    "/mcp/{agent_code}",
    methods=["GET", "POST", "DELETE"],
    include_in_schema=False,
)
@independent_auth(reason="Agent-scoped MCP bearer capability token")
async def agent_mcp_endpoint(agent_code: str, request: Request) -> Response:
    """Serve an agent's stateless unified MCP endpoint over Streamable HTTP.

    Native Galaris tools and external MCP tools are combined. Authentication
    uses ``Authorization: Bearer <agent MCP token>``.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    # app.tools centrally builds the aggregated native and external tool server.
    from app.tools.mcp_loader import build_agent_mcp

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("mcp_api.errors.token_required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with get_db_session():
        agent = await agent_service.get_by_code(agent_code)
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=await tr("mcp_api.errors.agent_not_found"),
            )
        matched = await mcp_token_service.get_enabled_token_by_value(agent.id, token)
        if matched is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=await tr("mcp_api.errors.invalid_token"),
                headers={"WWW-Authenticate": "Bearer"},
            )
        # The gateway is stateless. Recover the agent's active task so task-aware
        # tools receive a task ID. This is unambiguous because the scheduler
        # serializes execution for each agent to at most one active task.
        from app.agent import get_current_task

        mcp_server = await build_agent_mcp(
            agent.id,
            runtime=agent.agent_driver,
            task_id=get_current_task(agent.id),
        )

    logger.info("MCP HTTP request for agent={} ({})", agent.code, request.method)

    # Each stateless request rebuilds the server without a global lifecycle. The
    # manager writes the complete ASGI response itself.
    manager = StreamableHTTPSessionManager(
        app=mcp_server._mcp_server,  # type: ignore[attr-defined]
        json_response=False,
        stateless=True,
    )
    async with manager.run():
        await manager.handle_request(
            request.scope, request.receive, request._send  # type: ignore[attr-defined]
        )
    return _AlreadySentResponse()
