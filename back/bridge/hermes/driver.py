"""Hermes driver exposed exclusively through the ``app.agent`` facade."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import Any, Final, cast
from uuid import UUID

from app.agent.contracts import (
    AgentDriverError,
    AIMessage,
    AgentDriverSpec,
    AgentEvent,
    AgentRunRequest,
    AgentRunCheckpoint,
    HarnessCancellationReceipt,
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
        if stored == "kanban" and request.target is not None and request.target.target_ref.startswith("harness:"):
            raise AgentDriverError("The legacy Kanban continuation has no common authorization context; stop it before upgrading.")
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
        if request.deep_session_id is not None:
            async with aclosing(_stream_deep(request)) as events:
                async for event in events:
                    yield event
            return
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

    async def request_cancellation(self, run_id: UUID) -> HarnessCancellationReceipt:
        from .kanban import cancel_if_active
        from .executor import request_cancellation

        if await cancel_if_active(run_id):
            return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="requested")
        return await request_cancellation(run_id)

    async def request_checkpoint_cancellation(
        self, run_id: UUID, checkpoint: AgentRunCheckpoint,
    ) -> HarnessCancellationReceipt:
        from .executor import request_cancellation

        return await request_cancellation(run_id, checkpoint=checkpoint)

    async def execution_configuration(self, agent: Any) -> dict[str, Any]:
        """Build the run snapshot from the driver-owned configuration table."""

        from .config_service import execution_snapshot

        return await execution_snapshot(agent)

def create_driver() -> HermesAgentDriver:
    return HermesAgentDriver()


async def _stream_deep(request: AgentRunRequest) -> AsyncGenerator[AgentEvent, None]:
    from core.util import as_dict
    from . import client, session_binding

    if not request.deep_credential or not request.deep_control_credential:
        raise PermissionError("Hermes Deep requires both session credentials")
    target = client.HermesTarget.from_config(request.agent.driver_config, agent_code=request.agent.code)
    await client.verify_authorization_control(target, require_deep=True)
    logical = f"deep-{request.deep_session_id}"
    session = request.deep_native_session or logical
    await client.ensure_session(target, session, title="Deep")
    yield AgentEvent.from_message(AIMessage(type="tool", content="", native_session_ref=session))
    run_id = await client.start_run(
        target, session_id=session, session_key=logical, message=request.objective,
        system_message=request.system_instructions, run_context=request.deep_control_credential,
        deep_context=request.deep_credential, submission=str(request.run_id),
    )
    chunks: list[str] = []
    answer = ""
    terminal = False
    success = False
    try:
        stream = cast(AsyncGenerator[dict[str, Any], None], client.run_events(target, run_id))
        async with aclosing(stream):
            async for event in stream:
                name = str(event.get("event") or "")
                data = as_dict(event.get("data"))
                session = session_binding.effective_session_id(session, name, data)
                if name in {"assistant.delta", "message.delta"}:
                    delta = data.get("delta") or data.get("text") or data.get("content")
                    if isinstance(delta, str) and delta:
                        chunks.append(delta)
                        yield AgentEvent.from_message(AIMessage(type="text", content=delta))
                elif name in {"tool.started", "tool.completed", "tool.failed"}:
                    tool = str(data.get("tool_name") or data.get("name") or "Tool")
                    identifier = str(data.get("tool_call_id") or data.get("call_id") or "")
                    state = "running" if name == "tool.started" else "failed" if name == "tool.failed" else "completed"
                    yield AgentEvent.from_message(AIMessage(type="tool", tool_name=tool[:200],
                        content=str(data.get("output") or data.get("text") or ""),
                        activity_ref=identifier[:500] or None, activity_state=state))
                elif name == "assistant.completed" and isinstance(data.get("content"), str):
                    answer = str(data["content"])
                elif name in {"run.completed", "run.failed", "run.cancelled"}:
                    terminal = True
                    success = name == "run.completed"
                    if isinstance(data.get("output"), str):
                        answer = str(data["output"])
                    break
                elif name == "error":
                    raise RuntimeError("The Hermes Deep event stream was interrupted")
    finally:
        if not terminal:
            import asyncio
            try:
                async with asyncio.timeout(5):
                    await client.stop_run(target, run_id)
            except Exception:
                pass
    if not terminal:
        raise RuntimeError("Hermes Deep ended without an execution result")
    yield AgentEvent.from_result(ExecutionResult(prompt=request.objective, result=answer or "".join(chunks),
        success=success, metadata={"deep_native_session": session}))
