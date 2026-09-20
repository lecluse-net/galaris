"""Hermes driver exposed exclusively through the ``app.agent`` facade."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import Any, Final, cast
from uuid import UUID

from app.agent.contracts import (
    AgentDriverError,
    AgentDriverSpec,
    AgentEvent,
    AgentRunRequest,
    ExecutionResult,
    ResolvedExecutionTarget,
    ResolvedExecutionCapabilities,
)
from .agent_driver import HERMES_DRIVER


# Code-only switch for both card routing and its LLMCall tool-trace fallback.
# Do not expose it through settings, params, or the API.
HERMES_HIGH_KANBAN_ENABLED: Final[bool] = False


def _require_task(request: AgentRunRequest) -> None:
    """Reject taskless use of the autonomous Hermes runtime."""

    if request.task_id is None:
        raise AgentDriverError("The Hermes driver requires a durable Galaris Task.")


def _execution_strategy(request: AgentRunRequest) -> str:
    """Resolve a strategy while preserving every already-started runtime."""

    checkpoint = request.resume_checkpoint
    if checkpoint is not None and checkpoint.driver_code == request.driver_code:
        stored = str(checkpoint.data.get("execution_strategy") or "").strip().lower()
        return stored or "direct"
    strategy = request.execution_strategy.strip().lower()
    if request.effort == "high" and HERMES_HIGH_KANBAN_ENABLED:
        return "kanban"
    if strategy == "kanban":
        return "direct"
    return strategy


def _request_with_strategy(
    request: AgentRunRequest,
    strategy: str,
) -> AgentRunRequest:
    """Expose the effective bridge-owned strategy to the selected adapter."""

    if request.execution_strategy == strategy:
        return request
    return replace(request, execution_strategy=strategy)


@dataclass(frozen=True)
class HermesAgentDriver:
    """Adapter from the Hermes runtime to the shared Galaris contract."""

    spec: AgentDriverSpec = HERMES_DRIVER

    def execution_target(self, agent_id: int, configuration: Mapping[str, Any]) -> ResolvedExecutionTarget:
        raw = configuration.get("kanban")
        transport = str(cast(Mapping[str, object], raw).get("transport") or "") if isinstance(raw, Mapping) else ""
        return ResolvedExecutionTarget(
            provider_code=self.spec.code, target_ref=f"agent:{agent_id}:driver:{self.spec.code}",
            transport=transport,
            capabilities=ResolvedExecutionCapabilities(
                execution=self.spec.execution_capabilities, management=self.spec.management_capabilities,
            ),
            metadata={"model_gateway": str(configuration.get("model_gateway") or "")},
        )

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        _require_task(request)
        strategy = _execution_strategy(request)
        request = _request_with_strategy(request, strategy)
        if strategy == "direct":
            from .executor import run
        elif strategy == "kanban":
            from .kanban import run
        else:
            raise ValueError(f"Unsupported Hermes execution strategy: {strategy}")

        return await run(request)

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        _require_task(request)
        strategy = _execution_strategy(request)
        request = _request_with_strategy(request, strategy)
        if strategy == "direct":
            from .executor import stream
        elif strategy == "kanban":
            from .kanban import stream
        else:
            raise ValueError(f"Unsupported Hermes execution strategy: {strategy}")

        async with aclosing(cast(AsyncGenerator[AgentEvent, None], stream(request))) as events:
            async for event in events:
                yield event

    async def cancel(self, run_id: UUID) -> None:
        from .kanban import cancel_if_active

        if await cancel_if_active(run_id):
            return
        from .executor import cancel

        await cancel(run_id)

    async def execution_configuration(self, agent: Any) -> dict[str, Any]:
        """Build the run snapshot from the driver-owned configuration table."""

        from .config_service import execution_snapshot

        return await execution_snapshot(agent)

def create_driver() -> HermesAgentDriver:
    return HermesAgentDriver()
