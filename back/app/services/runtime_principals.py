"""Injected identity port: token storage remains owned by the MCP domain."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RuntimePrincipal:
    id: int
    agent_id: int
    enabled: bool


class RuntimePrincipalPort(Protocol):
    async def for_agent(self, agent_id: int) -> RuntimePrincipal | None: ...
    async def by_key(self, token_key: int) -> RuntimePrincipal | None: ...
    async def authenticate(self, bearer: str) -> RuntimePrincipal | None: ...


_principal_port: RuntimePrincipalPort | None = None


def register_runtime_principal_port(port: RuntimePrincipalPort) -> None:
    global _principal_port
    _principal_port = port


def runtime_principal_port() -> RuntimePrincipalPort:
    if _principal_port is None:
        raise PermissionError("The managed MCP principal provider is unavailable")
    return _principal_port
