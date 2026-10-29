"""Human catalogue reads scoped by the caller's agent management authority."""

from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.orm import load_only, selectinload

from app.agent import Agent
from core.database import get_db

from . import storage
from .models import Skill
from .schemas import PersonalSkillPublic, SkillLearningPublic
from .learning_policy import is_injectable


def _public(record: Skill, owner: Agent) -> PersonalSkillPublic:
    inspection = storage.inspect(record.code, owner_agent_id=owner.id)
    return PersonalSkillPublic(
        id=record.id, code=record.code, label=record.label,
        owner_agent_id=owner.id, owner_label=f"{owner.first_name} {owner.last_name}".strip(),
        revision=record.revision,
        enabled=any(item.agent_id == owner.id and item.active is True for item in record.assignments),
        available=inspection.available, valid=inspection.valid,
        description=inspection.description, file_count=inspection.file_count,
        updated_at=record.updated_at or record.created_at,
        learning=SkillLearningPublic(
            score=record.learning_score, evidence_count=record.learning_evidence_count,
            qualified=is_injectable(record), last_evidence_at=record.learning_last_evidence_at,
        ) if record.learning_key is not None or record.learning_last_evidence_at is not None else None,
    )


async def list_page(
    *, agent_ids: Collection[int] | None, owner_agent_id: int | None = None,
    search: str = "", page: int = 1, page_size: int = 50,
) -> tuple[list[PersonalSkillPublic], int]:
    query = select(Skill, Agent).join(Agent, Agent.id == Skill.owner_agent_id)
    if agent_ids is not None:
        query = query.where(Skill.owner_agent_id.in_(agent_ids))
    if owner_agent_id is not None:
        query = query.where(Skill.owner_agent_id == owner_agent_id)
    if search.strip():
        term = search.strip().lower()
        query = query.where(
            func.strpos(func.lower(Skill.code + " " + Skill.label), term) > 0,
        )
    total = int(await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0)
    records = (await get_db().execute(
        query.options(selectinload(Skill.assignments), load_only(
            Agent.id, Agent.first_name, Agent.last_name,
        )).order_by(Skill.label, Skill.id).offset((page - 1) * page_size).limit(page_size)
    )).all()
    return [_public(record, owner) for record, owner in records], total


async def get_record(
    skill_id: int, *, agent_ids: Collection[int] | None, lock: bool = False,
) -> tuple[Skill, PersonalSkillPublic]:
    query = (select(Skill, Agent).join(Agent, Agent.id == Skill.owner_agent_id)
             .where(Skill.id == skill_id).options(selectinload(Skill.assignments), load_only(
                 Agent.id, Agent.first_name, Agent.last_name,
             )))
    if agent_ids is not None:
        query = query.where(Skill.owner_agent_id.in_(agent_ids))
    if lock:
        query = query.with_for_update(of=Skill).execution_options(populate_existing=True)
    result = (await get_db().execute(query)).one_or_none()
    if result is None:
        raise FileNotFoundError("Skill not found")
    record, owner = result
    return record, _public(record, owner)
