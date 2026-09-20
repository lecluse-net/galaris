"""Durable history of structured task diagnoses."""

from __future__ import annotations


from typing import cast
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from core.i18n import tr

from . import evaluation_service
from .models import LabTaskDiagnosis
from .schemas import (
    AnalysisLanguage,
    EvidenceCoverage,
    TaskAnalysis,
    TaskAnalysisContent,
)


def _to_schema(row: LabTaskDiagnosis) -> TaskAnalysis:
    content = TaskAnalysisContent.model_validate(row.content)
    evidence = EvidenceCoverage.model_validate(row.evidence_coverage)
    return TaskAnalysis(
        **content.model_dump(),
        id=row.id,
        task_id=row.task_id,
        task_revision=row.task_revision,
        language=cast(AnalysisLanguage, row.language),
        prompt_version=row.prompt_version,
        evidence=evidence,
        model=row.model,
        duration=float(row.duration or 0.0),
        cost=float(row.cost or 0.0),
        created_at=row.created_at,
        created_by=row.created_by,
    )


async def create_diagnosis(
    *,
    task_id: UUID,
    task_revision: int,
    language: AnalysisLanguage,
    prompt_version: str,
    content: TaskAnalysisContent,
    evidence: EvidenceCoverage,
    model: str,
    duration: float,
    cost: float,
) -> TaskAnalysis:
    """Append one diagnosis without retaining source evidence or context separately."""

    if not await evaluation_service.is_registered(task_id):
        raise LookupError(await tr("evaluation_api.errors.lab_task_not_found"))
    row = LabTaskDiagnosis(
        task_id=task_id,
        task_revision=task_revision,
        language=language,
        prompt_version=prompt_version,
        model=model,
        verdict=content.verdict,
        confidence=content.confidence,
        content=content.model_dump(mode="json"),
        evidence_coverage=evidence.model_dump(mode="json"),
        duration=duration,
        cost=cost,
    )
    db = get_db()
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_schema(row)


async def list_diagnoses(
    task_id: UUID,
    *,
    limit: int = 50,
) -> list[TaskAnalysis]:
    """Return newest-first diagnoses for a task currently selected in the Lab."""

    if not await evaluation_service.is_registered(task_id):
        raise LookupError(await tr("evaluation_api.errors.lab_task_not_found"))
    query = (
        select(LabTaskDiagnosis)
        .where(LabTaskDiagnosis.task_id == task_id)
        .order_by(
            LabTaskDiagnosis.created_at.desc(),
            LabTaskDiagnosis.id.desc(),
        )
        .limit(limit)
    )
    rows = list(
        (await get_db().scalars(LabTaskDiagnosis.histo_filter(query))).all()
    )
    return [_to_schema(row) for row in rows]


__all__ = ["create_diagnosis", "list_diagnoses"]
