"""Hermes lifecycle contribution discovered by the generic harness facade."""

from typing import Literal

from app.agent import Agent

from . import config_service
from .manager import HermesAgent, manager

type HarnessAction = Literal["start", "stop", "restart", "update"]
type HarnessCapability = Literal[
    "status",
    "start",
    "stop",
    "restart",
    "update",
    "logs",
    "refresh",
]


class HermesHarnessSupervisor:
    driver_code = "hermes"

    def capabilities(self, agent: Agent) -> frozenset[HarnessCapability]:
        del agent
        return frozenset(
            {"status", "start", "stop", "restart", "update", "logs", "refresh"}
        )

    async def _runtime(self, agent: Agent) -> HermesAgent:
        await config_service.hydrate_agent(agent)
        return manager.get_agent(agent)

    async def status(self, agent: Agent) -> str:
        return await (await self._runtime(agent)).get_status()

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        runtime = await self._runtime(agent)
        if action == "start":
            return await runtime.start()
        if action == "stop":
            return await runtime.stop()
        if action == "restart":
            return await runtime.restart()
        return await runtime.update()

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        return await (await self._runtime(agent)).get_logs(lines)

    async def refresh(self, agent: Agent) -> None:
        await (await self._runtime(agent)).sync()


supervisor = HermesHarnessSupervisor()

__all__ = ["HermesHarnessSupervisor", "supervisor"]
