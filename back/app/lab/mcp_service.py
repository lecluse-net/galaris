"""Shared Lab queries and commands used by the agent transport."""

from copy import deepcopy
import json
from math import isfinite
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, select

from app.tools import McpToolContext
from core.database import get_db

from . import mechanism_evaluation_service as evaluations
from . import comparison_service
from .contracts import LabInput
from .mechanism_rubrics import MechanismRubric
from .mcp_schemas import CasePatch, DatasetPatch, Page
from .models import (
    LabAgentReview,
    LabEvaluationCase,
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabJudgmentCampaign,
    LabJudgmentResult,
)
from .schemas import (
    EvaluationCaseRead,
    EvaluationDatasetUpdate,
    EvaluationMechanism,
    EvaluationRunCaseRead,
    EvaluationRunRead,
    HumanReviewCreate,
    JudgmentCampaignRead,
    JudgmentResultRead,
    MechanismCaseUpdate,
)


def dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def summary(value: dict[str, Any], pagination: Page) -> dict[str, Any]:
    if not pagination.summary_only:
        return value
    keys = {
        "id",
        "revision",
        "name",
        "result_id",
        "campaign_id",
        "agent_id",
        "author_kind",
        "status",
        "readiness",
        "enabled",
        "score_percent",
        "verdict",
        "repetition",
        "created_at",
    }
    return {key: item for key, item in value.items() if key in keys}


async def page(query: Select[Any], schema: type[BaseModel], pagination: Page) -> dict[str, Any]:
    rows = (
        await get_db().scalars(query.offset(pagination.offset).limit(pagination.limit + 1))
    ).all()
    return {
        "items": [
            summary(dump(schema.model_validate(row)), pagination)
            for row in rows[: pagination.limit]
        ],
        "next_offset": pagination.offset + pagination.limit
        if len(rows) > pagination.limit
        else None,
    }


async def dataset(
    mechanism: EvaluationMechanism, identifier: UUID, revision: int | None = None
) -> LabEvaluationDataset:
    query = select(LabEvaluationDataset).where(
        LabEvaluationDataset.id == identifier, LabEvaluationDataset.mechanism == mechanism
    )
    if revision is not None:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await get_db().scalar(query)
    if row is None:
        raise LookupError("Lab dataset not found.")
    if revision is not None and row.revision != revision:
        raise evaluations.RevisionConflictError("Dataset revision changed; read it again.")
    return row


async def case(
    mechanism: EvaluationMechanism, identifier: UUID, revision: int | None = None
) -> LabEvaluationCase:
    query = (
        select(LabEvaluationCase)
        .join(LabEvaluationDataset)
        .where(LabEvaluationCase.id == identifier, LabEvaluationDataset.mechanism == mechanism)
    )
    if revision is not None:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await get_db().scalar(query)
    if row is None:
        raise LookupError("Lab case not found.")
    if revision is not None and row.revision != revision:
        raise evaluations.RevisionConflictError("Case revision changed; read it again.")
    return row


async def run(mechanism: EvaluationMechanism, identifier: UUID) -> LabEvaluationRun:
    row = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset)
        .where(LabEvaluationRun.id == identifier, LabEvaluationDataset.mechanism == mechanism)
    )
    if row is None:
        raise LookupError("Lab run not found.")
    return row


async def run_actor(
    ctx: McpToolContext, mechanism: EvaluationMechanism, result: BaseModel, action: str
) -> dict[str, Any]:
    payload = dump(result)
    row = await run(mechanism, UUID(payload["id"]))
    row.requester_agent_id, row.requester_task_id, row.requester_action = (
        ctx.agent_id,
        ctx.task_id,
        action,
    )
    await get_db().flush()
    return dump(EvaluationRunRead.model_validate(row))


async def campaign(mechanism: EvaluationMechanism, identifier: UUID) -> LabJudgmentCampaign:
    row = await get_db().get(LabJudgmentCampaign, identifier)
    if row is None:
        raise LookupError("Lab campaign not found.")
    await run(mechanism, row.run_id)
    return row


async def datasets(mechanism: EvaluationMechanism, pagination: Page) -> dict[str, Any]:
    rows = (
        await get_db().scalars(
            select(LabEvaluationDataset)
            .where(LabEvaluationDataset.mechanism == mechanism)
            .order_by(LabEvaluationDataset.created_at, LabEvaluationDataset.id)
            .offset(pagination.offset)
            .limit(pagination.limit + 1)
        )
    ).all()
    return {
        "items": [
            summary(dump(await evaluations.dataset_read(row)), pagination)
            for row in rows[: pagination.limit]
        ],
        "next_offset": pagination.offset + pagination.limit
        if len(rows) > pagination.limit
        else None,
    }


async def update_dataset(
    mechanism: EvaluationMechanism, identifier: UUID, data: DatasetPatch
) -> dict[str, Any]:
    row = await dataset(mechanism, identifier, data.revision)
    previous = dump(await evaluations.dataset_read(row))
    values = {
        key: previous[key]
        for key in (
            "revision",
            "name",
            "description",
            "purpose",
            "parameters",
            "configuration",
            "prompt_suffix",
        )
    }
    values.update(data.model_dump(exclude_unset=True))
    return dump(
        await evaluations.update_dataset(
            mechanism, identifier, EvaluationDatasetUpdate.model_validate(values)
        )
    )


async def clone_dataset(
    mechanism: EvaluationMechanism, identifier: UUID, revision: int, name: str
) -> dict[str, Any]:
    source = await dataset(mechanism, identifier, revision)
    from .schemas import MechanismDatasetCreate

    data = MechanismDatasetCreate(name=name, description=source.description, purpose=source.purpose)
    target = await evaluations.prepare_dataset(mechanism, data)
    target.parameters = deepcopy(source.parameters)
    target.configuration = deepcopy((await evaluations.dataset_read(source)).configuration)
    target.prompt_suffix = source.prompt_suffix
    get_db().add(target)
    await get_db().flush()
    rows = (
        await get_db().scalars(
            select(LabEvaluationCase)
            .where(LabEvaluationCase.dataset_id == identifier)
            .order_by(LabEvaluationCase.created_at, LabEvaluationCase.id)
            .with_for_update()
        )
    ).all()
    for row in rows:
        get_db().add(
            LabEvaluationCase(
                dataset_id=target.id,
                derived_from_case_id=row.id,
                name=row.name,
                enabled=row.enabled,
                readiness=row.readiness,
                categories=deepcopy(row.categories),
                input_data=deepcopy(row.input_data),
                expected_output=deepcopy(row.expected_output),
                reference=deepcopy(row.reference),
                source_capture=deepcopy(row.source_capture),
                source_task_id=row.source_task_id,
                source_task_revision=row.source_task_revision,
            )
        )
    await get_db().flush()
    return dump(await evaluations.dataset_read(target))


async def update_case(
    mechanism: EvaluationMechanism, identifier: UUID, data: CasePatch
) -> dict[str, Any]:
    row = await case(mechanism, identifier, data.revision)
    fields = data.model_fields_set
    if data.readiness == "ready" or {"input_data", "expected_output"} & fields:
        await evaluations.update_case(
            mechanism,
            identifier,
            MechanismCaseUpdate.model_validate(
                {
                    "revision": row.revision,
                    "name": data.name if data.name is not None else row.name,
                    "input_data": data.input_data or LabInput.model_validate(row.input_data),
                    "expected_output": data.expected_output
                    if "expected_output" in fields
                    else row.expected_output,
                    "categories": data.categories
                    if data.categories is not None
                    else row.categories,
                }
            ),
        )
    elif data.name is not None:
        if not data.name.strip():
            raise ValueError("A case name must not be blank.")
        row.name = data.name.strip()
    if data.categories is not None:
        row.categories = list(dict.fromkeys(data.categories))
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.readiness == "draft":
        row.readiness = "draft"
    await get_db().flush()
    return dump(EvaluationCaseRead.model_validate(row))


async def delete_dataset(
    mechanism: EvaluationMechanism, identifier: UUID, revision: int
) -> dict[str, Any]:
    await dataset(mechanism, identifier, revision)
    active = await get_db().scalar(
        select(LabEvaluationRun.id)
        .where(
            LabEvaluationRun.dataset_id == identifier,
            LabEvaluationRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    if active is not None:
        raise ValueError("Cancel and finish active benchmarks before deleting their dataset.")
    await evaluations.delete_dataset(mechanism, identifier)
    return {"deleted": True, "dataset_id": str(identifier)}


async def cases(
    mechanism: EvaluationMechanism, identifier: UUID, pagination: Page
) -> dict[str, Any]:
    await dataset(mechanism, identifier)
    return await page(
        select(LabEvaluationCase)
        .where(LabEvaluationCase.dataset_id == identifier)
        .order_by(LabEvaluationCase.created_at, LabEvaluationCase.id),
        EvaluationCaseRead,
        pagination,
    )


async def runs(
    mechanism: EvaluationMechanism, identifier: UUID, pagination: Page
) -> dict[str, Any]:
    await dataset(mechanism, identifier)
    return await page(
        select(LabEvaluationRun)
        .where(LabEvaluationRun.dataset_id == identifier)
        .order_by(LabEvaluationRun.created_at, LabEvaluationRun.id),
        EvaluationRunRead,
        pagination,
    )


async def results(
    mechanism: EvaluationMechanism, identifier: UUID, pagination: Page
) -> dict[str, Any]:
    await run(mechanism, identifier)
    return await page(
        select(LabEvaluationRunCase)
        .where(LabEvaluationRunCase.run_id == identifier)
        .order_by(LabEvaluationRunCase.created_at, LabEvaluationRunCase.id),
        EvaluationRunCaseRead,
        pagination,
    )


async def campaigns(
    mechanism: EvaluationMechanism, identifier: UUID, pagination: Page
) -> dict[str, Any]:
    await run(mechanism, identifier)
    return await page(
        select(LabJudgmentCampaign)
        .where(LabJudgmentCampaign.run_id == identifier)
        .order_by(LabJudgmentCampaign.sequence),
        JudgmentCampaignRead,
        pagination,
    )


async def campaign_detail(
    mechanism: EvaluationMechanism, identifier: UUID, pagination: Page
) -> dict[str, Any]:
    row = await campaign(mechanism, identifier)
    return {
        "campaign": dump(JudgmentCampaignRead.model_validate(row)),
        **await page(
            select(LabJudgmentResult)
            .where(LabJudgmentResult.campaign_id == identifier)
            .order_by(LabJudgmentResult.created_at, LabJudgmentResult.id),
            JudgmentResultRead,
            pagination,
        ),
    }


def review_payload(row: LabAgentReview) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "author_kind": "agent",
        "agent_id": row.agent_id,
        "task_uri": f"galaris://task/{row.task_id}" if row.task_id else None,
        "result_id": str(row.result_id),
        "campaign_id": str(row.campaign_id),
        "assessment": row.assessment,
        "score_percent": row.score_percent,
        "verdict": row.verdict,
    }


async def submit_review(
    ctx: McpToolContext, mechanism: EvaluationMechanism, data: HumanReviewCreate
) -> dict[str, Any]:
    judged = await campaign(mechanism, data.campaign_id)
    result = await get_db().scalar(
        select(LabEvaluationRunCase)
        .where(
            LabEvaluationRunCase.id == data.result_id, LabEvaluationRunCase.run_id == judged.run_id
        )
        .with_for_update()
    )
    if result is None or result.error or result.actual_output is None:
        raise LookupError("No candidate output to review.")
    if await get_db().scalar(
        select(LabAgentReview.id).where(
            LabAgentReview.agent_id == ctx.agent_id,
            LabAgentReview.campaign_id == data.campaign_id,
            LabAgentReview.result_id == data.result_id,
        )
    ):
        raise ValueError("This agent's assessment is immutable; it has already been submitted.")
    rubric = MechanismRubric.from_snapshot(mechanism, judged.configuration["rubric"])
    scores = {item.code: item.score_percent for item in data.dimensions}
    if (
        len(scores) != len(data.dimensions)
        or set(scores) != {dim.code for dim in rubric.dimensions}
        or not all(isfinite(v) for v in scores.values())
    ):
        raise ValueError("Provide exactly the dimensions of the frozen rubric.")
    score = sum(scores[dim.code] * dim.weight / 100 for dim in rubric.dimensions)
    critical = bool(data.critical_failures) or any(
        not check.get("passed") and check.get("critical")
        for check in result.score_details.get("checks", [])
    )
    if data.critical_failures:
        score = min(score, rubric.critical_failure_cap_percent)
    row = LabAgentReview(
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        result_id=result.id,
        campaign_id=judged.id,
        assessment=data.model_dump(mode="json", exclude={"result_id", "campaign_id"}),
        score_percent=score,
        verdict="fail"
        if critical or score < judged.configuration.get("pass_threshold", 75)
        else "pass",
    )
    get_db().add(row)
    await get_db().flush()
    return review_payload(row)


async def compare(
    mechanism: EvaluationMechanism,
    left_id: UUID,
    right_id: UUID,
    axis: Literal["model", "prompt", "parameters"],
    pagination: Page,
) -> dict[str, Any]:
    return await comparison_service.compare(
        mechanism, left_id, right_id, axis,
        offset=pagination.offset, limit=pagination.limit,
    )


async def content(
    mechanism: EvaluationMechanism,
    kind: Literal["case", "result", "run", "dataset", "campaign", "judgment", "review"],
    identifier: UUID,
    offset: int,
    length: int,
) -> dict[str, Any]:
    if offset < 0 or not 1 <= length <= 100000:
        raise ValueError("Use offset >= 0 and length between 1 and 100000 characters.")
    if kind == "case":
        value = dump(EvaluationCaseRead.model_validate(await case(mechanism, identifier)))
    elif kind == "run":
        value = dump(EvaluationRunRead.model_validate(await run(mechanism, identifier)))
    elif kind == "dataset":
        value = dump(await evaluations.dataset_read(await dataset(mechanism, identifier)))
    elif kind == "campaign":
        value = dump(JudgmentCampaignRead.model_validate(await campaign(mechanism, identifier)))
    elif kind == "judgment":
        judgment = await get_db().get(LabJudgmentResult, identifier)
        if judgment is None:
            raise LookupError("Judgment not found.")
        await campaign(mechanism, judgment.campaign_id)
        value = dump(JudgmentResultRead.model_validate(judgment))
    elif kind == "review":
        review = await get_db().get(LabAgentReview, identifier)
        if review is None:
            raise LookupError("Agent review not found.")
        await campaign(mechanism, review.campaign_id)
        value = review_payload(review)
    else:
        row = await get_db().get(LabEvaluationRunCase, identifier)
        if row is None:
            raise LookupError("Result not found.")
        await run(mechanism, row.run_id)
        value = dump(EvaluationRunCaseRead.model_validate(row))
    from .mcp_access import fingerprint

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {
        "content": serialized[offset : offset + length],
        "fingerprint": fingerprint(value),
        "offset_unit": "character",
        "total": len(serialized),
        "next_offset": offset + length if offset + length < len(serialized) else None,
    }
