"""Console use cases shared by MCP tools and administration routes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .connection_service import require_ssh_connection
from .contracts import SshConnectionConfig
from .file_transport import SshAgentFileTransport
from .ssh_client import SshExecutionTransport


@dataclass
class ConsoleRunResource:
    """Secrets and pooled transports frozen for the lifetime of one agent run."""

    config: SshConnectionConfig
    execution: SshExecutionTransport = field(init=False)
    files: SshAgentFileTransport = field(init=False)

    def __post_init__(self) -> None:
        self.execution = SshExecutionTransport(self.config)
        self.files = SshAgentFileTransport(self.execution)

    async def close(self) -> None:
        await self.execution.close()


async def build_run_resource(agent_id: int) -> ConsoleRunResource:
    return ConsoleRunResource(await require_ssh_connection(agent_id))
