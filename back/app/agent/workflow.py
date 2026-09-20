"""Agent pipeline orchestration independent from the scheduler."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from .contracts import AIMessage, AgentTask, DispatchResult, TaskPhase, TaskTransition
from .task_port import task_port


def task_uses_briefing(task: AgentTask) -> bool:
    """Honor the dispatcher's explicit choice, retaining old undecided rows."""
    get_dispatch = getattr(task, "get_dispatch_result", None)
    decision = cast(DispatchResult | None, get_dispatch()) if callable(get_dispatch) else None
    if decision is not None:
        if decision.decision.route == "BRIEFING":
            return True
        if "dispatch_choices" in decision.pipeline_policy:
            return False
    from .registry import should_use_briefing

    agent = getattr(task, "agent", None)
    return should_use_briefing(getattr(agent, "agent_driver", None), task.effort)


def route_to_driver_pipeline(task: AgentTask) -> TaskPhase:
    """Apply the selected execution path before invoking the driver."""
    has_briefing = (
        callable(getattr(task, "get_briefing_result", None))
        and task.get_briefing_result() is not None
    )
    event = (
        TaskTransition.ROUTE_TO_BRIEFING
        if task_uses_briefing(task)
        and not has_briefing
        else TaskTransition.ROUTE_TO_EXECUTION
    )
    return task_port.transition(task, event)


async def run_stream(task: AgentTask) -> AsyncIterator[AIMessage]:
    """Run dispatcher, optional briefing, and driver for the OpenAI stream."""
    from . import briefing_service, executor_service

    if not await should_execute(task):
        return
    if task.status == TaskPhase.BRIEFING:
        await briefing_service.run(task)
    async for message in executor_service.stream(task):
        yield message


async def should_execute(task: AgentTask) -> bool:
    """Honor the dispatch decision and prevent direct execution of PLAN."""
    from . import dispatcher_service

    if task.status == TaskPhase.CREATE:
        dispatch_result = await dispatcher_service.run(task)
        if not dispatch_result.success or dispatch_result.decision.route == "PLAN":
            return False
    return True


async def run_step(task: AgentTask) -> None:
    """Execute exactly the agentic step for the current durable phase."""
    from . import briefing_service, dispatcher_service, executor_service, planner_service

    if task.paused:
        return
    if task.status == TaskPhase.CREATE:
        await dispatcher_service.run(task)
        return
    if task.status == TaskPhase.BRIEFING:
        await briefing_service.run(task)
        return
    if task.status == TaskPhase.PLAN:
        await planner_service.advance(task)
        return
    if task.status != TaskPhase.DISPATCH:
        return

    # Compatibility for legacy HIGH rows that are already in DISPATCH.
    if (
        task_uses_briefing(task)
        and task.get_briefing_result() is None
        and await briefing_service.is_enabled(task)
    ):
        task_port.transition(task, TaskTransition.ROUTE_TO_BRIEFING)
        await task_port.save(task)
        return
    await executor_service.run(task)
