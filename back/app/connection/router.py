"""API routes for connections and their EAV parameters."""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated, List, Literal, Optional, Dict, Any

from core.database import get_db
from core.user import require_web_session, get_current_user_id
from pydantic import AnyHttpUrl, Field, ValidationError
from core.authorize import Privileges, authorize, public
from core.i18n import render_prompt, tr
from app.agent import AgentManagementScope, current_management_scope
from .models import Connection, ConnectionParam
from .schemas import (
    Connection as ConnectionSchema,
    ConnectionCreate,
    ConnectionUpdate,
    ConnectionParam as ConnectionParamSchema,
    ConnectionParamCreate,
    ConnectionParamUpdate,
    ConnectionParamBulkCreate,
    ConnectionParamsResponse,
    AgentByParamResponse,
    TestMcpToolsRequest,
    TestMcpToolsResponse,
    McpToolInfo,
    ConnectionFunctionsResponse,
    FunctionStateUpdate,
    FunctionStateResolved,
    RefreshToolCatalogsResponse,
    SyncIntegratedConnectionsResponse,
)
from . import connection_service
from . import oauth_service
from .oauth_service import DevicePoll, DevicePollResult, OAuthCallback, OAuthStart, OAuthStartOptions, OAuthStatus
from app.tools import (
    refresh_agent_tool_catalog,
    refresh_agents_tool_catalogs,
    refresh_all_tool_catalogs,
    refresh_tool_catalogs,
    list_available_connection_functions,
    tool_service,
    sync_integrated_tool_connections,
)
from app.tools.mcp import build_mcp_server

from loguru import logger

router = APIRouter(prefix="/connections", tags=["connections"])


async def _message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"connection_api.{key}"), **values)


async def _require_agent(
    scope: AgentManagementScope,
    agent_id: int,
) -> None:
    if not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail=await _message("errors.not_found"))


async def _managed_connection(connection_id: int, *, editable: bool = False) -> Connection:
    scope = await current_management_scope()
    connection = await connection_service.get_connection(connection_id)
    if connection is None or not scope.allows(connection.agent_id):
        raise HTTPException(status_code=404, detail=await _message("errors.not_found"))
    if editable:
        await _editable_tool(connection.tool_id)
    return connection


async def _editable_tool(tool_id: int) -> None:
    try:
        await connection_service.require_editable_tool(tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# =============================================================================
# Connection endpoints.
# =============================================================================


@router.get("/function-permissions", dependencies=[Depends(require_web_session)])
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_function_permissions(agent_id: int | None = None,
                                    offset: int = Query(0, ge=0),
                                    limit: int = Query(50, ge=1, le=500)) -> dict[str, object]:
    from .function_permissions import list_permissions
    return await list_permissions(await current_management_scope(), agent_id=agent_id, offset=offset, limit=limit)


def _oauth_user() -> int:
    user_id = get_current_user_id()
    if user_id is None:
        raise HTTPException(status_code=401)
    return user_id


async def _oauth_error(exc: ValueError) -> HTTPException:
    key = str(exc) if isinstance(exc, oauth_service.OAuthError) else "configuration"
    callback_uri = exc.redirect_uri if isinstance(exc, oauth_service.OAuthError) else None
    message = render_prompt(await tr(f"connection_api.oauth.{key}"), redirect_uri=callback_uri or "")
    if isinstance(exc, oauth_service.OAuthError):
        logger.bind(oauth_error=key, provider_status=exc.provider_status, provider_error=exc.provider_error).warning(
            "MCP account authorization failed: {} (provider HTTP {}, code {})", key, exc.provider_status, exc.provider_error)
        if exc.provider_status is not None:
            message += " " + await _message("oauth.provider_response", status=exc.provider_status)
        if exc.provider_error:
            message += f" ({exc.provider_error})"
    return HTTPException(status_code=400, detail=message)


@router.get("/oauth/client-metadata")
@public(reason="Public OAuth client metadata; contains no account, connection, session or secret")
async def oauth_client_metadata() -> dict[str, object]:
    return oauth_service.client_document().model_dump(mode="json", exclude_none=True)


@router.get("/oauth/client-metadata/loopback/{scheme}/{host}/{port}")
@public(reason="Public OAuth client metadata for a loopback callback; contains no account or secret")
async def oauth_local_client_metadata(scheme: Literal["http", "https"], host: Literal["localhost", "127.0.0.1", "::1"],
                                      port: Annotated[int, Path(ge=1, le=65535)]) -> dict[str, object]:
    authority = f"[{host}]" if host == "::1" else host
    callback = str(AnyHttpUrl(f"{scheme}://{authority}:{port}/connection/oauth-callback"))
    return oauth_service.client_document(callback, force_loopback=True).model_dump(mode="json", exclude_none=True)


@router.get("/{connection_id}/oauth", response_model=OAuthStatus)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def oauth_status(connection_id: int) -> OAuthStatus:
    connection = await _managed_connection(connection_id)
    try:
        return await oauth_service.status(connection)
    except (oauth_service.OAuthError, ValidationError) as exc:
        raise await _oauth_error(exc) from None


@router.post("/{connection_id}/oauth/start", response_model=OAuthStart, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def oauth_start(connection_id: int, data: OAuthStartOptions | None = None) -> OAuthStart:
    connection = await _managed_connection(connection_id, editable=True)
    try:
        return await oauth_service.start(connection, _oauth_user(), data)
    except (oauth_service.OAuthError, ValidationError) as exc:
        raise await _oauth_error(exc) from None


@router.post("/{connection_id}/oauth/callback", status_code=204, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def oauth_callback(connection_id: int, data: OAuthCallback) -> None:
    connection = await _managed_connection(connection_id, editable=True)
    try:
        await oauth_service.complete(connection, data, _oauth_user())
    except (oauth_service.OAuthError, ValidationError) as exc:
        raise await _oauth_error(exc) from None
    await _refresh_agent_indexes([connection.agent_id])


@router.post("/{connection_id}/oauth/device", response_model=DevicePollResult, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def oauth_device(connection_id: int, data: DevicePoll) -> DevicePollResult:
    connection = await _managed_connection(connection_id, editable=True)
    try:
        result = await oauth_service.poll_device(connection, data, _oauth_user())
    except (oauth_service.OAuthError, ValidationError) as exc:
        raise await _oauth_error(exc) from None
    if result.connected:
        await _refresh_agent_indexes([connection.agent_id])
    return result


@router.delete("/{connection_id}/oauth", status_code=204, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def oauth_disconnect(connection_id: int) -> None:
    connection = await _managed_connection(connection_id, editable=True)
    await oauth_service.disconnect(connection)
    await _refresh_agent_indexes([connection.agent_id])

@router.get("/find-by-param", response_model=AgentByParamResponse)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def find_agents_by_param(
    tool_id: int = Query(..., description="Tool ID"),
    param_name: str = Query(..., description="Parameter name"),
    param_value: str = Query(..., description="Value to find")
):
    agent_ids = await connection_service.find_agents_by_param(
        tool_id, param_name, param_value
    )
    scope = await current_management_scope()
    agent_ids = [agent_id for agent_id in agent_ids if scope.allows(agent_id)]
    return AgentByParamResponse(agent_ids=agent_ids, count=len(agent_ids))


async def _refresh_connections_and_tool_catalogs() -> RefreshToolCatalogsResponse:
    """Create internal connections, reload remote MCP data and rebuild the index.

    This operation is idempotent and preserves every existing connection.
    """
    db = get_db()
    scope = await current_management_scope()
    if scope.agent_ids is None:
        created = await sync_integrated_tool_connections()
    else:
        created = sum(
            [
                await sync_integrated_tool_connections(agent_id)
                for agent_id in sorted(scope.agent_ids)
            ]
        )
    await db.commit()
    result = (
        await refresh_all_tool_catalogs()
        if scope.agent_ids is None
        else await refresh_tool_catalogs(
            agent_ids=scope.agent_ids,
            force_embeddings=False,
            prune_stale=False,
        )
    )
    await db.commit()
    return RefreshToolCatalogsResponse(
        created=created,
        agents_scanned=result.agents_scanned,
        agents_refreshed=result.agents_refreshed,
        agent_failures=result.agent_failures,
        source_failures=result.source_failures,
        tools_discovered=result.tools_discovered,
        documents_indexed=result.documents_indexed,
        embeddings_refreshed=result.embeddings_refreshed,
        documents_pruned=result.documents_pruned,
        semantic_available=result.semantic_available,
        degradation_reason=result.degradation_reason,
        complete=result.complete,
    )


@router.post("/refresh-tools", response_model=RefreshToolCatalogsResponse)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def refresh_connections_and_tool_catalogs() -> RefreshToolCatalogsResponse:
    """Unified administrator refresh for connections and every tool catalog."""

    return await _refresh_connections_and_tool_catalogs()


@router.post(
    "/sync-integrated",
    response_model=SyncIntegratedConnectionsResponse,
    deprecated=True,
)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def sync_integrated_connections() -> RefreshToolCatalogsResponse:
    """Compatibility alias for the unified refresh operation."""

    return await _refresh_connections_and_tool_catalogs()


async def _refresh_agent_indexes(agent_ids: List[int]) -> None:
    """Best-effort reconciliation after an authorization-affecting mutation."""

    if not agent_ids:
        return
    db = get_db()
    try:
        if len(agent_ids) == 1:
            await refresh_agent_tool_catalog(agent_ids[0])
        else:
            await refresh_agents_tool_catalogs(agent_ids)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Automatic tool catalog refresh failed for {} agent(s)",
            len(agent_ids),
        )


@router.get("", response_model=List[ConnectionSchema])
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_connections(
    tool_id: Optional[int] = Query(None, description="Filter by tool ID"),
    agent_id: Optional[int] = Query(None, description="Filter by agent ID"),
    active_only: bool = Query(False, description="Return active connections only"),
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    db: AsyncSession = Depends(get_db)
):
    scope = await current_management_scope()
    query = select(Connection)
    if tool_id is not None:
        query = query.where(Connection.tool_id == tool_id)
    if agent_id:
        query = query.where(Connection.agent_id == agent_id)
    if scope.agent_ids is not None:
        query = query.where(Connection.agent_id.in_(scope.agent_ids))
    if active_only:
        query = query.where(Connection.active == True)
    query = query.order_by(Connection.id).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{connection_id}", response_model=ConnectionSchema)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def get_connection(connection_id: int):
    return await _managed_connection(connection_id)


@router.post("", response_model=ConnectionSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def create_connection(data: ConnectionCreate):
    scope = await current_management_scope()
    await _require_agent(scope, data.agent_id)
    await _editable_tool(data.tool_id)
    existing = await connection_service.get_connection_by_agent_tool(
        data.tool_id, data.agent_id
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=await _message(
                "errors.duplicate",
                agent_id=data.agent_id,
                tool_id=data.tool_id,
            ),
        )
    connection = await connection_service.get_or_create_connection(
        data.tool_id, data.agent_id, active=data.active
    )
    if connection.active != data.active:
        updated = await connection_service.set_connection_active(
            connection.id,
            data.active,
        )
        if updated is not None:
            connection = updated
    await _refresh_agent_indexes([connection.agent_id])
    return connection


@router.patch("/{connection_id}", response_model=ConnectionSchema)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def update_connection(connection_id: int, update: ConnectionUpdate):
    db = get_db()
    connection = await _managed_connection(connection_id)
    from app.tools.facade import lock_tools

    await lock_tools([connection.tool_id, update.tool_id or connection.tool_id])
    connection = await _managed_connection(connection_id, editable=True)
    if update.tool_id is not None:
        await _editable_tool(update.tool_id)
    scope = await current_management_scope()
    previous_agent_id = connection.agent_id

    new_tool_id = update.tool_id if update.tool_id is not None else connection.tool_id
    new_agent_id = update.agent_id or connection.agent_id
    await _require_agent(scope, new_agent_id)

    if (update.tool_id is not None or update.agent_id is not None) and \
       (new_tool_id != connection.tool_id or new_agent_id != connection.agent_id):
        existing = await connection_service.get_connection_by_agent_tool(
            new_tool_id, new_agent_id
        )
        if existing and existing.id != connection_id:
            raise HTTPException(
                status_code=409,
                detail=await _message(
                    "errors.duplicate",
                    agent_id=new_agent_id,
                    tool_id=new_tool_id,
                ),
            )

    if update.tool_id is not None:
        connection.tool_id = update.tool_id
    if update.agent_id is not None:
        connection.agent_id = update.agent_id
    if update.active is not None:
        connection.active = update.active

    await db.commit()
    await db.refresh(connection)
    await _refresh_agent_indexes(
        sorted({previous_agent_id, connection.agent_id})
    )
    return connection


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def delete_connection(connection_id: int):
    connection = await _managed_connection(connection_id, editable=True)
    deleted = await connection_service.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=await _message("errors.not_found"))
    await _refresh_agent_indexes([connection.agent_id])
    logger.info("Connection {} and all its parameters deleted", connection_id)
    return None


# =============================================================================
# EAV parameter endpoints.
# =============================================================================

@router.get("/{connection_id}/params", response_model=ConnectionParamsResponse)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def get_connection_params(
    connection_id: int,
    decrypt: bool = Query(False, description="Deprecated; secrets are always write-only")
):
    del decrypt
    await _managed_connection(connection_id)
    connection, params, configured = await connection_service.get_params_for_api(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail=await _message("errors.not_found"))
    return ConnectionParamsResponse(
        connection_id=connection_id,
        tool_id=connection.tool_id,
        agent_id=connection.agent_id,
        params=params,
        configured_params=configured,
    )


@router.get("/{connection_id}/params/{param_name}", response_model=ConnectionParamSchema)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def get_single_param(
    connection_id: int,
    param_name: str,
    db: AsyncSession = Depends(get_db)
):
    await _managed_connection(connection_id)
    result = await db.execute(
        select(ConnectionParam).where(
            ConnectionParam.connection_id == connection_id,
            ConnectionParam.param_name == param_name
        )
    )
    param = result.scalar_one_or_none()
    if not param:
        raise HTTPException(
            status_code=404,
            detail=await _message(
                "errors.parameter_for_connection_not_found",
                parameter=param_name,
                connection_id=connection_id,
            ),
        )
    return await connection_service.redact_param(param)


@router.post("/{connection_id}/params", response_model=ConnectionParamSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def create_or_update_param(connection_id: int, param: ConnectionParamCreate):
    await _managed_connection(connection_id, editable=True)
    if param.connection_id != connection_id:
        raise HTTPException(
            status_code=400,
            detail=await _message(
                "errors.body_id_mismatch",
                body_id=param.connection_id,
                url_id=connection_id,
            ),
        )
    try:
        saved = await connection_service.set_param(
            param.connection_id, param.param_name, param.param_value
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = await connection_service.get_connection(connection_id)
    if connection is not None:
        await _refresh_agent_indexes([connection.agent_id])
    return await connection_service.redact_param(saved)


@router.post("/{connection_id}/params/bulk", response_model=List[ConnectionParamSchema], status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def create_or_update_params_bulk(connection_id: int, bulk_data: ConnectionParamBulkCreate):
    await _managed_connection(connection_id, editable=True)
    if bulk_data.connection_id != connection_id:
        raise HTTPException(
            status_code=400,
            detail=await _message(
                "errors.body_id_mismatch",
                body_id=bulk_data.connection_id,
                url_id=connection_id,
            ),
        )
    try:
        saved = await connection_service.set_params_bulk(
            bulk_data.connection_id, bulk_data.params
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = await connection_service.get_connection(connection_id)
    if connection is not None:
        await _refresh_agent_indexes([connection.agent_id])
    return await connection_service.redact_params(saved)


@router.patch("/{connection_id}/params/{param_name}", response_model=ConnectionParamSchema)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def update_connection_param(
    connection_id: int,
    param_name: str,
    update: ConnectionParamUpdate,
):
    await _managed_connection(connection_id, editable=True)
    db = get_db()
    result = await db.execute(
        select(ConnectionParam).where(
            ConnectionParam.connection_id == connection_id,
            ConnectionParam.param_name == param_name
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=404,
            detail=await _message("errors.parameter_not_found", parameter=param_name),
        )
    try:
        saved = await connection_service.set_param(
            connection_id, param_name, update.param_value
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = await connection_service.get_connection(connection_id)
    if connection is not None:
        await _refresh_agent_indexes([connection.agent_id])
    return await connection_service.redact_param(saved)


@router.delete("/{connection_id}/params/{param_name}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def delete_param(connection_id: int, param_name: str):
    await _managed_connection(connection_id, editable=True)
    deleted = await connection_service.delete_param(connection_id, param_name)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=await _message("errors.parameter_not_found", parameter=param_name),
        )
    connection = await connection_service.get_connection(connection_id)
    if connection is not None:
        await _refresh_agent_indexes([connection.agent_id])
    return None


@router.post("/test-mcp-tools", response_model=TestMcpToolsResponse)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def test_mcp_tools(data: TestMcpToolsRequest):
    logger.info("Testing MCP tools for tool_id={}", data.tool_id)

    tool_schema = await tool_service.get_tool_by_id(data.tool_id)
    if not tool_schema:
        return TestMcpToolsResponse(
            success=False,
            message=await _message("errors.tool_not_found", tool_id=data.tool_id),
            tools=[]
        )
    if not tool_schema.mcp:
        return TestMcpToolsResponse(
            success=False,
            message=await _message("errors.no_mcp", tool_id=data.tool_id),
            tools=[]
        )

    try:
        local_params: Dict[str, Any] = {
            key: value for key, value in data.params.items() if value not in (None, "")
        }
        connection_params = await connection_service.merge_with_global_params(
            data.tool_id,
            local_params,
            decrypt_passwords=True,
        )
        server = build_mcp_server(tool_schema, connection_params, prefix_tools=False)
        if not server:
            return TestMcpToolsResponse(
                success=False,
                message=await _message("errors.server_creation_failed"),
                tools=[],
            )

        async with server:
            tools = await server.list_tools()

        return TestMcpToolsResponse(
            success=True,
            message=await _message("tools_available", count=len(tools)),
            tools=[McpToolInfo(name=t.name, description=t.description or "") for t in tools]
        )
    except Exception as exc:
        logger.error(
            "MCP tool test failed (error_type={})",
            type(exc).__name__,
        )
        return TestMcpToolsResponse(
            success=False,
            message=await _message("errors.connection_error"),
            tools=[],
        )


# =============================================================================
# MCP function authorization endpoints.
# =============================================================================

@router.get("/{connection_id}/functions", response_model=ConnectionFunctionsResponse)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_connection_functions(connection_id: int):
    """List currently exposed MCP functions and their cascade state."""
    await _managed_connection(connection_id)
    result = await list_available_connection_functions(connection_id)
    return ConnectionFunctionsResponse(**result)


@router.put("/{connection_id}/functions/{function_name}", response_model=FunctionStateResolved, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def set_connection_function(connection_id: int, function_name: str, data: FunctionStateUpdate):
    """Apply a function state directly at connection level."""
    connection = await _managed_connection(connection_id)
    await connection_service.set_connection_function_state(connection_id, function_name, data.state, capability_kind=data.capability_kind)
    resolved = await connection_service.resolve_function(connection, function_name, capability_kind=data.capability_kind)
    # Policies are read from the database by discovery and before each call.
    # The shared index holds definitions, not permissions, and search reconciles
    # newly visible definitions itself. Saving a rule needs no remote discovery.
    return FunctionStateResolved(**resolved)


@router.put("/{connection_id}/functions/{function_name}/global", response_model=FunctionStateResolved, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def set_connection_function_global(connection_id: int, function_name: str, data: FunctionStateUpdate):
    """Apply a global function state at the connection's tool level."""
    return await _set_global_function_policy(connection_id, function_name, data)


async def _set_global_function_policy(
    connection_id: int,
    function_name: str,
    data: FunctionStateUpdate,
    *,
    inherit_connection: bool = False,
) -> FunctionStateResolved:
    connection = await _managed_connection(connection_id)
    scope = await current_management_scope()
    if not scope.is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await _message("errors.not_found"),
        )
    if inherit_connection:
        await connection_service.set_global_function_state_and_inherit(
            connection, function_name, data.state, capability_kind=data.capability_kind,
        )
    else:
        await connection_service.set_tool_function_state(connection.tool_id, function_name, data.state, capability_kind=data.capability_kind)
    resolved = await connection_service.resolve_function(connection, function_name, capability_kind=data.capability_kind)
    return FunctionStateResolved(**resolved)


class CapabilityStateUpdate(FunctionStateUpdate):
    function_name: str = Field(min_length=1, max_length=2000)
    global_policy: bool = False
    inherit_connection: bool = Field(default=False, description="Clear this connection's override when saving a global policy.")


@router.put("/{connection_id}/capabilities", response_model=FunctionStateResolved, dependencies=[Depends(require_web_session)])
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def set_capability_policy(connection_id: int, data: CapabilityStateUpdate):
    """Exact names and URIs travel in the body, independently of their capability kind."""
    if data.global_policy:
        result = await _set_global_function_policy(
            connection_id, data.function_name, data, inherit_connection=data.inherit_connection,
        )
        connection = await _managed_connection(connection_id)
        from .models import ConnectionFunctionState
        from sqlalchemy import func
        result.local_override_count = await get_db().scalar(select(func.count()).select_from(ConnectionFunctionState)
            .join(Connection).where(Connection.tool_id == connection.tool_id,
                ConnectionFunctionState.capability_kind == data.capability_kind,
                ConnectionFunctionState.function_name == data.function_name)) or 0
        return result
    return await set_connection_function(connection_id, data.function_name, data)
