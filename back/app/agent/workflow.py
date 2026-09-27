"""Agent pipeline orchestration independent from the scheduler."""

from __future__ import annotations

from collections.abc import AsyncIterator
from .contracts import AIMessage, AgentTask, TaskPhase, TaskTransition
from .task_port import task_port


def route_to_driver_pipeline(task: AgentTask) -> TaskPhase:
    """Route the admitted objective directly to its selected executor."""
    return task_port.transition(task, TaskTransition.ROUTE_TO_EXECUTION)


async def run_stream(task: AgentTask) -> AsyncIterator[AIMessage]:
    """Run the dispatcher and driver for the OpenAI stream."""
    from . import executor_service

    if not await should_execute(task):
        return
    async for message in executor_service.stream(task):
        yield message


async def should_execute(task: AgentTask) -> bool:
    """Honor the dispatch decision and prevent direct execution of PLAN."""
    from . import dispatcher_service

    if task.paused or task.status == TaskPhase.PLAN:
        return False
    if task.status == TaskPhase.CREATE:
        dispatch_result = await dispatcher_service.run(task)
        if not dispatch_result.success or dispatch_result.decision.route == "PLAN":
            return False
    return True


async def run_step(task: AgentTask) -> None:
    """Execute exactly the agentic step for the current durable phase."""
    from . import dispatcher_service, executor_service, planner_service

    if task.paused:
        return
    if task.status == TaskPhase.CREATE:
        await dispatcher_service.run(task)
        return
    if task.status == TaskPhase.PLAN:
        await planner_service.advance(task)
        return
    if task.status == TaskPhase.DISPATCH:
        await executor_service.run(task)
