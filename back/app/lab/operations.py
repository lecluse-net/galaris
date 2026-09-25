"""Lab source discovery and admission of durable integrated processes."""

import json
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import exists, func, literal, or_, select, union_all
from sqlalchemy.orm import selectinload

from app.agent import Agent
from app.connection import Connection
from app.conversation import ConversationRound
from app.llm import LLMCall
from app.messenger import Message
from app.process import ProcessRun, process_service
from app.process.interface import ensure_integrated_definition
from app.task import Task
from app.tools import McpToolContext
from core.database import get_db

from . import (
    mechanism_evaluation_service as evaluations,
    dispatcher_evaluation_service as dispatcher,
)
from . import mcp_service as service, evaluation_service, diagnosis_service
from .mcp_access import authorize, fingerprint
from .mcp_schemas import Page, SourceImport
from .mechanism_registry import get_mechanism
from .models import (
    LabTask,
    LabTaskDiagnosis,
    LabAgentReview,
    LabHumanReview,
    LabEvaluationRunCase,
    LabJudgmentResult,
    LabOperationResult,
)
from .schemas import (
    EvaluationMechanism,
    DispatcherCaseImport,
    ExecutorCaseImport,
    MechanismCaseImport,
)

Operation = Literal[
    "lab_dataset_generate", "lab_expected_generate", "lab_run_analyze", "lab_task_analyze"
]


def paged(items: list[dict[str, Any]], page: Page) -> dict[str, Any]:
    return {
        "items": items[: page.limit],
        "next_offset": page.offset + page.limit if len(items) > page.limit else None,
    }


async def tasks(page: Page, search: str | None, *, registered: bool) -> dict[str, Any]:
    query = select(Task).options(selectinload(Task.agent))
    in_lab = exists(select(LabTask.task_id).where(LabTask.task_id == Task.id))
    query = query.where(in_lab if registered else ~in_lab)
    if search:
        query = query.where(
            or_(Task.label.ilike(f"%{search[:300]}%"), Task.objective.ilike(f"%{search[:300]}%"))
        )
    rows = (
        await get_db().scalars(
            query.order_by(Task.created_at, Task.id).offset(page.offset).limit(page.limit + 1)
        )
    ).all()
    return paged(
        [
            {
                **service.dump(evaluation_service.task_summary(row)),
                "task_uri": f"galaris://task/{row.id}",
            }
            for row in rows
        ],
        page,
    )


async def diagnoses(task_id: UUID, page: Page) -> dict[str, Any]:
    if await evaluation_service.get_task(task_id) is None:
        raise LookupError("Task not found.")
    rows = (
        await get_db().scalars(
            select(LabTaskDiagnosis)
            .where(LabTaskDiagnosis.task_id == task_id)
            .order_by(LabTaskDiagnosis.created_at, LabTaskDiagnosis.id)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    ).all()
    return paged([service.dump(diagnosis_service.to_schema(row)) for row in rows], page)


async def source_list(
    mechanism: EvaluationMechanism, page: Page, search: str | None
) -> dict[str, Any]:
    # Uniform SQL projection keeps pagination bounded even for mixed memory sources.
    task_query = select(
        Task.id.label("source_id"),
        literal("task").label("source_kind"),
        Task.created_at.label("created_at"),
        Task.label.label("label"),
    )
    round_query = select(
        ConversationRound.id.label("source_id"),
        literal("conversation_round").label("source_kind"),
        ConversationRound.created_at.label("created_at"),
        ConversationRound.effective_objective.label("label"),
    )
    if mechanism in {"dispatcher", "task_analysis", "task_executor"}:
        query = task_query
    elif mechanism == "conversation_executor":
        query = round_query.where(ConversationRound.voice_session_id.is_(None))
    elif mechanism == "voice_executor":
        query = select(
            ConversationRound.id.label("source_id"),
            literal("voice_turn").label("source_kind"),
            ConversationRound.created_at.label("created_at"),
            ConversationRound.effective_objective.label("label"),
        ).where(ConversationRound.voice_session_id.is_not(None))
    elif mechanism == "memory_extraction":
        query = select(
            union_all(
                task_query.where(Task.topic_id.is_not(None)),
                round_query.where(
                    ConversationRound.topic_id.is_not(None),
                    ConversationRound.contact_memory_item_id.is_not(None),
                ),
            ).subquery()
        )
    elif mechanism == "topic_classification":
        query = select(
            Message.id.label("source_id"),
            literal("messenger_message").label("source_kind"),
            Message.created_at.label("created_at"),
            Message.text.label("label"),
        ).where(func.length(func.trim(Message.text)) > 0)
    else:
        definition = get_mechanism(mechanism)
        query = select(
            LLMCall.id.label("source_id"),
            literal("llm_call").label("source_kind"),
            LLMCall.created_at.label("created_at"),
            LLMCall.prompt.label("label"),
        ).where(
            LLMCall.status.in_(["success", "completed"]),
            or_(
                *(
                    LLMCall.system_prompt.ilike(f"%{marker}%")
                    for marker in (definition.marker, *definition.marker_aliases)
                )
            ),
        )
    source = query.subquery()
    selected = select(
        source.c.source_id,
        source.c.source_kind,
        source.c.created_at,
        func.left(source.c.label, 300).label("label"),
    )
    if search:
        selected = selected.where(source.c.label.ilike(f"%{search[:300]}%"))
    rows = (
        (
            await get_db().execute(
                selected.order_by(source.c.created_at, source.c.source_id)
                .offset(page.offset)
                .limit(page.limit + 1)
            )
        )
        .mappings()
        .all()
    )
    return paged(
        [
            {**dict(row), "source_id": str(row["source_id"]), "created_at": str(row["created_at"])}
            for row in rows
        ],
        page,
    )


async def import_case(
    mechanism: EvaluationMechanism, dataset_id: UUID, data: SourceImport
) -> dict[str, Any]:
    await service.dataset(mechanism, dataset_id)
    common = {"name": data.name, "confirmation_token": data.confirmation_token}
    executor_sources = {
        "task_executor": "task",
        "conversation_executor": "conversation_round",
        "voice_executor": "voice_turn",
    }
    if mechanism in executor_sources:
        if data.source_kind != executor_sources[mechanism]:
            raise ValueError("The source type does not match this executor.")
        result = await evaluations.import_executor_case(
            mechanism, dataset_id, ExecutorCaseImport(source_id=data.source_id, **common)
        )
    elif mechanism == "dispatcher":
        if data.source_kind != "task":
            raise ValueError("Dispatcher captures require a Task source.")
        result = await dispatcher.import_task_case(
            dataset_id, DispatcherCaseImport(task_id=data.source_id, **common)
        )
    elif data.source_kind == "task" and mechanism != "memory_extraction":
        result = await evaluations.import_task_case(
            mechanism, dataset_id, DispatcherCaseImport(task_id=data.source_id, **common)
        )
    else:
        allowed = {
            "topic_classification": {"messenger_message"},
            "memory_extraction": {"task", "conversation_round"},
        }.get(mechanism, {"llm_call"})
        if data.source_kind not in allowed:
            raise ValueError("The source type does not match this mechanism.")
        result = await evaluations.import_source_case(
            mechanism,
            dataset_id,
            MechanismCaseImport(
                source_id=data.source_id, name=data.name, confirmation_token=data.confirmation_token
            ),
        )
    return service.dump(result)


async def topic_agents(page: Page) -> dict[str, Any]:
    rows = (
        await get_db().execute(
            select(
                Agent.id, Agent.first_name, Agent.last_name, func.count(Message.id).label("count")
            )
            .join(Connection, Connection.agent_id == Agent.id)
            .join(Message, Message.connection_id == Connection.id)
            .where(func.length(func.trim(Message.text)) > 0)
            .group_by(Agent.id, Agent.first_name, Agent.last_name)
            .order_by(Agent.id)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    ).all()
    return paged(
        [
            {
                "agent_id": row.id,
                "label": f"{row.first_name} {row.last_name}",
                "message_count": row.count,
            }
            for row in rows
        ],
        page,
    )


async def topic_people(agent_id: int, page: Page) -> dict[str, Any]:
    rows = (
        await get_db().execute(
            select(
                Message.connection_id,
                Message.user_id,
                Message.platform,
                func.count(Message.id).label("count"),
            )
            .join(Connection, Connection.id == Message.connection_id)
            .where(
                Connection.agent_id == agent_id,
                Message.direction == "inbound",
                Message.user_id.is_not(None),
                func.length(func.trim(Message.text)) > 0,
            )
            .group_by(Message.connection_id, Message.user_id, Message.platform)
            .order_by(Message.connection_id, Message.user_id, Message.platform)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    ).all()
    return paged(
        [
            {
                "connection_id": row.connection_id,
                "user_id": row.user_id,
                "platform": row.platform,
                "message_count": row.count,
            }
            for row in rows
        ],
        page,
    )


async def reviews(mechanism: EvaluationMechanism, campaign_id: UUID, page: Page) -> dict[str, Any]:
    await service.campaign(mechanism, campaign_id)
    agents = (
        await get_db().scalars(
            select(LabAgentReview)
            .where(LabAgentReview.campaign_id == campaign_id)
            .order_by(LabAgentReview.id)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    ).all()
    humans = (
        await get_db().scalars(
            select(LabHumanReview)
            .where(LabHumanReview.campaign_id == campaign_id)
            .order_by(LabHumanReview.id)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    ).all()
    return {
        "agents": paged([service.review_payload(row) for row in agents], page),
        "humans": paged(
            [
                {
                    "id": str(row.id),
                    "author_kind": "human",
                    "reviewer_id": row.reviewer_id,
                    "result_id": str(row.result_id),
                    "assessment": row.assessment,
                    "score_percent": row.score_percent,
                    "verdict": row.verdict,
                }
                for row in humans
            ],
            page,
        ),
    }


async def review_input(
    ctx: McpToolContext, mechanism: EvaluationMechanism, campaign_id: UUID, result_id: UUID
) -> dict[str, Any]:
    campaign = await service.campaign(mechanism, campaign_id)
    result = await get_db().get(LabEvaluationRunCase, result_id)
    if result is None or result.run_id != campaign.run_id:
        raise LookupError("Result not found in this campaign.")
    own = await get_db().scalar(
        select(LabAgentReview).where(
            LabAgentReview.agent_id == ctx.agent_id,
            LabAgentReview.campaign_id == campaign_id,
            LabAgentReview.result_id == result_id,
        )
    )
    payload = {
        "result_id": str(result.id),
        "campaign_id": str(campaign.id),
        "rubric": campaign.configuration["rubric"],
        "input": result.case_snapshot["input_data"],
        "expected": result.case_snapshot.get("expected_output"),
        "output": result.actual_output,
        "review": service.review_payload(own) if own else None,
    }
    if own:
        judgment = await get_db().scalar(
            select(LabJudgmentResult).where(
                LabJudgmentResult.campaign_id == campaign_id,
                LabJudgmentResult.result_id == result_id,
            )
        )
        payload["automatic_judgment"] = judgment.output if judgment else None
    return payload


async def start(
    ctx: McpToolContext,
    action: Operation,
    mechanism: EvaluationMechanism,
    request: dict[str, Any],
    invocation_key: str,
) -> dict[str, Any]:
    if not invocation_key.strip() or len(invocation_key) > 200:
        raise ValueError("Provide an invocation_key of 1–200 characters.")
    digest = fingerprint({"action": action, "mechanism": mechanism, "request": request})
    workflow = await ensure_integrated_definition(ctx.agent_id, "lab", action)
    # Check before resolving mutable defaults: a response-lost retry keeps its original model.
    existing = await get_db().scalar(
        select(ProcessRun).where(
            ProcessRun.launcher_agent_id == ctx.agent_id,
            ProcessRun.engine_code == "lab",
            ProcessRun.idempotency_key == f"{action}:{invocation_key}",
        )
    )
    if existing is not None:
        if existing.input.get("request_fingerprint") != digest:
            raise ValueError("The invocation_key belongs to different arguments.")
        return {"operation_id": str(existing.id), "status": existing.status}
    result = await process_service.start_process(
        agent_id=ctx.agent_id,
        workflow_id=workflow,
        input_data={
            "action": action,
            "mechanism": mechanism,
            "request": request,
            "runtime": ctx.runtime,
            "request_fingerprint": digest,
        },
        idempotency_key=f"{action}:{invocation_key}",
        task_id=ctx.task_id,
        runtime=ctx.runtime,
    )
    saved = await process_service.get_run(result.run_id)
    if saved is None or saved.input.get("request_fingerprint") != digest:
        raise ValueError("The invocation_key belongs to different arguments.")
    return {"operation_id": str(result.run_id), "status": result.status}


async def operation(ctx: McpToolContext, identifier: UUID) -> ProcessRun:
    row = await process_service.get_run(identifier)
    if row is None or row.engine_code != "lab":
        raise LookupError("Lab operation not found.")
    # Lab administrators can inspect all Lab operations; real-source results require the additional grant.
    if row.input.get("action") == "lab_task_analyze":
        await authorize(ctx, "lab_operation_get", sources=True)
    return row


async def get(ctx: McpToolContext, identifier: UUID, offset: int, length: int) -> dict[str, Any]:
    row = await operation(ctx, identifier)
    if offset < 0 or not 1 <= length <= 100000:
        raise ValueError("Use offset >= 0 and length between 1 and 100000.")
    saved = await get_db().scalar(
        select(LabOperationResult).where(LabOperationResult.process_run_id == identifier)
    )
    serialized = json.dumps(saved.payload, ensure_ascii=False, sort_keys=True) if saved else ""
    return {
        "operation_id": str(row.id),
        "status": row.status,
        "agent_id": row.launcher_agent_id,
        "action": row.input.get("action"),
        "error": row.error_message,
        "output": row.output,
        "result": saved.payload if saved and len(serialized) <= length and offset == 0 else None,
        "content": serialized[offset : offset + length],
        "total": len(serialized),
        "fingerprint": fingerprint(saved.payload) if saved else None,
        "next_offset": offset + length if offset + length < len(serialized) else None,
    }


async def cancel(ctx: McpToolContext, identifier: UUID) -> dict[str, Any]:
    await operation(ctx, identifier)
    row = await process_service.cancel_run(identifier)
    return {"operation_id": str(row.id), "status": row.status}
