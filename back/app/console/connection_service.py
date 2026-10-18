"""Resolve immutable SSH console configuration from agent connections."""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.agent import Agent
from app.connection import Connection
from app.connection import connection_service
from app.tools import tool_service
from core.database import get_db
from core.i18n import render_prompt, tr

from .contracts import SshConnectionConfig


async def _message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"console.errors.{key}"), **values)


def _required(params: dict[str, Any], name: str) -> str:
    value = str(params.get(name) or "").strip()
    if not value:
        raise KeyError(name)
    return value


def _bounded_number(
    params: dict[str, Any],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    value = float(str(raw))
    if value < minimum or value > maximum:
        raise ValueError(f"{value:g}")
    return value


async def _config_from_connection(connection: Connection) -> SshConnectionConfig:
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is None or tool.code != "console":
        raise ValueError("Connection is not an SSH console connection")
    _, params = await connection_service.get_params_as_dict(
        connection,
        decrypt_passwords=True,
    )
    try:
        return SshConnectionConfig(
            connection_id=connection.id,
            host=_required(params, "host"),
            port=int(_bounded_number(params, "port", 22, 1, 65535)),
            username=_required(params, "username"),
            private_key=SecretStr(_required(params, "private_key")),
            private_key_passphrase=(
                SecretStr(str(params["private_key_passphrase"]))
                if params.get("private_key_passphrase")
                else None
            ),
            known_host_key=_required(params, "known_host_key"),
            code_runtime_port=(int(str(params["code_runtime_port"])) if params.get("code_runtime_port") else None),
            code_runtime_token=(SecretStr(str(params["code_runtime_token"])) if params.get("code_runtime_token") else None),
            connect_timeout_s=_bounded_number(
                params, "connect_timeout_s", 10, 1, 120
            ),
            command_timeout_s=_bounded_number(
                params, "command_timeout_s", 300, 1, 86400
            ),
        )
    except KeyError as exc:
        raise ValueError(
            await _message("required_parameter", parameter=exc.args[0])
        ) from exc
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(
            await _message("invalid_parameter", parameter="configuration", value=exc)
        ) from exc


async def resolve_connection(connection_id: int) -> SshConnectionConfig:
    connection = await connection_service.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"Connection {connection_id} not found")
    return await _config_from_connection(connection)


async def resolve_active_connection(connection_id: int) -> SshConnectionConfig:
    """IDE access requires an active target; provisioning may resolve inactive ones."""
    connection = await connection_service.get_connection(connection_id)
    if connection is None or not connection.active:
        raise ValueError("Console unavailable")
    return await _config_from_connection(connection)


async def resolve_ssh_connection(agent_id: int) -> SshConnectionConfig | None:
    """Return the active console connection, decrypted once for the current run."""
    tool = await tool_service.get_tool_record("console")
    if tool is None:
        return None
    connection = await get_db().scalar(
        select(Connection).where(
            Connection.agent_id == agent_id,
            Connection.tool_id == tool.id,
            Connection.active.is_(True),
        ).execution_options(populate_existing=True)
    )
    return await _config_from_connection(connection) if connection is not None else None


async def require_ssh_connection(agent_id: int) -> SshConnectionConfig:
    config = await resolve_ssh_connection(agent_id)
    if config is None:
        raise ValueError(await _message("connection_missing"))
    return config


async def is_embedded_executor_in_use() -> bool:
    """Return whether an agent using the internal harness has an embedded SSH console."""
    tool = await tool_service.get_tool_record("console")
    if tool is None:
        return False

    connections = await connection_service.get_connections_by_param(
        tool_id=tool.id,
        param_name="host",
        param_value="ssh-executor",
    )
    agent_ids = [connection.agent_id for connection in connections if connection.active]
    for offset in range(0, len(agent_ids), 500):
        if await get_db().scalar(
            select(Agent.id).where(
                Agent.id.in_(agent_ids[offset:offset + 500]),
                Agent.agent_driver == "internal",
            ).limit(1)
        ) is not None:
            return True
    return False
