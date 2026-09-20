"""Hermes installation contribution to the configurable Harness domain."""

from __future__ import annotations

from app.agent import Agent
from app.harnesses import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
)
from core.params import Params
from core.util import get_encryption_service

from . import config_service
from .agent_driver import HERMES_DRIVER
from .manager import manager


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    encryption = get_encryption_service()
    return encryption.decrypt(value) if encryption.is_encrypted(value) else value


class HermesHarnessProvider:
    pipeline_policy = HERMES_DRIVER.pipeline_policy
    code = "hermes"
    driver_code = "hermes"
    label = "Hermes Agent"
    containerized = True
    enabled_param: str | None = Params.HARNESS_HERMES_ENABLED
    max_parallel_tasks = 1

    def capabilities(self) -> frozenset[HarnessCapability]:
        return frozenset({
            "execute", "streaming", "status", "start", "stop", "restart",
            "update", "logs", "refresh", "skills", "runtime_files",
            "mcp", "memory",
        })

    async def provision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
        *,
        token: str | None,
    ) -> HarnessProvisioningResult:
        del request, token
        await config_service.ensure_config(agent)
        runtime = manager.get_agent(agent)
        await runtime.create()
        await runtime.sync()
        await config_service.hydrate_agent(agent)
        snapshot = await config_service.execution_snapshot(agent)
        return HarnessProvisioningResult(
            base_url=str(snapshot.get("url") or "") or None,
            model=str(snapshot.get("model") or "") or None,
            token=_decrypt(str(snapshot.get("api_key") or "")) or None,
            capabilities=self.capabilities(),
        )

    async def deprovision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
    ) -> None:
        del request
        await config_service.hydrate_agent(agent)
        await manager.get_agent(agent).delete()

    async def status(self, agent: Agent) -> str:
        await config_service.hydrate_agent(agent)
        return await manager.get_agent(agent).get_status()

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        await config_service.hydrate_agent(agent)
        runtime = manager.get_agent(agent)
        if action == "start":
            return await runtime.start()
        if action == "stop":
            return await runtime.stop()
        if action == "restart":
            return await runtime.restart()
        if action == "update":
            return await runtime.update()
        await runtime.sync()
        return "synchronized"

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        await config_service.hydrate_agent(agent)
        return await manager.get_agent(agent).get_logs(lines)


provider = HermesHarnessProvider()

__all__ = ["HermesHarnessProvider", "provider"]
