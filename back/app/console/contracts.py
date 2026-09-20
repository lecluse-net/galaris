"""Runtime contracts for the persistent SSH console."""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


ConsoleRunStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "outcome_unknown",
]


class SshConnectionConfig(BaseModel):
    """Decrypted, immutable SSH configuration scoped to one agent run."""

    connection_id: int
    host: str
    port: int = 22
    username: str
    private_key: SecretStr
    private_key_passphrase: SecretStr | None = None
    known_host_key: str
    connect_timeout_s: float = 10.0
    command_timeout_s: float = 300.0
    model_config = ConfigDict(frozen=True)


class ConsoleFile(BaseModel):
    path: str
    size: int | None = None
    change: Literal["created", "modified"] = "modified"


class ConsoleResult(BaseModel):
    run_id: UUID | None = None
    status: ConsoleRunStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = 0
    cwd: str = "."
    cursor: int = 0
    files: list[ConsoleFile] = Field(default_factory=list[ConsoleFile])


class ConsoleStatus(BaseModel):
    reachable: bool
    authenticated: bool
    host_key_verified: bool
    home: str = ""
    home_writable: bool = False
    sftp_available: bool = False
    galaris_exec_available: bool = False
    operation_recovery_available: bool = False
    mode: Literal["standard", "enhanced"] = "standard"
    detected_commands: list[str] = Field(default_factory=list[str])
    error: str = ""


class ExecutionTransport(Protocol):
    async def status(self) -> ConsoleStatus: ...

    async def exec(
        self,
        command: str,
        cwd: str = ".",
        timeout_s: float | None = None,
        *,
        stdin: bytes | None = None,
    ) -> ConsoleResult: ...

    async def start(
        self,
        command: str,
        cwd: str = ".",
        *,
        task_id: UUID | None = None,
        operation_id: UUID | None = None,
    ) -> ConsoleResult: ...

    async def poll(self, run_id: UUID, cursor: int = 0) -> ConsoleResult: ...

    async def write(self, run_id: UUID, data: str) -> ConsoleResult: ...

    async def stop(self, run_id: UUID) -> ConsoleResult: ...

    async def cancel_active(self) -> None: ...

    async def close(self) -> None: ...


class ExecutorManager(Protocol):
    async def request(self, operation: str, **payload: Any) -> dict[str, Any]: ...
