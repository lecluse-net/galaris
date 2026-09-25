"""Connection and EAV parameter service."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Dict, Optional, List, Tuple, cast
from sqlalchemy import CursorResult, delete, exists, or_, select
from sqlalchemy.orm import joinedload

from .models import Connection, ConnectionParam, ConnectionFunctionState, ToolFunctionState
from .schemas import FunctionState
from core.util import get_encryption_service
from core.database import get_db
from core.i18n import render_prompt, tr


_encryption = get_encryption_service()

if TYPE_CHECKING:
    from app.tools import Tool


async def _get_tool_schema(tool_id: int) -> Optional[Dict[str, Any]]:
    """Return a tool's connection schema from the database."""
    from app.tools import facade as tool_service
    tool = await tool_service.get_tool_by_id(tool_id)
    if not tool or not tool.connection:
        return None
    return {
        "properties": {
            name: {"type": param.type}
            for name, param in tool.connection.params.items()
        }
    }


def _is_password_field(param_name: str, tool_schema: Optional[Dict[str, Any]]) -> bool:
    if not tool_schema:
        return False
    return tool_schema.get("properties", {}).get(param_name, {}).get("type") == "password"


def _encrypt_if_needed(
    param_name: str,
    param_value: Optional[str],
    tool_schema: Optional[Dict[str, Any]]
) -> Optional[str]:
    if not param_value or not _is_password_field(param_name, tool_schema):
        return param_value
    if _encryption.is_encrypted(param_value):
        return param_value
    return _encryption.encrypt(param_value)


def _decrypt_if_needed(
    param_name: str,
    param_value: Optional[str],
    tool_schema: Optional[Dict[str, Any]]
) -> Optional[str]:
    if not param_value or not _is_password_field(param_name, tool_schema):
        return param_value
    if not _encryption.is_encrypted(param_value):
        return param_value
    return _encryption.decrypt(param_value)


# ==========================================================================
# Parent connection records.
# ==========================================================================

async def tool_can_disable(tool_id: int) -> bool:
    from app.tools import facade as tool_service

    tool = await tool_service.get_tool_by_id(tool_id)
    return tool is None or tool.can_disable


async def require_editable_tool(tool_id: int) -> None:
    if not await tool_can_disable(tool_id):
        raise ValueError(await tr("tools.errors.system_read_only"))


async def require_editable_connection(connection_id: int) -> None:
    connection = await get_connection(connection_id)
    if connection is not None:
        await require_editable_tool(connection.tool_id)

async def get_or_create_connection(tool_id: int, agent_id: int) -> Connection:
    db = get_db()
    result = await db.execute(
        select(Connection).where(
            Connection.tool_id == tool_id,
            Connection.agent_id == agent_id
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        return connection
    new_connection = Connection(tool_id=tool_id, agent_id=agent_id, active=True)
    db.add(new_connection)
    await db.commit()
    await db.refresh(new_connection)
    return new_connection


async def get_connection(connection_id: int) -> Optional[Connection]:
    db = get_db()
    result = await db.execute(
        select(Connection).where(Connection.id == connection_id)
    )
    return result.scalar_one_or_none()


async def get_connection_by_agent_tool(
    tool_id: int,
    agent_id: int
) -> Optional[Connection]:
    db = get_db()
    result = await db.execute(
        select(Connection).where(
            Connection.tool_id == tool_id,
            Connection.agent_id == agent_id
        )
    )
    return result.scalar_one_or_none()


async def has_active_tool_connection(
    agent_id: int,
    tool_code: str,
    *,
    connection_id: int | None = None,
) -> bool:
    """Return whether an agent has an active connection to a tool.

    ``connection_id`` lets listeners revalidate the exact connection that started them. Deleted,
    reassigned, or disabled connections immediately become unavailable.
    """
    from app.tools import ToolModel

    db = get_db()
    query = (
        select(Connection.id)
        .join(ToolModel, ToolModel.id == Connection.tool_id)
        .where(
            Connection.agent_id == agent_id,
            Connection.active.is_(True),
            ToolModel.code == tool_code,
        )
        .limit(1)
    )
    if connection_id is not None:
        query = query.where(Connection.id == connection_id)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def has_active_tool_function(agent_id: int, tool_code: str, function_name: str) -> bool:
    """Check the live connection and its effective function authorization."""
    from app.tools import ToolModel

    connections = (await get_db().scalars(select(Connection).join(ToolModel).where(
        Connection.agent_id == agent_id, Connection.active.is_(True), ToolModel.code == tool_code,
    ))).all()
    for connection in connections:
        if function_name not in await get_disabled_function_names(connection):
            return True
    return False


async def has_any_active_tool_connection(
    tool_code: str,
    *,
    agent_ids: Collection[int] | None = None,
) -> bool:
    """Return whether at least one agent has an active connection to a tool."""
    from app.tools import ToolModel

    query = (
        select(Connection.id)
        .join(ToolModel, ToolModel.id == Connection.tool_id)
        .where(
            Connection.active.is_(True),
            ToolModel.code == tool_code,
        )
        .limit(1)
    )
    if agent_ids is not None:
        query = query.where(Connection.agent_id.in_(agent_ids))
    result = await get_db().execute(query)
    return result.scalar_one_or_none() is not None


async def set_connection_active(connection_id: int, active: bool) -> Optional[Connection]:
    await require_editable_connection(connection_id)
    db = get_db()
    connection = await get_connection(connection_id)
    if not connection:
        return None
    connection.active = active
    await db.commit()
    await db.refresh(connection)
    return connection


async def delete_connection(connection_id: int) -> bool:
    await require_editable_connection(connection_id)
    db = get_db()
    connection = await get_connection(connection_id)
    if not connection:
        return False
    await db.delete(connection)
    await db.commit()
    return True


# ==========================================================================
# EAV parameters.
# ==========================================================================

async def _get_local_params_as_dict(
    connection: "int | Connection",
    decrypt_passwords: bool = True
) -> Tuple[Optional[Connection], Dict[str, Any]]:
    if isinstance(connection, int):
        connection_obj = await get_connection(connection)
        if not connection_obj:
            return None, {}
    else:
        connection_obj = connection

    # Never access ``connection_obj.params`` here: the relationship is lazy by
    # default and implicit I/O raises MissingGreenlet under SQLAlchemy async.
    db = get_db()
    result = await db.execute(
        select(ConnectionParam).where(ConnectionParam.connection_id == connection_obj.id)
    )
    params = result.scalars().all()

    tool_schema = await _get_tool_schema(connection_obj.tool_id) if decrypt_passwords else None

    result_dict: Dict[str, Any] = {}
    for param in params:
        value = param.param_value
        if decrypt_passwords and value:
            value = _decrypt_if_needed(param.param_name, value, tool_schema)
        result_dict[param.param_name] = value

    return connection_obj, result_dict


async def merge_with_global_params(
    tool_id: int,
    local_params: Dict[str, Any],
    *,
    decrypt_passwords: bool = True,
) -> Dict[str, Any]:
    """Apply the common Tool inheritance rule to an arbitrary local parameter mapping."""

    from app.tools import facade as tool_service

    global_params, forced = await tool_service.get_runtime_global_params(
        tool_id,
        decrypt_passwords=decrypt_passwords,
    )
    resolved = dict(global_params)
    for name, value in local_params.items():
        if name in forced or value in (None, ""):
            continue
        resolved[name] = value
    return resolved


async def get_params_as_dict(
    connection: "int | Connection",
    decrypt_passwords: bool = True,
) -> Tuple[Optional[Connection], Dict[str, Any]]:
    """Return effective parameters: local override, then global Tool value."""

    connection_obj, local_params = await _get_local_params_as_dict(
        connection,
        decrypt_passwords=decrypt_passwords,
    )
    if connection_obj is None:
        return None, {}
    return connection_obj, await merge_with_global_params(
        connection_obj.tool_id,
        local_params,
        decrypt_passwords=decrypt_passwords,
    )


async def get_params_for_api(
    connection: "int | Connection",
) -> Tuple[Optional[Connection], Dict[str, Any], List[str]]:
    """Return connection parameters without ever exposing password values."""
    connection_obj, params = await _get_local_params_as_dict(
        connection,
        decrypt_passwords=False,
    )
    if connection_obj is None:
        return None, {}, []
    tool_schema = await _get_tool_schema(connection_obj.tool_id)
    configured: List[str] = []
    safe: Dict[str, Any] = {}
    for name, value in params.items():
        if _is_password_field(name, tool_schema):
            safe[name] = None
            if value:
                configured.append(name)
        else:
            safe[name] = value
    return connection_obj, safe, sorted(configured)


async def redact_param(param: ConnectionParam) -> ConnectionParam:
    """Clear a password value before serializing an EAV row to the API."""
    connection = await get_connection(param.connection_id)
    if connection is None:
        return param
    tool_schema = await _get_tool_schema(connection.tool_id)
    if not _is_password_field(param.param_name, tool_schema):
        return param
    return ConnectionParam(
        id=param.id,
        connection_id=param.connection_id,
        param_name=param.param_name,
        param_value=None,
    )


async def find_agents_by_param(
    tool_id: int,
    param_name: str,
    param_value: str
) -> List[int]:
    connections = await get_connections_by_param(
        tool_id=tool_id,
        param_name=param_name,
        param_value=param_value,
    )
    return [connection.agent_id for connection in connections]


async def get_connections_by_param(
    tool_id: int,
    param_name: str,
    param_value: str
) -> List[Connection]:
    """Find connections whose effective value matches, including inherited globals."""

    from app.tools import facade as tool_service

    global_params, forced = await tool_service.get_runtime_global_params(tool_id)
    global_matches = global_params.get(param_name) == param_value
    if param_name in forced:
        if not global_matches:
            return []
        predicate = Connection.tool_id == tool_id
    else:
        local_match = exists(
            select(ConnectionParam.id).where(
                ConnectionParam.connection_id == Connection.id,
                ConnectionParam.param_name == param_name,
                ConnectionParam.param_value == param_value,
            )
        )
        if global_matches:
            local_override = exists(
                select(ConnectionParam.id).where(
                    ConnectionParam.connection_id == Connection.id,
                    ConnectionParam.param_name == param_name,
                    ConnectionParam.param_value.is_not(None),
                    ConnectionParam.param_value != "",
                )
            )
            value_matches = or_(local_match, ~local_override)
        else:
            value_matches = local_match
        predicate = (Connection.tool_id == tool_id) & value_matches

    db = get_db()
    result = await db.execute(
        select(Connection).where(predicate)
    )
    return list(result.scalars().all())


async def set_param(
    connection_id: int,
    param_name: str,
    param_value: Optional[str]
) -> ConnectionParam:
    await require_editable_connection(connection_id)
    db = get_db()
    connection = await get_connection(connection_id)
    if not connection:
        raise ValueError(
            render_prompt(
                await tr("connection_api.errors.not_found_by_id"),
                connection_id=connection_id,
            )
        )

    from app.tools import facade as tool_service

    _, forced = await tool_service.get_runtime_global_params(
        connection.tool_id,
        decrypt_passwords=False,
    )
    if param_name in forced and param_value not in (None, ""):
        raise ValueError(f"Connection parameter {param_name} is imposed globally")

    tool_schema = await _get_tool_schema(connection.tool_id)
    encrypted_value = _encrypt_if_needed(param_name, param_value, tool_schema)

    result = await db.execute(
        select(ConnectionParam).where(
            ConnectionParam.connection_id == connection_id,
            ConnectionParam.param_name == param_name
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.param_value = encrypted_value
        await db.commit()
        await db.refresh(existing)
        return existing

    new_param = ConnectionParam(
        connection_id=connection_id,
        param_name=param_name,
        param_value=encrypted_value
    )
    db.add(new_param)
    await db.commit()
    await db.refresh(new_param)
    return new_param


async def set_params_bulk(
    connection_id: int,
    params: Dict[str, Optional[str]]
) -> List[ConnectionParam]:
    await require_editable_connection(connection_id)
    return [await set_param(connection_id, k, v) for k, v in params.items()]


async def delete_param(connection_id: int, param_name: str) -> bool:
    await require_editable_connection(connection_id)
    db = get_db()
    result = await db.execute(
        delete(ConnectionParam).where(
            ConnectionParam.connection_id == connection_id,
            ConnectionParam.param_name == param_name
        )
    )
    await db.commit()
    return cast(CursorResult[Any], result).rowcount > 0


async def delete_all_params(connection_id: int) -> int:
    await require_editable_connection(connection_id)
    db = get_db()
    result = await db.execute(
        delete(ConnectionParam).where(ConnectionParam.connection_id == connection_id)
    )
    await db.commit()
    return cast(CursorResult[Any], result).rowcount


async def get_param(
    connection_id: int,
    param_name: str,
    decrypt: bool = True
) -> Optional[str]:
    _, params = await get_params_as_dict(
        connection_id,
        decrypt_passwords=decrypt,
    )
    value = params.get(param_name)
    return str(value) if value not in (None, "") else None


async def get_tools_by_agent(agent_id: int) -> List[Tool]:
    from app.tools import facade as tool_service
    db = get_db()
    result = await db.execute(
        select(Connection).where(
            Connection.agent_id == agent_id,
            Connection.active == True
        )
    )
    connections = result.scalars().all()
    tools: List[Tool] = []
    for connection in connections:
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool:
            tools.append(tool)
    return tools


async def get_connections_by_agent(agent_id: int) -> List[Connection]:
    db = get_db()
    result = await db.execute(
        select(Connection)
        .options(joinedload(Connection.params, innerjoin=False))
        .where(
            Connection.agent_id == agent_id,
            Connection.active == True
        )
    )
    return list(result.unique().scalars().all())


async def get_agent_ids_by_tool(tool_id: int) -> List[int]:
    """Return agents whose catalog can be affected by a tool-level change."""

    result = await get_db().execute(
        select(Connection.agent_id)
        .where(Connection.tool_id == tool_id)
        .distinct()
        .order_by(Connection.agent_id)
    )
    return [int(agent_id) for agent_id in result.scalars().all()]


# ==========================================================================
# MCP function exposure cascade: connection overrides tool.
# ==========================================================================
# Row-presence cascade, enabled by default:
# 1. a connection row wins;
# 2. otherwise a tool row wins;
# 3. otherwise the function is enabled.
# The runtime consumes the resulting denylist.


def function_state_label(enabled: Optional[bool]) -> FunctionState:
    """Convert an optional stored boolean to a three-state label."""
    if enabled is None:
        return "default"
    return "enabled" if enabled else "disabled"


def resolve_function_enabled(
    function_name: str,
    conn_states: Dict[str, bool],
    tool_states: Dict[str, bool],
) -> bool:
    """Resolve a function through the enabled-by-default cascade."""
    if function_name in conn_states:
        return conn_states[function_name]
    if function_name in tool_states:
        return tool_states[function_name]
    return True


async def list_function_states(connection_id: int) -> List[ConnectionFunctionState]:
    """Return connection-level state rows."""
    db = get_db()
    result = await db.execute(
        select(ConnectionFunctionState).where(
            ConnectionFunctionState.connection_id == connection_id
        )
    )
    return list(result.scalars().all())


async def list_tool_function_states(tool_id: int) -> List[ToolFunctionState]:
    """Return global tool-level state rows."""
    db = get_db()
    result = await db.execute(
        select(ToolFunctionState).where(ToolFunctionState.tool_id == tool_id)
    )
    return list(result.scalars().all())


async def get_disabled_function_names(connection: Connection) -> set[str]:
    """Return function names disabled for a connection after cascade resolution."""
    if not await tool_can_disable(connection.tool_id):
        return set()
    conn_states = {s.function_name: s.enabled for s in await list_function_states(connection.id)}
    tool_states = {s.function_name: s.enabled for s in await list_tool_function_states(connection.tool_id)}
    return {
        name
        for name in (set(conn_states) | set(tool_states))
        if not resolve_function_enabled(name, conn_states, tool_states)
    }


async def set_connection_function_state(
    connection_id: int,
    function_name: str,
    state: FunctionState,
) -> None:
    """Apply a connection-level state; ``default`` deletes the override row."""
    await require_editable_connection(connection_id)
    db = get_db()
    result = await db.execute(
        select(ConnectionFunctionState).where(
            ConnectionFunctionState.connection_id == connection_id,
            ConnectionFunctionState.function_name == function_name,
        )
    )
    row = result.scalar_one_or_none()

    if state == "default":
        if row:
            await db.delete(row)
            await db.commit()
        return

    enabled = state == "enabled"
    if row:
        row.enabled = enabled
    else:
        db.add(ConnectionFunctionState(
            connection_id=connection_id,
            function_name=function_name,
            enabled=enabled,
        ))
    await db.commit()


async def set_tool_function_state(
    tool_id: int,
    function_name: str,
    state: FunctionState,
) -> None:
    """Apply a tool-level state; ``default`` deletes the override row."""
    await require_editable_tool(tool_id)
    db = get_db()
    result = await db.execute(
        select(ToolFunctionState).where(
            ToolFunctionState.tool_id == tool_id,
            ToolFunctionState.function_name == function_name,
        )
    )
    row = result.scalar_one_or_none()

    if state == "default":
        if row:
            await db.delete(row)
            await db.commit()
        return

    enabled = state == "enabled"
    if row:
        row.enabled = enabled
    else:
        db.add(ToolFunctionState(
            tool_id=tool_id,
            function_name=function_name,
            enabled=enabled,
        ))
    await db.commit()


async def resolve_function(connection: Connection, function_name: str) -> Dict[str, Any]:
    """Resolve connection, tool, and effective state without querying MCP."""
    if not await tool_can_disable(connection.tool_id):
        return {"name": function_name, "connection_state": "enabled",
                "global_state": "enabled", "effective": True}
    conn_states = {s.function_name: s.enabled for s in await list_function_states(connection.id)}
    tool_states = {s.function_name: s.enabled for s in await list_tool_function_states(connection.tool_id)}
    return {
        "name": function_name,
        "connection_state": function_state_label(conn_states.get(function_name)),
        "global_state": function_state_label(tool_states.get(function_name)),
        "effective": resolve_function_enabled(function_name, conn_states, tool_states),
    }
