"""Allow existing Claude containers to drain and be removed during a Harness switch."""

from app.agent import Agent, DriverPipelinePolicy
from app.harnesses import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
)
from core.params import Params
from bridge.harness import manager


class RetiredClaudeHarnessProvider:
    pipeline_policy = DriverPipelinePolicy(
        use_planner=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
    )
    code = "claude_agent"
    driver_code = "openai_messages"
    label = "Claude Agent"
    containerized = True
    enabled_param: str | None = Params.HARNESS_CLAUDE_AGENT_ENABLED
    max_parallel_tasks = None

    def capabilities(self) -> frozenset[HarnessCapability]:
        return frozenset({"execute", "streaming", "status", "start", "stop", "logs", "mcp", "memory"})

    async def provision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
        *,
        token: str | None,
    ) -> HarnessProvisioningResult:
        raise RuntimeError("This Claude Agent runtime is retired. Select Claude Agent in the agent record.")

    async def deprovision(self, agent: Agent, request: HarnessProvisioningRequest) -> None:
        await manager.delete_instance(agent.code)
        from app.mcp import mcp_token_service

        await mcp_token_service.revoke_system_tokens(agent.id)

    async def status(self, agent: Agent) -> str:
        return await manager.get_instance_status(agent.code)

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        if action not in {"start", "stop"}:
            raise ValueError("A retired Claude Agent runtime can only be started or stopped.")
        return await manager.run_action(agent.code, action)

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        return await manager.get_logs(agent.code, lines)


provider = RetiredClaudeHarnessProvider()
