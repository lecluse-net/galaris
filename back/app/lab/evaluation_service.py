"""Task selection and configuration services for the AI analysis Lab."""

from __future__ import annotations

from app.llm import model_usages

from collections.abc import Collection
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import String, cast as sa_cast, exists, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.llm import llm_service
from app.task import Task
from core.database import get_db
from core.i18n import tr

from .models import LabTask
from .schemas import LabConfig, LabLlmOption, LabTaskReference, LabTaskSummary


def task_summary(task: Task) -> LabTaskSummary:
    """Expose current task facts without persisting a Lab-owned snapshot."""

    agent = task.agent
    return LabTaskSummary(
        task_id=task.id,
        revision=int(task.revision or 1),
        label=task.label,
        objective=task.objective,
        status=task.status.value,
        paused=bool(task.paused),
        effort=task.effort,
        forced_route=task.forced_route,
        forced_effort=task.forced_effort,
        feedback=task.feedback,
        last_error=task.last_error,
        cost=float(task.cost or 0.0),
        attempt_count=int(task.attempt_count or 0),
        agent_id=task.agent_id,
        agent_name=(
            f"{agent.first_name} {agent.last_name}".strip()
            if agent is not None
            else None
        ),
        agent_code=agent.code if agent is not None else None,
        driver=agent.agent_driver if agent is not None else None,
        created_at=cast(datetime | None, task.created_at),
        updated_at=task.updated_at,
    )


async def get_task(
    task_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> Task | None:
    query = (
        select(Task)
        .options(selectinload(Task.agent))
        .where(Task.id == task_id)
    )
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    return await get_db().scalar(Task.histo_filter(query))


async def list_candidates(
    *,
    limit: int = 50,
    search: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> list[LabTaskSummary]:
    """Return recent canonical tasks that are not already referenced by the Lab."""

    query = select(Task).options(selectinload(Task.agent)).where(
        ~exists(select(LabTask.task_id).where(LabTask.task_id == Task.id))
    )
    normalized = (search or "").strip()
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    if normalized:
        pattern = f"%{normalized}%"
        query = query.where(
            or_(
                Task.label.ilike(pattern),
                Task.objective.ilike(pattern),
                sa_cast(Task.id, String).ilike(pattern),
            )
        )
    query = query.order_by(Task.updated_at.desc(), Task.id.desc()).limit(limit)
    rows = (await get_db().scalars(Task.histo_filter(query))).all()
    return [task_summary(task) for task in rows]


async def list_tasks(
    *, agent_ids: Collection[int] | None = None
) -> list[LabTaskReference]:
    """List Lab references enriched with the latest canonical task values."""

    db = get_db()
    task_ids = list((await db.scalars(select(LabTask.task_id))).all())
    if not task_ids:
        return []
    query = (
        select(Task)
        .options(selectinload(Task.agent))
        .where(Task.id.in_(task_ids))
    )
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    rows = list((await db.scalars(Task.histo_filter(query))).all())
    tasks = {task.id: task for task in rows}

    def sort_key(task_id: UUID) -> float:
        task = tasks.get(task_id)
        value = (task.updated_at or task.created_at) if task is not None else None
        return value.timestamp() if value is not None else 0.0

    return [
        LabTaskReference(
            task_id=task_id,
            task=task_summary(tasks[task_id]) if task_id in tasks else None,
        )
        for task_id in sorted(task_ids, key=sort_key, reverse=True)
    ]


async def add_task(
    task_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> LabTaskReference:
    """Idempotently retain only the canonical task UUID."""

    task = await get_task(task_id, agent_ids=agent_ids)
    if task is None:
        raise LookupError(await tr("evaluation_api.errors.task_not_found"))
    db = get_db()
    await db.execute(
        pg_insert(LabTask)
        .values(task_id=task_id)
        .on_conflict_do_nothing(index_elements=[LabTask.task_id])
    )
    await db.commit()
    return LabTaskReference(task_id=task_id, task=task_summary(task))


async def remove_task(
    task_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> bool:
    db = get_db()
    if await get_task(task_id, agent_ids=agent_ids) is None:
        return False
    row = await db.get(LabTask, task_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def is_registered(task_id: UUID) -> bool:
    return await get_db().get(LabTask, task_id) is not None


async def config() -> LabConfig:
    llms = await llm_service.list_llms(capability="chat")
    lab_llm = await llm_service.get_profile_llm(model_usages.LAB)
    decision_llms = await llm_service.list_llms(capability="decision")
    dispatcher_llm = (await llm_service.get_profile_llm(model_usages.DECISION)
                      or await llm_service.get_profile_llm(model_usages.DISPATCHER))
    return LabConfig(
        lab_llm_id=lab_llm.id if lab_llm is not None else None,
        dispatcher_llm_id=dispatcher_llm.id if dispatcher_llm is not None else None,
        decision_llms=[LabLlmOption(id=llm.id, code=llm.code, label=llm.label, model=llm.llm_name)
                       for llm in decision_llms],
        llms=[
            LabLlmOption(
                id=llm.id,
                code=llm.code,
                label=llm.label,
                model=llm.llm_name,
            )
            for llm in llms
        ],
    )
