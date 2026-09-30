"""Connection workflows for the manager-scoped AgentAdmin delegation."""

from typing import Any
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from loguru import logger

from core.database import get_db
from app.tools.facade import HUMAN_ONLY_TOOL_CODES
from . import connection_service as service
from .models import Connection
from .schemas import Connection as ConnectionRead, FunctionState


async def refresh_after_mutation(agent_id: int) -> None:
    from app.tools import refresh_agent_tool_catalog
    try:
        await refresh_agent_tool_catalog(agent_id)
        await get_db().commit()
    except Exception:
        await get_db().rollback()
        logger.warning("Connection catalog refresh failed for agent {}", agent_id)


async def require_connection(connection_id: int, *, editable: bool = False) -> Connection:
    from app.tools.facade import get_tool_by_id
    connection = await service.get_connection(connection_id)
    if connection is None:
        raise LookupError("Connection not found")
    if editable:
        await service.require_editable_connection(connection_id)
        tool = await get_tool_by_id(connection.tool_id)
        if tool and tool.code in HUMAN_ONLY_TOOL_CODES:
            raise PermissionError("Administrative delegation can only be changed by a human")
    return connection


async def projection(connection_id: int) -> dict[str, Any]:
    connection, local, configured = await service.get_params_for_api(connection_id)
    if connection is None:
        raise LookupError("Connection not found")
    from app.tools.facade import get_tool_by_id, get_runtime_global_params

    tool = await get_tool_by_id(connection.tool_id)
    if tool is None:
        raise LookupError("Tool not found")
    global_values, forced = await get_runtime_global_params(connection.tool_id, decrypt_passwords=False)
    executable = tool.mcp is not None and tool.mcp.type == "stdio"
    effective: dict[str, Any] = {}
    for name, definition in tool.connection.params.items():
        local_set = name in configured or local.get(name) not in (None, "")
        inherited = name in forced or not local_set
        value = global_values.get(name, definition.default or None) if inherited else local.get(name)
        secret = definition.type == "password"
        effective[name] = {
            "value": None if secret or executable else value, "secret": secret,
            "configured": value not in (None, "") or (not inherited and name in configured),
            "origin": "global" if inherited and name in global_values else "default" if inherited else "local",
            "forced": name in forced,
        }
    if executable:
        local = {name: None for name in local}
    return {"id": connection.id, "tool_id": connection.tool_id, "agent_id": connection.agent_id, "active": connection.active, "resource_uri": f"galaris://agent/{connection.agent_id}", "local_params": local, "configured_params": configured, "effective_params": effective}


async def create(agent_id: int, tool_id: int, active: bool) -> dict[str, Any]:
    from app.tools.facade import lock_tools, get_tool_by_id
    await lock_tools([tool_id])
    tool = await get_tool_by_id(tool_id)
    if tool is None:
        raise LookupError("Tool not found")
    await service.require_editable_tool(tool_id)
    if tool.code in HUMAN_ONLY_TOOL_CODES:
        raise PermissionError("Only humans can grant administrative capabilities")
    identifier = await get_db().scalar(insert(Connection).values(agent_id=agent_id, tool_id=tool_id, active=active)
                                      .on_conflict_do_nothing().returning(Connection.id))
    if identifier is None:
        raise ValueError("A connection already exists for this agent and Tool")
    await get_db().commit()
    await refresh_after_mutation(agent_id)
    return await projection(identifier)


async def set_active(connection_id: int, active: bool) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    await service.set_connection_active(connection_id, active)
    await refresh_after_mutation(connection.agent_id)
    return await projection(connection_id)


async def delete(connection_id: int) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    agent_id = connection.agent_id
    await service.delete_connection(connection_id)
    await refresh_after_mutation(agent_id)
    return {"connection_id": connection_id, "agent_id": agent_id, "deleted": True}


async def params_set(connection_id: int, params: dict[str, str | None]) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    if len(params) > 100 or any(v is not None and len(v) > 100_000 for v in params.values()):
        raise ValueError("Connection parameters exceed the supported limit")
    await service.validate_params(connection.tool_id, params)
    await service.set_params_bulk(connection_id, params)
    await refresh_after_mutation(connection.agent_id)
    return await projection(connection_id)


async def param_delete(connection_id: int, name: str) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    await service.delete_param(connection_id, name)
    await refresh_after_mutation(connection.agent_id)
    return await projection(connection_id)


async def functions(connection_id: int) -> dict[str, Any]:
    connection = await require_connection(connection_id)
    from app.tools import list_available_connection_functions, load_mcp_tools
    from app.tools.facade import get_tool_by_id
    tool = await get_tool_by_id(connection.tool_id)
    native = [d for d in load_mcp_tools() if tool and d.tool_code == tool.code]
    if native:
        rows: list[dict[str, Any]] = []
        for definition in native:
            resolved = await service.resolve_function(connection, definition.name)
            resolved["description"] = definition.description
            resolved["effective"] = connection.active and resolved["effective"]
            rows.append(resolved)
        return {"success": True, "functions": rows}
    return await list_available_connection_functions(connection_id, include_inactive=True)


async def function_set(connection_id: int, name: str, state: FunctionState) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    catalog = await functions(connection_id)
    if not any(f["name"] == name for f in catalog["functions"]):
        raise ValueError("Unknown connection function")
    await service.set_connection_function_state(connection_id, name, state)
    result = await service.resolve_function(connection, name)
    await refresh_after_mutation(connection.agent_id)
    return result


async def list_connections(agent_id: int, tool_id: int | None, active_only: bool, skip: int, limit: int) -> dict[str, Any]:
    query = select(Connection).where(Connection.agent_id == agent_id).order_by(Connection.id)
    if tool_id is not None:
        query = query.where(Connection.tool_id == tool_id)
    if active_only:
        query = query.where(Connection.active.is_(True))
    connections = (await get_db().scalars(query.offset(skip).limit(limit))).all()
    return {"items": [ConnectionRead.model_validate(c).model_dump() for c in connections], "skip": skip, "limit": limit}


async def list_tools(search: str, skip: int, limit: int) -> dict[str, Any]:
    from app.tools import tool_service
    from app.tools.facade import public_connection_schema
    records = [t for t in await tool_service.get_all_tool_records()
               if not search or search.casefold() in f"{t.code} {t.label}".casefold()]
    values: list[dict[str, Any]] = []
    for record in records[skip:skip + limit]:
        tool = await tool_service.get_tool_by_id(record.id)
        if tool is not None:
            values.append({"id": record.id, "code": record.code, "label": record.label,
                           "mandatory": not record.can_disable,
                           "human_only": record.code in HUMAN_ONLY_TOOL_CODES,
                           "connection_schema": public_connection_schema(record.connection_schema or {})})
    return {"items": values, "total": len(records), "skip": skip, "limit": limit}
