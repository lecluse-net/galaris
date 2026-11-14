"""Connection-owned administrative projections, dependencies and mutations."""

from __future__ import annotations

from typing import Any
from collections.abc import Collection

from sqlalchemy import func, select, update

from app.services.facade import AdministrationContext, AdministrationError
from core.database import Base, get_db

from . import connection_service as service
from .models import Connection, ConnectionParam, ConnectionFunctionState


async def list_connections(*, service_id: int | None = None, agent_id: int | None = None,
                           active: bool | None = None, offset: int = 0, limit: int = 50,
                           agent_ids: Collection[int] | None = None) -> dict[str, Any]:
    query = select(Connection)
    if agent_ids is not None:
        query = query.where(Connection.agent_id.in_(agent_ids))
    if service_id is not None:
        query = query.where(Connection.service_id == service_id)
    if agent_id is not None:
        query = query.where(Connection.agent_id == agent_id)
    if active is not None:
        query = query.where(Connection.active == active)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    records = (await get_db().scalars(query.order_by(Connection.id).offset(offset).limit(limit))).all()
    return {"total": total, "offset": offset, "limit": limit, "items": [identity(record) for record in records]}


def identity(connection: Connection) -> dict[str, Any]:
    return {"id": connection.id, "service_id": connection.service_id, "agent_id": connection.agent_id, "active": connection.active}


async def snapshot(service_id: int, *, connection_id: int | None = None) -> dict[str, Any]:
    query = select(Connection).where(Connection.service_id == service_id)
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
    global_states = await service.list_service_function_states(service_id)
    return {
        "connections": [identity(record) for record in records],
        "params": [(row.connection_id, row.param_name, row.param_value) for row in params],
        "local_states": [(row.connection_id, row.capability_kind, row.function_name, service.stored_function_state(row)) for row in local],
        "global_states": sorted((row.capability_kind, row.function_name, service.stored_function_state(row)) for row in global_states),
    }


async def references(connection_ids: list[int], *, service_id: int | None = None) -> list[dict[str, Any]]:
    """Inventory technical FK references without importing foreign domain internals."""
    result: list[dict[str, Any]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if table.name in {"connections", "connection_params", "connection_function_state", "service_function_state"}:
            continue
        for fk in table.foreign_keys:
            if fk.target_fullname == "connections.id":
                predicate = fk.parent.in_(connection_ids)
            elif service_id is not None and fk.target_fullname == "services.id":
                predicate = fk.parent == service_id
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
    from app.services.facade import get_service_by_id, get_runtime_global_params

    tool = await get_service_by_id(connection.service_id)
    if tool is None:
        raise AdministrationError("not_found", "Service not found.")
    global_values, forced = await get_runtime_global_params(connection.service_id, decrypt_passwords=False)
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
    from app.services.facade import get_service_by_id

    tool = await get_service_by_id(connection.service_id)
    if tool is None:
        raise AdministrationError("not_found", "Service not found.")
    actor.require_target(tool.code, can_disable=tool.can_disable,
                         executable=tool.mcp is not None and tool.mcp.type == "stdio")
    return connection


async def create(actor: AdministrationContext, service_id: int, agent_id: int, *, active: bool = False) -> Connection:
    from app.agent import agent_service
    from app.services.facade import get_service_by_id, lock_services

    await lock_services([service_id])
    await actor.require()
    actor.require_agent(agent_id)
    tool = await get_service_by_id(service_id)
    if tool is None or await agent_service.get(agent_id) is None:
        raise AdministrationError("not_found", "Service or agent not found.")
    actor.require_target(tool.code, can_disable=tool.can_disable,
                         executable=tool.mcp is not None and tool.mcp.type == "stdio")
    if tool.mail is None and await service.get_connection_by_agent_service(service_id, agent_id) is not None:
        raise AdministrationError("conflict", "This agent/Service connection already exists.")
    return await service.create_connection(service_id, agent_id, active=active, commit=False)


async def require_singleton_connections(service_id: int) -> None:
    """Do not strand multiple accounts when the Mail protocol is removed."""
    duplicate = await get_db().scalar(select(Connection.agent_id).where(Connection.service_id == service_id)
        .group_by(Connection.agent_id).having(func.count() > 1).limit(1))
    if duplicate is not None:
        raise ValueError("Remove the additional Mail connections before removing the Mail protocol")
    await get_db().execute(update(Connection).where(Connection.service_id == service_id).values(singleton_key=0))


async def lock_connection(connection_id: int) -> None:
    await get_db().execute(select(Connection).where(Connection.id == connection_id).with_for_update()
                           .execution_options(populate_existing=True))
