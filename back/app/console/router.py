"""Administration routes for SSH console connections and the embedded executor."""

from __future__ import annotations

import asyncssh
from fastapi import APIRouter, HTTPException, status
from loguru import logger

from app.agent import AgentOwnerAssertion, agent_service, current_management_scope
from app.connection import connection_service
from app.tools import tool_service
from core.authorize import Privileges, authorize

from .connection_service import is_embedded_executor_in_use, resolve_connection
from .helper_service import install_connection_helper
from .keys import generate_ed25519_keypair
from .manager import embedded_executor_manager
from .provisioning import provision_embedded_console
from .schemas import (
    ConsoleConnectionTest,
    ConsoleHelperInstallResult,
    EmbeddedProvisionRequest,
    EmbeddedProvisionResult,
    ExecutorActionRequest,
    ExecutorAvailability,
    ExecutorResponse,
    GeneratedConsoleKey,
    HostKeyScanRequest,
    HostKeyScanResult,
)
from .ssh_client import SshExecutionTransport


router = APIRouter(prefix="/console", tags=["console"])


async def _managed_connection(connection_id: int):
    connection = await connection_service.get_connection(connection_id)
    scope = await current_management_scope()
    if connection is None or not scope.allows(connection.agent_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global Agent management is required",
        )


async def _console_tool_id() -> int:
    record = await tool_service.get_tool_record("console")
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The built-in console tool has not been synchronized yet",
        )
    return record.id


@router.post("/host-key/scan", response_model=HostKeyScanResult)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def scan_host_key(data: HostKeyScanRequest) -> HostKeyScanResult:
    """Fetch an untrusted host key for explicit administrator confirmation."""
    try:
        key = await asyncssh.get_server_host_key(data.host, data.port)
    except (OSError, asyncssh.Error) as exc:
        raise HTTPException(status_code=502, detail=f"SSH host-key scan failed: {exc}") from exc
    if key is None:
        raise HTTPException(status_code=502, detail="The SSH server returned no host key")
    exported = key.export_public_key().decode("ascii").strip()
    return HostKeyScanResult(
        host=data.host,
        port=data.port,
        key=exported,
        fingerprint=key.get_fingerprint(),
    )


@router.post("/connections/{connection_id}/generate-key", response_model=GeneratedConsoleKey)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def generate_connection_key(connection_id: int) -> GeneratedConsoleKey:
    config_connection = await _managed_connection(connection_id)
    if config_connection.tool_id != await _console_tool_id():
        raise HTTPException(status_code=400, detail="Connection is not an SSH console")
    private_key, public_key = generate_ed25519_keypair()
    await connection_service.set_param(connection_id, "private_key", private_key)
    return GeneratedConsoleKey(connection_id=connection_id, public_key=public_key)


@router.post("/connections/{connection_id}/test", response_model=ConsoleConnectionTest)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def test_connection(connection_id: int) -> ConsoleConnectionTest:
    try:
        await _managed_connection(connection_id)
        transport = SshExecutionTransport(await resolve_connection(connection_id))
        try:
            result = await transport.status()
        finally:
            await transport.close()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConsoleConnectionTest(connection_id=connection_id, status=result)


@router.post(
    "/connections/{connection_id}/install-helper",
    response_model=ConsoleHelperInstallResult,
)
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def install_connection_galaris_exec(
    connection_id: int,
) -> ConsoleHelperInstallResult:
    try:
        await _managed_connection(connection_id)
        return await install_connection_helper(connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "galaris-exec installation failed for connection {}",
            connection_id,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/embedded/provision", response_model=EmbeddedProvisionResult)
@authorize(privileges=Privileges.CONNECTION_EDIT, assertion=AgentOwnerAssertion)
async def provision_embedded(data: EmbeddedProvisionRequest) -> EmbeddedProvisionResult:
    agent = await agent_service.get(data.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.agent_driver != "internal":
        raise HTTPException(
            status_code=400,
            detail="SSH console provisioning is available only with the internal harness",
        )
    try:
        return await provision_embedded_console(agent)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_READ_OPERATIONS = frozenset({"health", "status", "list_users", "user_usage", "list_sessions"})
_ADMIN_OPERATIONS = frozenset({
    "rotate_key",
    "enable_user",
    "disable_user",
    "stop_session",
    "cleanup_partials",
    "cleanup_caches",
    "recycle",
})


@router.get("/executor/availability", response_model=ExecutorAvailability)
@authorize(privileges=Privileges.CONSOLE_ACCESS)
async def executor_availability() -> ExecutorAvailability:
    return ExecutorAvailability(in_use=await is_embedded_executor_in_use())


@router.get("/executor/status", response_model=ExecutorResponse)
@authorize(privileges=Privileges.CONSOLE_ACCESS)
async def executor_status() -> ExecutorResponse:
    await _require_global_scope()
    try:
        result = await embedded_executor_manager.request("status")
        return ExecutorResponse(ok=True, result=result)
    except RuntimeError as exc:
        return ExecutorResponse(ok=False, error=str(exc))


@router.post("/executor/action", response_model=ExecutorResponse)
@authorize(privileges=Privileges.CONSOLE_ADMIN)
async def executor_action(data: ExecutorActionRequest) -> ExecutorResponse:
    await _require_global_scope()
    if data.operation not in _READ_OPERATIONS | _ADMIN_OPERATIONS:
        raise HTTPException(status_code=400, detail="Unsupported executor operation")
    try:
        result = await embedded_executor_manager.request(data.operation, **data.payload)
        return ExecutorResponse(ok=True, result=result)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
