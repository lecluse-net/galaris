"""Persistent SSH console for agents using the internal harness."""

from app.agent import register_agent_profile_observer

from .contracts import (
    ConsoleFile,
    ConsoleResult,
    ConsoleStatus,
    ExecutionTransport,
    ExecutorManager,
    SshConnectionConfig,
    RepositoryTarget,
    RepositoryListing,
)
from .console_service import ConsoleRunResource, build_run_resource
from .connection_service import resolve_ssh_connection, resolve_connection, resolve_active_connection
from .repository import discover_repository, list_repositories, code_runtime_tunnel, connection_generation
from .editor_service import register_editor_installer, configure_editor_runtime, configured_external_editor_connections
from .schemas import ConsoleEditorInstallResult
from .ssh_client import SshExecutionTransport
from .provisioning import provision_new_agent_console

register_agent_profile_observer("console_defaults", provision_new_agent_console)


async def _test_saved_connection(connection_id: int) -> bool:
    transport = SshExecutionTransport(await resolve_connection(connection_id))
    try:
        result = await transport.status()
        return result.reachable and result.authenticated and result.host_key_verified and result.sftp_available
    finally:
        await transport.close()


from app.tools import register_connection_probe

register_connection_probe("console", _test_saved_connection)

__all__ = [
    "ConsoleFile",
    "ConsoleResult",
    "ConsoleStatus",
    "ExecutionTransport",
    "ExecutorManager",
    "SshConnectionConfig",
    "ConsoleRunResource",
    "build_run_resource",
    "resolve_ssh_connection",
    "RepositoryTarget", "resolve_connection", "resolve_active_connection", "discover_repository", "code_runtime_tunnel", "connection_generation",
    "RepositoryListing", "list_repositories",
    "register_editor_installer", "configure_editor_runtime", "ConsoleEditorInstallResult", "SshExecutionTransport",
    "configured_external_editor_connections",
]
