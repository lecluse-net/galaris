"""Driver that delegates every network Harness to the common OpenAI client."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from app.agent import AgentEvent, AgentRunRequest, ExecutionResult
from app.agent.contracts import ResolvedExecutionTarget

from .agent_driver import OPENAI_MESSAGES_DRIVER
from .openai_client import OpenAIHarnessClient
from .service import execution_credentials, resolve_target


def _harness_id(request: AgentRunRequest) -> UUID:
    target = request.target
    if target is None or not target.target_ref.startswith("harness:"):
        raise RuntimeError("The network Harness run has no frozen Harness target.")
    try:
        return UUID(target.target_ref.removeprefix("harness:"))
    except ValueError as exc:
        raise RuntimeError("The frozen Harness target reference is invalid.") from exc


@dataclass(frozen=True)
class OpenAIMessagesDriver:
    spec = OPENAI_MESSAGES_DRIVER

    def execution_target(self, agent_id: int, configuration: Mapping[str, Any]) -> ResolvedExecutionTarget:
        return ResolvedExecutionTarget(
            provider_code=str(configuration.get("provider_code") or self.spec.code),
            target_ref=f"harness:{configuration['harness_id']}",
            revision=str(configuration.get("revision") or ""), transport="chat_completions",
            metadata={"model": str(configuration.get("model") or "")},
        )

    async def _client(self, request: AgentRunRequest) -> OpenAIHarnessClient:
        credentials = await execution_credentials(_harness_id(request))
        return OpenAIHarnessClient(
            base_url=credentials.base_url,
            token=credentials.token,
        )

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        return await (await self._client(request)).run(request.to_envelope())

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        stream = (await self._client(request)).stream(request.to_envelope())
        async with aclosing(cast(AsyncGenerator[AgentEvent, None], stream)) as events:
            async for event in events:
                yield event

    async def cancel(self, run_id: UUID) -> None:
        raise RuntimeError("The network Harness does not support cancellation by run_id.")

    async def execution_configuration(self, agent: Any) -> dict[str, Any]:
        target = await resolve_target(agent)
        if target is None:
            raise RuntimeError("The network Harness driver has no selected Harness.")
        return {
            "harness_id": str(target.id),
            "provider_code": target.provider_code,
            "revision": str(target.revision),
            "base_url": target.base_url,
            "model": target.model,
            "capabilities": sorted(target.capabilities),
        }


def create_driver() -> OpenAIMessagesDriver:
    return OpenAIMessagesDriver()


__all__ = ["OpenAIMessagesDriver", "create_driver"]
