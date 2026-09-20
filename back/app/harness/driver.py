"""Factory adapting the internal Pydantic AI harness to ``AgentDriver``."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import cast
from uuid import UUID

from app.agent.contracts import (
    AgentDriverSpec,
    AgentEvent,
    AgentRunRequest,
    ExecutionResult,
    HarnessCancellationReceipt,
)
from app.agent.registry import INTERNAL_HARNESS


@dataclass(frozen=True)
class InternalHarness:
    """Internal harness adapter for the shared ``AgentRunRequest`` contract."""

    spec: AgentDriverSpec = INTERNAL_HARNESS

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        from .executor import run

        return await run(request)

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        from .executor import stream

        async with aclosing(cast(AsyncGenerator[AgentEvent, None], stream(request))) as events:
            async for event in events:
                yield event

    async def cancel(self, run_id: UUID) -> None:
        from .run_control import cancel

        await cancel(run_id)

    async def request_cancellation(self, run_id: UUID) -> HarnessCancellationReceipt:
        from .run_control import cancel, is_active

        was_active = is_active(run_id)
        await cancel(run_id)
        return HarnessCancellationReceipt(
            run_id=run_id, scope="local",
            state="confirmed" if was_active and not is_active(run_id) else "unknown",
        )

def create_driver() -> InternalHarness:
    return InternalHarness()
