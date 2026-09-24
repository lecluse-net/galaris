"""Injected port to the optional configurable Harness domain."""

from __future__ import annotations

from typing import Any, Protocol
from collections.abc import Collection

from .contracts import AgentRunRequest, ConfiguredHarnessSelection, HarnessExecutionPolicy


class AgentHarnessSelectionPort(Protocol):
    async def projected_skill_agent_ids(self, agent_ids: Collection[int] | None = None) -> list[int]: ...

    async def request_skill_sync(self, agent_id: int) -> None: ...

    async def prepare_execution(self, request: AgentRunRequest) -> None: ...

    async def resolve(self, agent: Any) -> ConfiguredHarnessSelection | None: ...

    async def configuration(self, provider_code: str) -> tuple[HarnessExecutionPolicy, int]: ...


class _HarnessSelectionPortProxy:
    def __init__(self) -> None:
        self._implementation: AgentHarnessSelectionPort | None = None

    def register(self, implementation: AgentHarnessSelectionPort) -> None:
        self._implementation = implementation

    async def prepare_execution(self, request: AgentRunRequest) -> None:
        if self._implementation is not None:
            await self._implementation.prepare_execution(request)

    async def projected_skill_agent_ids(self, agent_ids: Collection[int] | None = None) -> list[int]:
        if self._implementation is None:
            return []
        return await self._implementation.projected_skill_agent_ids(agent_ids)

    async def request_skill_sync(self, agent_id: int) -> None:
        if self._implementation is not None:
            await self._implementation.request_skill_sync(agent_id)

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
