"""Connection-owned administrative projections, dependencies and mutations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.tools.facade import AdministrationContext, AdministrationError
from core.database import Base, get_db

from . import connection_service as service
from .models import Connection, ConnectionParam, ConnectionFunctionState


async def list_connections(*, tool_id: int | None = None, agent_id: int | None = None,
                           active: bool | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    query = select(Connection)
    if tool_id is not None:
        query = query.where(Connection.tool_id == tool_id)
    if agent_id is not None:
        query = query.where(Connection.agent_id == agent_id)
    if active is not None:
        query = query.where(Connection.active == active)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    records = (await get_db().scalars(query.order_by(Connection.id).offset(offset).limit(limit))).all()
    return {"total": total, "offset": offset, "limit": limit, "items": [identity(record) for record in records]}


def identity(connection: Connection) -> dict[str, Any]:
    return {"id": connection.id, "tool_id": connection.tool_id, "agent_id": connection.agent_id, "active": connection.active}


async def snapshot(tool_id: int, *, connection_id: int | None = None) -> dict[str, Any]:
    query = select(Connection).where(Connection.tool_id == tool_id)
    if connection_id is not None:
        query = query.where(Connection.id == connection_id)
    records = (await get_db().scalars(query.order_by(Connection.id).execution_options(populate_existing=True))).all()
    ids = [record.id for record in records]
    params = (await get_db().scalars(select(ConnectionParam).where(ConnectionParam.connection_id.in_(ids))
                                  .order_by(ConnectionParam.connection_id, ConnectionParam.param_name)
                                  .execution_options(populate_existing=True))).all()
    local = (await get_db().scalars(select(ConnectionFunctionState).where(ConnectionFunctionState.connection_id.in_(ids))
                                 .order_by(ConnectionFunctionState.connection_id, ConnectionFunctionState.function_name)
                                 .execution_options(populate_existing=True))).all()
    global_states = await service.list_tool_function_states(tool_id)
    return {
        "connections": [identity(record) for record in records],
        "params": [(row.connection_id, row.param_name, row.param_value) for row in params],
        "local_states": [(row.connection_id, row.capability_kind, row.function_name, service.stored_function_state(row)) for row in local],
        "global_states": sorted((row.capability_kind, row.function_name, service.stored_function_state(row)) for row in global_states),
    }


async def references(connection_ids: list[int], *, tool_id: int | None = None) -> list[dict[str, Any]]:
    """Inventory technical FK references without importing foreign domain internals."""
    result: list[dict[str, Any]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if table.name in {"connections", "connection_params", "connection_function_state", "tool_function_state"}:
            continue
        for fk in table.foreign_keys:
            if fk.target_fullname == "connections.id":
                predicate = fk.parent.in_(connection_ids)
            elif tool_id is not None and fk.target_fullname == "tools.id":
                predicate = fk.parent == tool_id
            else:
                continue
            count = await get_db().scalar(select(func.count()).select_from(table).where(predicate))
            if count:
                result.append({"table": table.name, "field": fk.parent.name, "count": count, "on_delete": fk.ondelete})
    return result


async def projection(connection_id: int) -> dict[str, Any]:
    connection, local, configured = await service.get_params_for_api(connection_id)
    if connection is None:
        raise AdministrationError("not_found", "Connection not found.")
    from app.tools.facade import get_tool_by_id, get_runtime_global_params

    tool = await get_tool_by_id(connection.tool_id)
    if tool is None:
        raise AdministrationError("not_found", "Tool not found.")
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
    return {**identity(connection), "local_params": local, "configured_params": configured, "effective_params": effective}


async def require_target(actor: AdministrationContext, connection_id: int) -> Connection:
    connection = await service.get_connection(connection_id)
    if connection is None:
        raise AdministrationError("not_found", "Connection not found.")
    actor.require_agent(connection.agent_id)
    from app.tools.facade import get_tool_by_id

    tool = await get_tool_by_id(connection.tool_id)
    if tool is None:
        raise AdministrationError("not_found", "Tool not found.")
    actor.require_target(tool.code, can_disable=tool.can_disable,
                         executable=tool.mcp is not None and tool.mcp.type == "stdio")
    return connection


async def create(actor: AdministrationContext, tool_id: int, agent_id: int, *, active: bool = False) -> Connection:
    from app.agent import agent_service
    from app.tools.facade import get_tool_by_id, lock_tools

    await lock_tools([tool_id])
    await actor.require()
    actor.require_agent(agent_id)
    tool = await get_tool_by_id(tool_id)
    if tool is None or await agent_service.get(agent_id) is None:
        raise AdministrationError("not_found", "Tool or agent not found.")
    actor.require_target(tool.code, can_disable=tool.can_disable,
                         executable=tool.mcp is not None and tool.mcp.type == "stdio")
    if await service.get_connection_by_agent_tool(tool_id, agent_id) is not None:
        raise AdministrationError("conflict", "This agent/Tool connection already exists.")
    return await service.get_or_create_connection(tool_id, agent_id, active=active, commit=False)


async def lock_connection(connection_id: int) -> None:
    await get_db().execute(select(Connection).where(Connection.id == connection_id).with_for_update()
                           .execution_options(populate_existing=True))
