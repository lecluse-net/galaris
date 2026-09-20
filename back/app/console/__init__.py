"""Persistent SSH console for agents using the internal harness."""

from app.agent import register_agent_profile_observer

from .contracts import (
    ConsoleFile,
    ConsoleResult,
    ConsoleStatus,
    ExecutionTransport,
    ExecutorManager,
    SshConnectionConfig,
)
from .console_service import ConsoleRunResource, build_run_resource
from .connection_service import resolve_ssh_connection
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
]
