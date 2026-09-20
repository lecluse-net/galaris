"""Injected port to the optional configurable Harness domain."""

from __future__ import annotations

from typing import Any, Protocol

from .contracts import ConfiguredHarnessSelection, HarnessExecutionPolicy


class AgentHarnessSelectionPort(Protocol):
    async def resolve(self, agent: Any) -> ConfiguredHarnessSelection | None: ...

    async def configuration(self, provider_code: str) -> tuple[HarnessExecutionPolicy, int]: ...


class _HarnessSelectionPortProxy:
    def __init__(self) -> None:
        self._implementation: AgentHarnessSelectionPort | None = None

    def register(self, implementation: AgentHarnessSelectionPort) -> None:
        self._implementation = implementation

    async def resolve(self, agent: Any) -> ConfiguredHarnessSelection | None:
        if self._implementation is None:
            return None
        return await self._implementation.resolve(agent)

    async def configuration(self, provider_code: str) -> tuple[HarnessExecutionPolicy, int]:
        if self._implementation is None:
            return HarnessExecutionPolicy(), 0
        return await self._implementation.configuration(provider_code)


harness_selection_port = _HarnessSelectionPortProxy()


def register_harness_selection_port(implementation: AgentHarnessSelectionPort) -> None:
    harness_selection_port.register(implementation)


__all__ = [
    "AgentHarnessSelectionPort",
    "harness_selection_port",
    "register_harness_selection_port",
]
