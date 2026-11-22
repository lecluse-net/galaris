"""Service-level inventory of tools that can be enabled for conversation."""

import asyncio
from typing import Any, cast

import httpx2 as httpx
from loguru import logger
from pydantic_ai.mcp import MCPToolset

from core.authorize import check_privilege
from core.database import get_db, release_db_transaction
from core.user import get_current_user

from . import service
from .admin_network import diagnostic_client
from .assertions import service_can_edit
from .mcp import build_mcp_server
from .mcp_diagnostics import list_mcp_tools_bounded
from .mcp_loader import conversation_tool_names, mcp_tools_by_service_code, native_service_codes_for_service
from .schemas import ConversationToolCatalog, ConversationToolEntry, Service
from .secrets import resolve_connection_references


_CONNECTION_PAGE_SIZE = 4
_DISCOVERY_SLOTS = asyncio.Semaphore(4)


async def _discover_mcp_tools(service_id: int, tool: Service, params: dict[str, Any]) -> tuple[set[str], bool]:
    config = tool.mcp
    assert config is not None and config.type in {"http", "sse"}

    secrets = {
        str(value) for name, value in params.items()
        if value and name in tool.connection.params and tool.connection.params[name].type == "password"
    }
    if config.auth.token_static:
        secrets.add(config.auth.token_static)
    for name in (config.auth.param, config.auth.password_param if config.auth.type == "basic" else None):
        if name and (value := params.get(name)):
            secrets.add(str(value))
    secret_headers = {"authorization", "cookie", *(name.lower() for name in config.headers)}
    if config.auth.type == "header":
        secret_headers.add(config.auth.header_name.lower())

    async def remember_credentials(request: httpx.Request) -> None:
        # The callback sees the headers after OAuth has added its access token.
        for name in secret_headers:
            if value := request.headers.get(name):
                secrets.add(value)
                if name == "authorization" and " " in value:
                    secrets.add(value.split(" ", 1)[1])

    try:
        url = resolve_connection_references(config.url or "", params)
        async with asyncio.timeout(25), _DISCOVERY_SLOTS:
            async with await diagnostic_client(url, allow_private=True) as client:
                client.event_hooks["request"].append(remember_credentials)
                # Keep the effective parameter mapping so the builder can resolve OAuth.
                server = build_mcp_server(tool, params, prefix_tools=False, http_client=client)
                assert isinstance(server, MCPToolset)
                async with server:
                    entries, truncated = await list_mcp_tools_bounded(cast(MCPToolset[Any], server))
        names = {
            entry.name for entry in entries
            if 0 < len(entry.name.encode("utf-8")) <= 255 and "\x00" not in entry.name
            and not any(secret and secret in entry.name for secret in secrets)
        }
        return names, truncated or any(entry.name not in names for entry in entries)
    except Exception as exc:
        logger.warning("Conversation tool discovery failed for service {} ({})", service_id, type(exc).__name__)
        return set(), True


async def _discover_external(
    service_id: int, tool: Service, *, after_connection_id: int | None,
) -> tuple[set[str], bool, int | None]:
    from app.agent import current_management_scope
    from app.connection.facade import CONNECTION_FUNCTION_READ_PRIVILEGES, get_params_as_dict, list_management_connections

    if tool.mcp is None or tool.mcp.type == "stdio":
        return set(), True, None

    sources: list[dict[str, Any]] = []
    next_connection_id = None
    if await check_privilege(await get_current_user(), CONNECTION_FUNCTION_READ_PRIVILEGES, get_db()):
        scope = await current_management_scope()
        connections = await list_management_connections(
            agent_ids=scope.agent_ids, service_id=service_id, active_only=True,
            after_id=after_connection_id, limit=_CONNECTION_PAGE_SIZE + 1,
        )
        page = connections[:_CONNECTION_PAGE_SIZE]
        if len(connections) > len(page):
            next_connection_id = page[-1].id
        for item in page:
            connection, params = await get_params_as_dict(item.id)
            if connection and connection.active and connection.service_id == service_id and scope.allows(connection.agent_id):
                sources.append(params)

    shared = after_connection_id is None
    if shared:
        params, _ = await service.get_runtime_global_params(service_id)
        sources.insert(0, params)
    await release_db_transaction()
    results: list[tuple[set[str], bool]] = await asyncio.gather(
        *(_discover_mcp_tools(service_id, tool, params) for params in sources),
    )
    discovered = {name for names, _ in results for name in names}
    # A private server may reject a shared probe while every applicable connection succeeds.
    if shared and len(results) > 1 and not results[0][0]:
        results = results[1:]
    return discovered, any(incomplete for _, incomplete in results), next_connection_id


async def read_conversation_tools(
    service_id: int, *, discover: bool = False, after_connection_id: int | None = None,
) -> ConversationToolCatalog | None:
    tool = await service.get_service_by_id(service_id)
    if tool is None:
        return None

    discovered: set[str] = set()
    incomplete = False
    next_connection_id = None
    if discover and tool.mcp and tool.can_disable and service_can_edit(tool.code):
        discovered, incomplete, next_connection_id = await _discover_external(
            service_id, tool, after_connection_id=after_connection_id,
        )
        # Remote discovery can outlast another administrator's save.
        current = await service.get_service_by_id(service_id)
        if current is None:
            return None
        if current.mcp != tool.mcp or current.connection != tool.connection or not current.can_disable:
            discovered.clear()
            incomplete = True
            next_connection_id = None
        tool = current
    native_enabled = set(conversation_tool_names(tool, source="native"))
    external_enabled = set(conversation_tool_names(tool, source="external"))
    definitions = mcp_tools_by_service_code()
    native_definitions = [
        definition
        for code in native_service_codes_for_service(tool)
        for definition in definitions.get(code, ())
    ]
    eligible_names = {definition.name for definition in native_definitions if definition.conversation_policy != "forbidden"}
    if tool.can_disable and service_can_edit(tool.code):
        native_names = eligible_names | native_enabled
    else:
        native_names = {definition.name for definition in native_definitions}
        native_enabled &= eligible_names
    return ConversationToolCatalog(
        tools=[
            *(ConversationToolEntry(name=name, source="native", enabled=name in native_enabled) for name in sorted(native_names)),
            *(ConversationToolEntry(name=name, source="external", enabled=name in external_enabled)
              for name in sorted(external_enabled | discovered)),
        ],
        discovery_incomplete=incomplete,
        next_connection_id=next_connection_id,
    )
