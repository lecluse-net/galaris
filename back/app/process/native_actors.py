"""Typed workflow assignments and bounded human work receipts."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent import AgentManagementScope, get_agent_record
from core.database import get_db
from core.user import get_user_record

from .bpmn import Workflow, Node, decision_activity
from .models import ProcessRun, ProcessNodeRun, ProcessNodeAttempt
from .process_service import TERMINAL_STATUSES
from .human_directory import list_process_humans


async def human_options(agent_id: int) -> list[dict[str, Any]]:
    """Select active humans from the shared messaging contact directory."""
    options: dict[int, dict[str, Any]] = {}
    for contact in await list_process_humans(agent_id):
        user_id = contact.user_id
        if user_id is None or user_id in options:
            continue
        user = await get_user_record(user_id)
        if user is not None and user.is_active:
            options[user_id] = {"id": user_id, "label": contact.display_name}
    return list(options.values())


async def validate_assignments(graph: Workflow, scope: int | AgentManagementScope) -> None:
    # Empty lanes are saved layout, not participants in this execution.
    # Validate only actors actually referenced by a node in this graph.
    used = {node.config.get("actor") for node in graph.nodes if isinstance(node.config.get("actor"), str)}
    actors = [actor for actor in graph.actors if actor.id in used]
    agent_ids = {actor.agent_id for actor in actors if actor.kind == "agent" and actor.agent_id is not None}
    if graph.execution_agent_id is not None:
        agent_ids.add(graph.execution_agent_id)
    for agent_id in agent_ids:
        if isinstance(scope, int):
            if agent_id != scope:
                raise PermissionError("An agent cannot assign another agent's execution")
        else:
            scope.require(agent_id)
        if await get_agent_record(agent_id) is None:
            raise ValueError("The assigned agent no longer exists")
    for actor in actors:
        if actor.kind == "human":
            user = await get_user_record(actor.user_id) if actor.user_id is not None else None
            if user is None or not user.is_active:
                raise ValueError("Each human actor requires an active assigned user")
    for node in graph.nodes:
        if node.body is not None:
            await validate_assignments(node.body, scope)


def execution_agent(graph: Workflow, node: Node, fallback: int) -> int:
    actor = next((actor for actor in graph.actors if actor.id == node.config.get("actor")), None)
    if actor is not None and actor.kind == "agent" and actor.agent_id is not None:
        return actor.agent_id
    return graph.execution_agent_id if graph.execution_agent_id is not None else fallback


async def human_work(scope: AgentManagementScope, *, page: int, page_size: int) -> dict[str, Any]:
    from sqlalchemy import func
    query = select(ProcessNodeAttempt, ProcessNodeRun, ProcessRun).join(ProcessNodeRun,
        ProcessNodeRun.id == ProcessNodeAttempt.node_run_id).join(ProcessRun, ProcessRun.id == ProcessNodeRun.run_id).where(
        ProcessNodeAttempt.status == "human_waiting", ProcessNodeRun.status == "waiting",
        ProcessRun.status.not_in(TERMINAL_STATUSES),
        ProcessNodeRun.context["human_user_id"].as_integer() == scope.user_id)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    rows = (await get_db().execute(query.order_by(ProcessNodeRun.started_at, ProcessNodeRun.id)
        .offset((page - 1) * page_size).limit(page_size))).all()
    from .native_engine import local_graph
    return {"items": [{"attempt_id": str(attempt.id), "run_id": str(run.id), "title": occurrence.context["human_title"],
        "instructions": str(local_graph(run, occurrence).node(occurrence.node_key).config.get("prompt", ""))
            if local_graph(run, occurrence).typed else attempt.prompt,
        "input": attempt.input,
        "inputs": [variable.model_dump(mode="json") for variable in local_graph(run, occurrence).node(occurrence.node_key).inputs or []]
            if local_graph(run, occurrence).typed else None,
        "outputs": [variable.model_dump(mode="json") for variable in local_graph(run, occurrence).node(occurrence.node_key).outputs or []]
            if local_graph(run, occurrence).typed else None,
        "data_uri": f"galaris://processes/runs/{run.id}/data",
        "attachments_uri": f"galaris://processes/runs/{run.id}/attachments/"}
        for attempt, occurrence, run in rows], "total": total or 0, "page": page, "page_size": page_size}


async def complete_human_work(identity: UUID, scope: AgentManagementScope, output: dict[str, Any],
                              *, commit: bool = True, question_id: UUID | None = None) -> dict[str, Any]:
    # Lock in the same order as the scheduler: run, then effect. The durable
    # receipt is the admission identity; a lost reply cannot repeat completion.
    attempt = await get_db().get(ProcessNodeAttempt, identity)
    occurrence = await get_db().get(ProcessNodeRun, attempt.node_run_id) if attempt is not None else None
    if occurrence is None or occurrence.context.get("human_user_id") != scope.user_id:
        raise PermissionError("Only the assigned human may complete this activity")
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == occurrence.run_id)
        .with_for_update().execution_options(populate_existing=True))
    attempt = await get_db().scalar(select(ProcessNodeAttempt).where(ProcessNodeAttempt.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    assert run is not None and attempt is not None
    await get_db().refresh(occurrence)
    if question_id is not None:
        from .activity_controls import answer_input
        await answer_input(run, occurrence, question_id=question_id, user_id=scope.user_id, output=output)
        if commit:
            await get_db().commit()
        return {"attempt_id": str(identity), "completed": True}
    user = await get_user_record(scope.user_id)
    if user is None or not user.is_active:
        raise PermissionError("The assigned human is inactive")
    from .native_engine import local_graph
    graph = local_graph(run, occurrence)
    node = decision_activity(graph.node(occurrence.node_key))
    if graph.typed:
        from .values import normalize
        assert node.outputs is not None
        output = normalize(node.outputs, output, path=f"{node.id}.output")
    if attempt.status == "completed":
        if attempt.receipt != output:
            from app.memory import MemoryConflictError
            raise MemoryConflictError("This human activity already has a different result")
        return {"attempt_id": str(identity), "completed": True}
    if run.status in TERMINAL_STATUSES or run.engine_metadata.get("native", {}).get("cancel_requested") or attempt.status != "human_waiting":
        raise ValueError("This human activity is no longer awaiting a result")
    from .native_engine import local_graph
    node = decision_activity(local_graph(run, occurrence).node(occurrence.node_key))
    if node.kind != "human_task":
        raise PermissionError("This is not a human activity")
    attempt.receipt = output
    attempt.status = "completed"
    attempt.finished_at = datetime.now(timezone.utc)
    if commit:
        await get_db().commit()
    return {"attempt_id": str(identity), "completed": True}
