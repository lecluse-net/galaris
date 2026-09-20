"""Persist and apply dispatcher routing decisions.

The dispatcher chooses EXEC, BRIEFING or PLAN. It does not own task hierarchy or
execution; those concerns remain behind the task port and agent workflow.

Usage:
    >>> from app.agent import dispatcher_service
    >>> await dispatcher_service.run(task)
"""

from core.i18n import current_language

from .contracts import AgentTask, DispatchResult, TaskPhase, TaskTransition
from .dispatcher import get_dispatcher
from .task_port import task_port


async def _store_language(task: AgentTask, dispatch_result: DispatchResult) -> None:
    data = dict(task.data) if isinstance(task.data, dict) else {}
    language = await current_language(data.get("language") or dispatch_result.decision.language)
    dispatch_result.decision.language = language
    data["language"] = language
    task.data = data


async def run(
    task: AgentTask, use_default_params: bool = False, use_memory: bool = True
) -> DispatchResult:

    dispatcher = get_dispatcher()
    dispatch_result = await dispatcher.run(
        task, use_default_params=use_default_params, use_memory=use_memory
    )
    task.effort = dispatch_result.decision.effort
    # The route is authoritative after context and driver policy have constrained it.

    # Persist decision trace, cost, and any failure.
    await _update_task_after_dispatch(task, dispatch_result)

    # A failed dispatch is already terminal.
    if not dispatch_result.success:
        return dispatch_result

    if dispatch_result.decision.route == "PLAN":
        # The scheduler resumes PLAN through planner_service.advance.
        await _update_task_status(task, TaskPhase.PLAN)
        return dispatch_result

    # The runner orchestrates background or streaming execution after DISPATCH.
    await _update_task_status(task, TaskPhase.DISPATCH)

    return dispatch_result


async def _update_task_status(task: AgentTask, status: TaskPhase) -> None:
    """Update task workflow status."""
    if status == TaskPhase.PLAN:
        task_port.transition(task, TaskTransition.ROUTE_TO_PLAN)
    else:
        from .workflow import route_to_driver_pipeline

        route_to_driver_pipeline(task)
    await task_port.save(task)


async def _update_task_after_dispatch(
    task: AgentTask,
    dispatch_result: DispatchResult,
) -> None:
    """Persist the dispatch trace and cumulative cost without hierarchy placement."""
    # Resolve the user language before serializing the complete dispatch result.
    await _store_language(task, dispatch_result)
    task.set_dispatch_result(dispatch_result)
    task.effort = dispatch_result.decision.effort

    # Update cumulative cost.
    task.cost += dispatch_result.cost

    # Mark failure when necessary.
    if not dispatch_result.success:
        task_port.transition(task, TaskTransition.FAIL)
        task_port.clear_pauses(task)

    # Saving also emits the websocket event.
    await task_port.save(task)
