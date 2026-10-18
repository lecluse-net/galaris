"""Shared aggregate reads for Dispatcher and generic evaluation catalogues."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select

from core.database import get_db

from .models import LabEvaluationCase


async def load_case_counts(dataset_ids: Collection[UUID]) -> dict[UUID, tuple[int, int]]:
    """Count active cases and enabled ready cases without loading their payloads."""
    identifiers = list(set(dataset_ids))
    counts: dict[UUID, tuple[int, int]] = {}
    # Bound parameters even for catalogues larger than the asyncpg bind limit.
    for offset in range(0, len(identifiers), 500):
        rows = await get_db().execute(
            select(
                LabEvaluationCase.dataset_id,
                func.count(LabEvaluationCase.id),
                func.count(LabEvaluationCase.id).filter(
                    LabEvaluationCase.readiness == "ready",
                    LabEvaluationCase.enabled.is_(True),
                ),
            )
            .where(
                LabEvaluationCase.dataset_id.in_(identifiers[offset:offset + 500]),
                LabEvaluationCase.deleted_at.is_(None),
            )
            .group_by(LabEvaluationCase.dataset_id)
        )
        for dataset_id, total, ready in rows:
            counts[dataset_id] = (int(total), int(ready))
    return counts
