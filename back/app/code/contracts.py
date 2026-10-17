"""Code workspace runtime port; storage and authorization stay in app.code."""

from typing import AsyncContextManager, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

Mode = Literal["read", "edit"]
RUNTIME_CONFIGURATION_LOCK_OFFSET = 8100000000


class CodeRuntimeNotConfiguredError(RuntimeError):
    """The Console requires administrator preparation before opening its IDE."""


class CodeSessionUnavailableError(RuntimeError):
    """The runtime has stopped this session; explicit authorized recovery is needed."""


class RuntimeEndpoint(BaseModel):
    url: str
    credential: str


class CodeConnection(BaseModel):
    """Immutable registered target identity; no transport secrets cross this port."""
    connection_id: int
    fingerprint: str
    owner_user_id: int | None = None


class WorkspaceTarget(BaseModel):
    home: str
    root: str
    git_paths: tuple[str, ...]
    generation: str
    root_identity: str | None = None
    git_identities: tuple[str, ...] = ()
    branch: str | None = None
    head: str | None = None


class RepositoryCandidates(BaseModel):
    paths: list[str] = Field(default_factory=list)
    truncated: bool = False


class CodeRuntime(Protocol):
    async def connection_for_agent(self, agent_id: int) -> CodeConnection: ...
    async def connection(self, connection_id: int) -> CodeConnection: ...
    async def discover(self, connection: CodeConnection, path: str) -> WorkspaceTarget: ...
    async def repositories(self, connection: CodeConnection) -> RepositoryCandidates: ...
    def endpoint(self, reference: CodeConnection) -> AsyncContextManager[RuntimeEndpoint]: ...
    async def open(self, config: CodeConnection, target: WorkspaceTarget, session: UUID, mode: Mode) -> None: ...
    async def close(self, config: CodeConnection, session: UUID, *, discard: bool = False) -> None: ...
    async def touch(self, config: CodeConnection, session: UUID) -> None: ...
    async def navigate(self, config: CodeConnection, session: UUID, file: str | None, view: str) -> None: ...


_runtime: CodeRuntime | None = None


def register_runtime(runtime: CodeRuntime) -> None:
    global _runtime
    _runtime = runtime


def runtime() -> CodeRuntime:
    if _runtime is None:
        raise RuntimeError("The code editor adapter is unavailable")
    return _runtime
