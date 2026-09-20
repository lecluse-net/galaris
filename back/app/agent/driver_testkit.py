"""Reusable contract checks for internal and third-party agent drivers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import UUID

from .contracts import AgentDriver, AgentDriverSpec, AgentEvent, AgentRunRequest, ExecutionResult
from .driver_stream import validated_driver_stream


@dataclass
class ScriptedDriver:
    """Deterministic fault-injection harness; never registered by application startup.

    Scripts can emit invalid objects, raise exceptions, or wait on an Event. Separate
    instances let tests exercise concurrent runs without sharing runtime state.
    """

    spec: AgentDriverSpec
    steps: tuple[object, ...] = ()
    result: ExecutionResult = field(default_factory=lambda: ExecutionResult(prompt="", result="done"))
    requests: list[AgentRunRequest] = field(default_factory=list[AgentRunRequest])
    cancellations: list[UUID] = field(default_factory=list[UUID])
    closed: bool = False

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        self.requests.append(request)
        return self.result

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        from typing import cast

        self.requests.append(request)
        try:
            for step in self.steps:
                if isinstance(step, BaseException):
                    raise step
                if isinstance(step, asyncio.Event):
                    await step.wait()
                else:
                    # Deliberately allow malformed runtime output at this test boundary.
                    yield cast(AgentEvent, step)
        finally:
            self.closed = True

    async def cancel(self, run_id: UUID) -> None:
        self.cancellations.append(run_id)


@dataclass(frozen=True)
class DriverConformanceReport:
    """Evidence collected without depending on a concrete runtime test framework."""

    driver_code: str
    message_events: int
    terminal_result: ExecutionResult
    envelope_json: str


async def exercise_driver_stream(
    driver: AgentDriver,
    request: AgentRunRequest,
) -> DriverConformanceReport:
    """Exercise the portable envelope and the strict stream invariants.

    Bridge test suites can call this helper with a fake transport or recorded runtime. It
    intentionally performs no network setup and does not hide driver exceptions.
    """

    if driver.spec.code != request.driver_code:
        raise AssertionError(
            f"driver/request mismatch: {driver.spec.code!r} != {request.driver_code!r}"
        )
    envelope_json = request.to_envelope().model_dump_json()
    terminal: ExecutionResult | None = None
    message_events = 0
    async for event in validated_driver_stream(driver, request, spec=driver.spec):
        if event.kind == "message":
            message_events += 1
        else:
            terminal = event.result
    if terminal is None:
        raise AssertionError("driver emitted no terminal result")
    return DriverConformanceReport(
        driver_code=driver.spec.code,
        message_events=message_events,
        terminal_result=terminal,
        envelope_json=envelope_json,
    )


__all__ = ["DriverConformanceReport", "ScriptedDriver", "exercise_driver_stream"]
