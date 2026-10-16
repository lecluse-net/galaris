"""Task-scoped receipts and human questions for native AI activities."""

from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.task import task_service
from app.task.facade import request_task_input, answer_task_input, consume_task_input
from core.database import get_db
from core.user import get_user_record

from .bpmn import Node, decision_activity
from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from .native_engine import local_graph
from .native_actors import execution_agent
from .process_service import TERMINAL_STATUSES
from .values import Variable, external_outputs, normalize, validate_declarations


async def owned_activity(task_id: UUID | None, agent_id: int) -> tuple[ProcessRun, ProcessNodeRun, ProcessNodeAttempt, Node]:
    if task_id is None:
        raise PermissionError("This action requires a native activity Task")
    row = (await get_db().execute(select(ProcessNodeRun.run_id, ProcessNodeAttempt.id)
        .join(ProcessNodeAttempt, ProcessNodeAttempt.node_run_id == ProcessNodeRun.id)
        .where(ProcessNodeAttempt.task_id == task_id))).one_or_none()
    if row is None:
        raise PermissionError("This Task does not belong to a native activity")
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == row.run_id)
        .with_for_update().execution_options(populate_existing=True))
    attempt = await get_db().get(ProcessNodeAttempt, row.id, populate_existing=True)
    assert run is not None and attempt is not None
    occurrence = await get_db().get(ProcessNodeRun, attempt.node_run_id, populate_existing=True)
    assert occurrence is not None
    graph = local_graph(run, occurrence)
    node = decision_activity(graph.node(occurrence.node_key))
    task = await task_service.get_by_id(task_id)
    if (task is None or task.agent_id != agent_id or not graph.typed or node.kind != "task"
            or execution_agent(graph, node, run.launcher_agent_id) != agent_id):
        raise PermissionError("Only the assigned activity Task may use this action")
    if (run.status in TERMINAL_STATUSES or run.engine_metadata.get("native", {}).get("cancel_requested")
            or task_service.has_terminal_outcome(task) or task_service.is_held_by_user(task)
            or attempt.status != "accepted"):
        raise ValueError("This activity is no longer accepting Task actions")
    return run, occurrence, attempt, node


async def submit_result(task_id: UUID | None, agent_id: int, output: dict[str, Any], message: str) -> dict[str, Any]:
    _, occurrence, _, node = await owned_activity(task_id, agent_id)
    if occurrence.context.get("activity_question", {}).get("status") == "pending":
        raise ValueError("Wait for the human answer before completing this activity")
    assert node.outputs is not None
    result = external_outputs(node.outputs, output, path=f"{node.id}.output")
    receipt = {"output": result, "message": message}
    previous = occurrence.context.get("activity_result")
    if previous is not None and previous != receipt:
        raise ValueError("This activity already has a different result")
    occurrence.context = {**occurrence.context, "activity_result": receipt}
    question = occurrence.context.get("activity_question", {})
    if question.get("status") == "answered":
        assert task_id is not None
        await consume_task_input(task_id=task_id, agent_id=agent_id, request_key=question["id"])
    await get_db().commit()
    return {"accepted": True}


async def ask_input(task_id: UUID | None, agent_id: int, question: str,
                    variables: list[Variable] | None, *, question_key: str | None = None) -> dict[str, Any]:
    run, occurrence, _, node = await owned_activity(task_id, agent_id)
    assert task_id is not None
    if occurrence.context.get("activity_result") is not None:
        raise ValueError("The activity already submitted its result")
    question = question.strip()
    if not question or len(question) > 12_000:
        raise ValueError("Provide a nonempty question of at most 12000 characters")
    if question_key is not None and (not question_key.strip() or len(question_key) > 128):
        raise ValueError("Provide a nonempty question_key of at most 128 characters")
    declarations = variables if variables is not None else node.outputs or []
    validate_declarations(declarations, path="question.variables")
    if not declarations:
        raise ValueError("Declare the variables expected from the human answer")
    outputs = [item.model_dump(mode="json") for item in declarations]
    previous = occurrence.context.get("activity_question", {})
    history: list[dict[str, Any]] = occurrence.context.get("activity_question_history", [])
    requested = {item["name"]: item for item in outputs}
    for stored in [previous, *reversed(history)]:
        same_variables = {item["name"]: item for item in stored.get("outputs", [])} == requested
        same_request = question_key is None or stored.get("key") == question_key
        if question_key is not None and same_request and not same_variables:
            raise ValueError("This question_key already identifies different variables")
        if stored.get("status") == "answered" and same_request and same_variables:
            # A retry must keep its receipt even after later questions have opened.
            return {"answered": True, "question": stored["question"], "response": stored["response"],
                "instruction": "Use this received answer to continue the activity, then call process_activity_complete."}
    same_variables = {item["name"]: item for item in previous.get("outputs", [])} == {item["name"]: item for item in outputs}
    same_request = question_key is None or previous.get("key") == question_key
    if previous.get("status") == "pending":
        if not same_variables or not same_request:
            raise ValueError("This activity already has a pending human question")
        return {"waiting_for_human": True}
    if previous.get("status") == "answered":
        history = [*history, previous]
        if len(json.dumps(history, ensure_ascii=False).encode("utf-8")) > 2_000_000:
            raise ValueError("Activity question history exceeds its 2 MB limit")
    from .human_directory import process_requester
    user_id = run.requester_user_id or await process_requester(run.id, run.launcher_agent_id)
    user = await get_user_record(user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise ValueError("This process has no active authenticated human requester")
    identity = uuid4()
    pending = {"id": str(identity), "question": question, "outputs": outputs,
        "user_id": user_id, "status": "pending", **({"key": question_key} if question_key is not None else {})}
    occurrence.context = {**occurrence.context, "activity_question": pending,
        "activity_question_history": history,
        "human_user_id": user_id, "human_title": node.title or node.id,
        "human_request_sent": None, "human_request_retry_at": None, "human_request_closed": None}
    await request_task_input(task_id=task_id, agent_id=agent_id, request_key=str(identity))
    # The domain request and its execution suspension are one durable transaction.
    await get_db().commit()
    return {"waiting_for_human": True, "instruction": "Stop this turn. Resume only after the human reply."}


async def answer_input(run: ProcessRun, occurrence: ProcessNodeRun, *, question_id: UUID,
                       user_id: int, output: dict[str, Any]) -> None:
    pending: dict[str, Any] = occurrence.context.get("activity_question", {})
    if pending.get("id") != str(question_id):
        history: list[dict[str, Any]] = occurrence.context.get("activity_question_history", [])
        pending = next((item for item in history if item.get("id") == str(question_id)), dict[str, Any]())
    if pending.get("id") != str(question_id) or pending.get("user_id") != user_id:
        raise PermissionError("This reply does not match the current human question")
    user = await get_user_record(user_id)
    if user is None or not user.is_active:
        raise PermissionError("The human requester is inactive")
    declarations = [Variable.model_validate(item) for item in pending["outputs"]]
    result = normalize(declarations, output, path="question.output")
    if pending["status"] == "answered":
        if pending["response"] != result:
            raise ValueError("This question already has a different answer")
        return
    if run.status in TERMINAL_STATUSES or run.engine_metadata.get("native", {}).get("cancel_requested"):
        raise ValueError("This process is no longer awaiting human input")
    graph = local_graph(run, occurrence)
    agent_id = execution_agent(graph, decision_activity(graph.node(occurrence.node_key)), run.launcher_agent_id)
    attempt = await get_db().scalar(select(ProcessNodeAttempt).where(
        ProcessNodeAttempt.node_run_id == occurrence.id, ProcessNodeAttempt.status == "accepted"))
    if attempt is None or attempt.task_id is None:
        raise ValueError("This activity no longer has an active execution")
    if pending.get("wait_task_id"):
        from app.task.facade import replace_legacy_input_wait
        await replace_legacy_input_wait(task_id=attempt.task_id, agent_id=agent_id,
            request_key=str(question_id), wait_task_id=UUID(pending["wait_task_id"]))
        pending = {key: value for key, value in pending.items() if key != "wait_task_id"}
    await answer_task_input(task_id=attempt.task_id, agent_id=agent_id,
        request_key=str(question_id), response=json.dumps({"question_id": str(question_id),
            "question": pending["question"], "response": result}, ensure_ascii=False))
    occurrence.context = {**occurrence.context, "activity_question": {**pending,
        "status": "answered", "response": result, "answered_at": datetime.now(timezone.utc).isoformat()}}
