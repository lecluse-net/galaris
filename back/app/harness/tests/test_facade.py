from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.agent import Agent
from app.harness import facade
from app.harness.contracts import HarnessAction, HarnessCapability


class _Supervisor:
    def __init__(self, driver_code: str) -> None:
        self.driver_code = driver_code
        self.status_call = AsyncMock(return_value="running")
        self.action_call = AsyncMock(return_value="done")

    def capabilities(self, agent: Agent) -> frozenset[HarnessCapability]:
        del agent
        return frozenset({"status", "restart"})

    async def status(self, agent: Agent) -> str:
        return cast(str, await self.status_call(agent))

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        return cast(str, await self.action_call(agent, action))

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        del agent, lines
        return []

    async def refresh(self, agent: Agent) -> None:
        del agent


@pytest.mark.asyncio
async def test_facade_dispatches_status_and_actions_to_driver_contribution() -> None:
    supervisor = _Supervisor("test-managed")
    facade.register_harness_supervisor(supervisor)
    agent = cast(Agent, SimpleNamespace(agent_driver="test-managed"))

    assert await facade.status(agent) == "running"
    assert await facade.run_action(agent, "restart") == "done"
    assert facade.capabilities(agent) == frozenset({"status", "restart"})
    supervisor.status_call.assert_awaited_once_with(agent)
    supervisor.action_call.assert_awaited_once_with(agent, "restart")


@pytest.mark.asyncio
async def test_facade_rejects_capability_not_advertised_by_driver() -> None:
    supervisor = _Supervisor("test-managed-unsupported")
    facade.register_harness_supervisor(supervisor)
    agent = cast(Agent, SimpleNamespace(agent_driver="test-managed-unsupported"))

    with pytest.raises(facade.UnsupportedHarnessCapabilityError):
        await facade.run_action(agent, "update")
