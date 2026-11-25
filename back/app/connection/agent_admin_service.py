"""Connection workflows for the manager-scoped AgentAdmin delegation."""

from typing import Any
from loguru import logger

from core.database import get_db
from app.services.facade import HUMAN_ONLY_SERVICE_CODES
from . import connection_service as service
from .models import Connection
from .schemas import FunctionState


async def refresh_after_mutation(agent_id: int) -> None:
    from app.services import refresh_agent_tool_catalog
    try:
        await refresh_agent_tool_catalog(agent_id)
        await get_db().commit()
    except Exception:
        await get_db().rollback()
        logger.warning("Connection catalog refresh failed for agent {}", agent_id)


async def require_connection(connection_id: int, *, editable: bool = False) -> Connection:
    from app.services.facade import get_service_by_id
    connection = await service.get_connection(connection_id)
    if connection is None:
        raise LookupError("Connection not found")
    if editable:
        await service.require_editable_connection(connection_id)
        tool = await get_service_by_id(connection.service_id)
        if tool and tool.code in HUMAN_ONLY_SERVICE_CODES:
            raise PermissionError("Administrative delegation can only be changed by a human")
    return connection


async def projection(connection_id: int) -> dict[str, Any]:
    from .admin_service import projection as shared_projection
    result = await shared_projection(connection_id)
    result["resource_uri"] = f"galaris://agent/{result['agent_id']}"
    return result


async def create(agent_id: int, service_id: int, active: bool) -> dict[str, Any]:
    from app.services.facade import lock_services, get_service_by_id
    await lock_services([service_id])
    tool = await get_service_by_id(service_id)
    if tool is None:
        raise LookupError("Service not found")
    await service.require_editable_tool(service_id)
    if tool.code in HUMAN_ONLY_SERVICE_CODES:
        raise PermissionError("Only humans can grant administrative capabilities")
    connection = await service.create_connection(service_id, agent_id, active=active)
    await refresh_after_mutation(agent_id)
    return await projection(connection.id)


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
    return {"agent_id": agent_id, "deleted": True}


async def params_set(connection_id: int, params: dict[str, str | None]) -> dict[str, Any]:
    connection = await require_connection(connection_id, editable=True)
    if len(params) > 100 or any(v is not None and len(v) > 100_000 for v in params.values()):
        raise ValueError("Connection parameters exceed the supported limit")
    await service.validate_params(connection.service_id, params)
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
    from app.services import list_available_connection_functions, load_mcp_tools
    from app.services.facade import get_service_by_id
    tool = await get_service_by_id(connection.service_id)
    native = [d for d in load_mcp_tools() if tool and d.service_code == tool.code]
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


async def list_connections(agent_id: int, service_id: int | None, active_only: bool, skip: int, limit: int) -> dict[str, Any]:
    from .admin_service import list_connections as list_managed_connections
    page = await list_managed_connections(agent_id=agent_id, service_id=service_id,
        active=True if active_only else None, offset=skip, limit=limit)
    return {"items": page["items"], "skip": skip, "limit": limit}


async def service_identifier(service_code: str) -> int:
    from app.services import service
    record = await service.get_service_record(service_code)
    if record is None:
        raise LookupError("Service not found")
    return record.id


async def list_tools(search: str, skip: int, limit: int) -> dict[str, Any]:
    from app.services import service
    from app.services.facade import get_services_by_ids, public_connection_schema
    records = [t for t in await service.get_all_service_records(summary_only=True)
               if not search or search.casefold() in f"{t.code} {t.label}".casefold()]
    selected = records[skip:skip + limit]
    current = set(await get_services_by_ids({record.id for record in selected}))
    values: list[dict[str, Any]] = []
    for record in selected:
        if record.id in current:
            values.append({"agent_id": None, "id": record.id, "code": record.code, "label": record.label,
                           "mandatory": not record.can_disable,
                           "human_only": record.code in HUMAN_ONLY_SERVICE_CODES,
                           "connection_schema": public_connection_schema(record.connection_schema or {})})
    return {"items": values, "total": len(records), "skip": skip, "limit": limit}
