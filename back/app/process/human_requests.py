"""Durable dispatch of human activities through the registered messaging port."""

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, cast, String, or_, and_
from uuid import UUID

from core.database import get_db

from .human_directory import ProcessHumanRequest, deliver_process_human_request, withdraw_process_human_request
from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from .native_engine import local_graph
from .process_service import TERMINAL_STATUSES
from .bpmn import decision_activity


async def deliver_human_requests() -> int:
    """Claim a bounded batch; retry failed deliveries without losing the human wait."""
    now = datetime.now(timezone.utc)
    rows = (await get_db().execute(select(ProcessNodeAttempt, ProcessNodeRun, ProcessRun)
        .join(ProcessNodeRun, ProcessNodeRun.id == ProcessNodeAttempt.node_run_id)
        .join(ProcessRun, ProcessRun.id == ProcessNodeRun.run_id).where(
            or_(ProcessNodeAttempt.status == "human_waiting", and_(ProcessNodeAttempt.status == "accepted",
                ProcessNodeRun.context["activity_question"]["status"].as_string() == "pending")),
            ProcessNodeRun.status == "waiting",
            ProcessRun.status.not_in(TERMINAL_STATUSES),
            ProcessRun.engine_metadata["native"]["cancel_requested"].as_boolean().is_not(True),
            ProcessNodeRun.context["human_request_sent"].as_string().is_(None),
            (ProcessNodeRun.context["human_request_retry_at"].as_string().is_(None)
                | (ProcessNodeRun.context["human_request_retry_at"].as_string() <= now.isoformat())),
        ).order_by(ProcessNodeAttempt.created_at, ProcessNodeAttempt.id)
        .with_for_update(of=ProcessNodeRun, skip_locked=True).limit(20))).all()
    requests: list[ProcessHumanRequest] = []
    for attempt, occurrence, run in rows:
        if run.engine_metadata.get("native", {}).get("cancel_requested"):
            continue
        graph = local_graph(run, occurrence)
        original = graph.node(occurrence.node_key)
        node = decision_activity(original)
        question = occurrence.context.get("activity_question", {})
        requests.append(ProcessHumanRequest(attempt_id=attempt.id, run_id=run.id,
            agent_id=run.launcher_agent_id,
            user_id=occurrence.context["human_user_id"], title=occurrence.context["human_title"],
            instructions=question["question"] if question.get("status") == "pending" else str(node.config.get("prompt", "")), input=attempt.input,
            outputs=question["outputs"] if question.get("status") == "pending" else [item.model_dump(mode="json") for item in node.outputs or []] if graph.typed else None,
            files=occurrence.context.get("input_files", []), decision=original.kind == "if" and not question,
            question_id=UUID(question["id"]) if question.get("status") == "pending" else None))
        occurrence.context = {**occurrence.context,
            "human_request_retry_at": (now + timedelta(minutes=1)).isoformat()}
    await get_db().commit()
    for request in requests:
        try:
            await deliver_process_human_request(request)
        except Exception:
            await get_db().rollback()
            logger.warning("Messaging delivery deferred for process human activity {}", request.attempt_id)
            continue
        attempt = await get_db().get(ProcessNodeAttempt, request.attempt_id)
        occurrence = await get_db().scalar(select(ProcessNodeRun).where(
            ProcessNodeRun.id == attempt.node_run_id).with_for_update()
            .execution_options(populate_existing=True)) if attempt else None
        if occurrence is not None and (request.question_id is None or
                occurrence.context.get("activity_question", {}).get("id") == str(request.question_id)):
            occurrence.context = {**occurrence.context, "human_request_sent": str(request.attempt_id)}
            await get_db().commit()
    await withdraw_finished_requests()
    return len(requests)


async def withdraw_finished_requests() -> None:
    rows = (await get_db().execute(select(ProcessNodeAttempt, ProcessNodeRun, ProcessRun)
        .join(ProcessNodeRun, ProcessNodeRun.id == ProcessNodeAttempt.node_run_id)
        .join(ProcessRun, ProcessRun.id == ProcessNodeRun.run_id).where(
            ProcessNodeRun.context["human_request_sent"].as_string() == cast(ProcessNodeAttempt.id, String),
            ProcessNodeRun.context["human_request_closed"].as_string().is_(None),
            ((ProcessNodeAttempt.status != "human_waiting") &
                (ProcessNodeRun.context["activity_question"]["status"].as_string().is_distinct_from("pending")))
                | ProcessRun.status.in_(TERMINAL_STATUSES)
                | ProcessRun.engine_metadata["native"]["cancel_requested"].as_boolean().is_(True),
        ).order_by(ProcessNodeAttempt.created_at, ProcessNodeAttempt.id).limit(20))).all()
    captured = [(attempt.id, occurrence.id,
        run.launcher_agent_id,
        UUID(occurrence.context["activity_question"]["id"]) if occurrence.context.get("activity_question") else None)
        for attempt, occurrence, run in rows]
    await get_db().commit()
    for attempt_id, occurrence_id, agent_id, question_id in captured:
        try:
            await withdraw_process_human_request(agent_id=agent_id, attempt_id=attempt_id, question_id=question_id)
            occurrence = await get_db().scalar(select(ProcessNodeRun).where(ProcessNodeRun.id == occurrence_id)
                .with_for_update().execution_options(populate_existing=True))
            # A resumed activity may have opened its next question while the old
            # messaging request was being withdrawn. Close only the captured one.
            if (occurrence is not None and occurrence.context.get("activity_question", {}).get("id")
                    == (str(question_id) if question_id is not None else None)):
                occurrence.context = {**occurrence.context, "human_request_closed": datetime.now(timezone.utc).isoformat()}
                await get_db().commit()
        except Exception:
            await get_db().rollback()
            logger.warning("Messaging withdrawal deferred for process human activity {}", attempt_id)
