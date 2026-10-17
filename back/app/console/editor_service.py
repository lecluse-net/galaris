"""Explicit editor deployment from a managed Console connection."""

from collections.abc import Awaitable, Callable

from app.connection.facade import get_connection, set_params_bulk, validate_params
from app.connection.facade import get_params_as_dict
from app.connection import Connection
from app.agent import current_management_scope
from app.tools import tool_service
from sqlalchemy import select
from core.database import get_db

from .connection_service import resolve_connection
from .contracts import SshConnectionConfig
from .schemas import ConsoleEditorInstallResult

EditorInstaller = Callable[[int, bool], Awaitable[ConsoleEditorInstallResult]]
_installer: EditorInstaller | None = None


async def configured_external_editor_connections() -> list[int]:
    """Update only active Consoles whose administrator already configured an editor."""
    tool = await tool_service.get_tool_record("console")
    if tool is None:
        return []
    connections = (await get_db().scalars(select(Connection).where(
        Connection.tool_id == tool.id, Connection.active.is_(True),
    ).order_by(Connection.id))).all()
    identifiers: list[int] = []
    for connection in connections:
        _, params = await get_params_as_dict(connection, decrypt_passwords=False)
        if params.get("host") != "ssh-executor" and (params.get("code_runtime_port") or params.get("code_runtime_token")):
            identifiers.append(connection.id)
    return identifiers


def register_editor_installer(installer: EditorInstaller) -> None:
    global _installer
    _installer = installer


async def install_connection_editor(connection_id: int, upgrade: bool = False) -> ConsoleEditorInstallResult:
    if _installer is None:
        raise RuntimeError("The code editor deployment adapter is unavailable")
    connection = await get_connection(connection_id)
    if connection is None:
        raise ValueError("Console connection unavailable")
    # Reject globally imposed parameters before changing anything remotely.
    await validate_params(connection.tool_id, {"code_runtime_port": "8766", "code_runtime_token": "deployment-preflight"})
    await get_db().commit()
    return await _installer(connection_id, upgrade)


async def configure_editor_runtime(original: SshConnectionConfig, port: int, credential: str) -> None:
    connection = await get_db().scalar(select(Connection).where(
        Connection.id == original.connection_id).with_for_update().execution_options(populate_existing=True))
    if connection is None or not (await current_management_scope()).allows(connection.agent_id):
        raise ValueError("Console management access changed during deployment")
    current = await resolve_connection(original.connection_id)
    if current != original:
        raise ValueError("Console configuration changed during deployment; retry with the current connection")
    await set_params_bulk(original.connection_id, {
        "code_runtime_port": str(port), "code_runtime_token": credential,
    }, commit=False)
