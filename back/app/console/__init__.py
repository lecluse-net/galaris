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
)
from .console_service import ConsoleRunResource, build_run_resource
from .connection_service import resolve_ssh_connection, resolve_connection, resolve_active_connection
from .repository import discover_repository, code_runtime_tunnel, connection_generation
from .editor_service import register_editor_installer, configure_editor_runtime
from .schemas import ConsoleEditorInstallResult
from .ssh_client import SshExecutionTransport
from .provisioning import provision_new_agent_console

register_agent_profile_observer("console_defaults", provision_new_agent_console)

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
    "register_editor_installer", "configure_editor_runtime", "ConsoleEditorInstallResult", "SshExecutionTransport",
]
