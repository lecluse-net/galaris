"""Dataset-owned Topic associations and versioned Dream sources."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.agent import AgentManagementScope
from core.database import get_db

from .access import accessible_clause
from .models import Dataset


async def assignment(identity: UUID, scope: AgentManagementScope) -> tuple[UUID | None, bool]:
    from .service import record

    dataset = await record(identity, scope)
    topic_id = dataset.topic_id
    return topic_id, dataset.metadata_.get("topic_assignment") == {
        "origin": "manual",
        "topic_id": str(topic_id),
    }


async def change_assignment(
    identity: UUID,
    scope: AgentManagementScope,
    *,
    topic_id: UUID,
    expected_topic_id: UUID | None,
    expected_lock_version: int,
) -> int:
    from .service import record
    from .contracts import DatasetConflictError

    dataset = await record(identity, scope, write=True, lock=True)
    if dataset.lock_version != expected_lock_version or dataset.topic_id != expected_topic_id:
        raise DatasetConflictError("Dataset changed; reload and retry")
    dataset.topic_id = topic_id
    dataset.metadata_ = {
        **dataset.metadata_,
        "topic_assignment": {"origin": "manual", "topic_id": str(topic_id)},
    }
    dataset.lock_version += 1
    await get_db().flush()
    return dataset.lock_version


def _identity() -> ColumnElement[str]:
    return func.concat(
        Dataset.id,
        ":",
        Dataset.lock_version,
        ":",
        func.coalesce(Dataset.updated_at, Dataset.created_at),
    )


def _pending(handled: Select[tuple[str]]) -> Select[tuple[str]]:
    return select(_identity()).where(
        Dataset.topic_id.is_(None), Dataset.deleted_at.is_(None), ~_identity().in_(handled)
    )


async def count_pending(handled: Select[tuple[str]]) -> int:
    return int(
        await get_db().scalar(select(func.count()).select_from(_pending(handled).subquery())) or 0
    )


async def claim_one(handled: Select[tuple[str]]) -> str | None:
    return await get_db().scalar(
        _pending(handled)
        .order_by(Dataset.created_at, Dataset.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def source(identity: str) -> tuple[str, int | None, str | None] | None:
    row = (
        await get_db().execute(
            select(
                Dataset.title,
                func.left(Dataset.content, 18_000),
                Dataset.owner_agent_id,
                Dataset.metadata_,
            ).where(
                _identity() == identity, Dataset.topic_id.is_(None), Dataset.deleted_at.is_(None)
            )
        )
    ).one_or_none()
    if row is None:
        return None
    title, content, agent_id, metadata = row
    return (
        f"Dataset: {title}\n\nJSON data (possibly truncated):\n{content}",
        agent_id,
        metadata.get("language"),
    )


async def assign(identity: str, topic_id: UUID) -> bool:
    assigned = await get_db().scalar(
        update(Dataset)
        .where(
            _identity() == identity,
            Dataset.topic_id.is_(None),
            Dataset.deleted_at.is_(None),
        )
        .values(topic_id=topic_id)
        .returning(Dataset.id)
    )
    return assigned is not None


async def is_current(identity: str) -> bool:
    return (
        await get_db().scalar(
            select(Dataset.id).where(
                _identity() == identity,
                Dataset.topic_id.is_(None),
                Dataset.deleted_at.is_(None),
            )
        )
        is not None
    )


async def list_related(
    topic_ids: set[UUID],
    *,
    scope: AgentManagementScope | None = None,
    agent_ids: Collection[int] | None = None,
) -> list[tuple[UUID, UUID, str]]:
    if not topic_ids:
        return []
    query = select(Dataset.topic_id, Dataset.id, Dataset.title).where(
        Dataset.topic_id.in_(topic_ids), Dataset.deleted_at.is_(None)
    )
    if scope is not None:
        query = query.where(accessible_clause(scope))
    elif agent_ids is not None:
        query = query.where(Dataset.owner_agent_id.in_(agent_ids))
    rows = await get_db().execute(query.order_by(Dataset.title, Dataset.id))
    return [
        (topic_id, identity, title) for topic_id, identity, title in rows if topic_id is not None
    ]


async def reassign(source_topic_id: UUID, target_topic_id: UUID | None) -> None:
    await get_db().execute(
        update(Dataset)
        .where(Dataset.topic_id == source_topic_id)
        .values(topic_id=target_topic_id)
        .execution_options(include_historized=True)
    )
