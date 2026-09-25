"""Database operations and disk reconciliation for the skill library."""

from __future__ import annotations

from collections.abc import Collection

from typing import Sequence, TypedDict

from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.agent.models import Agent
from app.agent import list_driver_specs
from core.database import get_db

from .models import AgentSkill, AgentSkillCategory, Skill, SkillCategory
from .schemas import (
    SkillAuthorization,
    SkillAuthorizationState,
    SkillCategoryAuthorizationState,
    SkillCategoryCreate,
    SkillCategoryPublic,
    SkillCategoryUpdate,
    SkillCreate,
    SkillGlobalAuthorizationState,
    SkillPublic,
    SkillUpdate,
)
from . import storage


class SkillRescanData(TypedDict):
    created: int
    restored: int
    invalid_directories: list[str]


def _skill_agent_drivers() -> tuple[str, ...]:
    """Return drivers that participate in the generic skill assignment matrix."""

    return tuple(spec.code for spec in list_driver_specs())


async def runtime_requires_skill_sync(agent_id: int) -> bool:
    """Resolve the selected provider, independently of its transport driver."""
    from app.agent import projected_skill_agent_ids

    return bool(await projected_skill_agent_ids([agent_id]))


async def get(skill_id: int) -> Skill | None:
    db = get_db()
    result = await db.execute(
        select(Skill)
        .options(
            selectinload(Skill.assignments),
            selectinload(Skill.category).selectinload(SkillCategory.authorizations),
        )
        .where(Skill.id == skill_id)
    )
    return result.scalar_one_or_none()


async def get_by_code(code: str, include_historized: bool = False) -> Skill | None:
    db = get_db()
    query = (
        select(Skill)
        .options(
            selectinload(Skill.category).selectinload(SkillCategory.authorizations),
        )
        .where(Skill.code == code)
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_all() -> Sequence[Skill]:
    db = get_db()
    result = await db.execute(
        select(Skill)
        .options(
            selectinload(Skill.assignments),
            selectinload(Skill.category).selectinload(SkillCategory.authorizations),
        )
        .order_by(Skill.label, Skill.code)
    )
    return result.scalars().all()


async def has_configured_skills() -> bool:
    """Return whether the library contains at least one active skill."""
    query = Skill.histo_filter(select(Skill.id)).limit(1)
    result = await get_db().execute(query)
    return result.scalar_one_or_none() is not None


async def ensure_assignment_matrix(
    *,
    agent_id: int | None = None,
    skill_id: int | None = None,
) -> int:
    """Add missing persisted agent-skill settings to the current transaction."""
    db = get_db()
    agent_query = select(Agent.id).where(Agent.agent_driver.in_(_skill_agent_drivers()))
    if agent_id is not None:
        agent_query = agent_query.where(Agent.id == agent_id)
    agent_ids = list((await db.execute(agent_query)).scalars().all())

    skill_query = select(Skill.id)
    if skill_id is not None:
        skill_query = skill_query.where(Skill.id == skill_id)
    skill_ids = list((await db.execute(skill_query)).scalars().all())
    if not agent_ids or not skill_ids:
        return 0

    existing_result = await db.execute(
        select(AgentSkill.agent_id, AgentSkill.skill_id).where(
            AgentSkill.agent_id.in_(agent_ids),
            AgentSkill.skill_id.in_(skill_ids),
        )
    )
    existing = set(existing_result.tuples().all())
    missing = [
        AgentSkill(agent_id=current_agent_id, skill_id=current_skill_id, active=None)
        for current_skill_id in skill_ids
        for current_agent_id in agent_ids
        if (current_agent_id, current_skill_id) not in existing
    ]
    if missing:
        db.add_all(missing)
        await db.flush()
        logger.info("Skill assignment matrix: created={} association(s)", len(missing))
    return len(missing)


def to_public(skill: Skill) -> SkillPublic:
    inspection = storage.inspect(skill.code)
    return SkillPublic(
        id=skill.id,
        code=skill.code,
        label=skill.label,
        system=skill.system,
        available=inspection.available,
        valid=inspection.valid,
        validation_error=inspection.validation_error,
        description=inspection.description,
        category_id=skill.category_id,
        category_label=skill.category.label if skill.category is not None else None,
        file_count=inspection.file_count,
        total_size=inspection.total_size,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


async def _upsert_record(code: str, label: str) -> tuple[Skill, bool]:
    db = get_db()
    record = await get_by_code(code, include_historized=True)
    created = record is None
    if record is None:
        record = Skill(code=code, label=label)
        db.add(record)
    else:
        if record.is_historized:
            record.restore()
        record.label = label
    await db.flush()
    await ensure_assignment_matrix(skill_id=record.id)
    await db.commit()
    await db.refresh(record, attribute_names=["assignments"])
    return record, created


async def create(data: SkillCreate) -> Skill:
    code = storage.validate_code(data.code)
    category = (
        await _require_category(data.category_id)
        if data.category_id is not None
        else None
    )
    existing = await get_by_code(code)
    if existing is not None:
        raise FileExistsError(f"La compétence {code} existe déjà")
    markdown = data.markdown or storage.default_markdown(code, data.label)
    await storage.install_markdown(code, data.label, markdown, overwrite=False)
    record, _ = await _upsert_record(code, data.label)
    if category is not None:
        record.category = category
        db = get_db()
        await db.commit()
        await db.refresh(record, attribute_names=["assignments", "category"])
    logger.info("Skill created: code={}", code)
    return record


async def import_upload(
    filename: str,
    content: bytes,
    code: str | None,
    label: str | None,
    overwrite: bool,
) -> tuple[Skill, bool]:
    installed = await storage.install_upload(filename, content, code, label, overwrite)
    record, created = await _upsert_record(installed.code, installed.label)
    return record, created


async def update(skill_id: int, data: SkillUpdate) -> Skill | None:
    record = await get(skill_id)
    if record is None:
        return None
    if record.system:
        raise ValueError(f"La compétence système {record.code} ne peut pas être modifiée")
    if data.markdown is not None:
        storage.write_markdown(record.code, data.markdown)
    if data.label is not None:
        record.label = data.label
    db = get_db()
    await db.commit()
    await db.refresh(record, attribute_names=["assignments"])
    logger.info("Skill updated: code={}", record.code)
    return record


async def delete_skill(skill_id: int) -> tuple[bool, list[int]]:
    record = await get(skill_id)
    if record is None:
        return False, []
    if record.system:
        raise ValueError(f"La compétence système {record.code} ne peut pas être supprimée")
    agent_ids = [agent.id for agent in await list_managed_runtime_agents()]
    quarantined = storage.quarantine(record.code)
    try:
        # Skill uses soft deletion, so the database FK cascade cannot run here.
        # Clear settings explicitly; a later restoration recreates defaults.
        record.assignments.clear()
        record.soft_delete()
        db = get_db()
        await db.commit()
    except Exception:
        storage.restore_quarantine(record.code, quarantined)
        raise
    storage.purge_quarantine(quarantined)
    logger.info("Skill deleted: code={}", record.code)
    return True, agent_ids


async def sync_from_disk() -> SkillRescanData:
    """Apply the module DataSource through the DbAdmin merge engine."""
    from core.dbadmin import reconcile_dataset
    from .dbadmin import compile_skill_rows, datasets

    db = get_db()
    results = [await reconcile_dataset(db, dataset) for dataset in datasets()]
    await db.commit()
    _system, _installed, invalid = compile_skill_rows()
    created = sum(result.inserted for result in results[:2])
    restored = sum(result.restored for result in results[:2])
    if created or restored or invalid:
        logger.info(
            "Skill directory reconciliation: created={} restored={} invalid={}",
            created,
            restored,
            invalid,
        )
    return {
        "created": created,
        "restored": restored,
        "invalid_directories": list(invalid),
    }


def _agent_skill_active(skill: Skill, agent_id: int) -> bool | None:
    assignment = next(
        (item for item in skill.assignments if item.agent_id == agent_id),
        None,
    )
    return assignment.active if assignment is not None else None


def _category_active_for_agent(skill: Skill, agent_id: int) -> bool | None:
    if skill.category is None:
        return None
    authorization = next(
        (
            item
            for item in skill.category.authorizations
            if item.agent_id == agent_id
        ),
        None,
    )
    return authorization.active if authorization is not None else None


def _configured_enabled(skill: Skill, agent_id: int) -> bool:
    agent_active = _agent_skill_active(skill, agent_id)
    if agent_active is not None:
        return agent_active
    category_active = _category_active_for_agent(skill, agent_id)
    if category_active is not None:
        return category_active
    return skill.global_enabled


def _configured_states(skill: Skill, agents: Sequence[Agent]) -> dict[int, bool]:
    return {agent.id: _configured_enabled(skill, agent.id) for agent in agents}


def _changed_agent_ids(
    old_states: dict[int, bool],
    new_states: dict[int, bool],
) -> list[int]:
    return sorted(
        agent_id
        for agent_id, old_state in old_states.items()
        if new_states[agent_id] != old_state
    )


def to_authorization(skill: Skill, agent: Agent) -> SkillAuthorization:
    inspection = storage.inspect(skill.code)
    assignment = next(
        (item for item in skill.assignments if item.agent_id == agent.id),
        None,
    )
    agent_state: SkillAuthorizationState
    category_state: SkillCategoryAuthorizationState = "default"
    inherited_enabled = skill.global_enabled
    category_active = _category_active_for_agent(skill, agent.id)
    if category_active is not None:
        category_state = "enabled" if category_active else "disabled"
        inherited_enabled = category_active
    if assignment is None or assignment.active is None:
        agent_state = "default"
        effective = inherited_enabled
    else:
        agent_state = "enabled" if assignment.active else "disabled"
        effective = assignment.active
    return SkillAuthorization(
        skill_id=skill.id,
        code=skill.code,
        label=skill.label,
        agent_id=agent.id,
        agent_code=agent.code,
        agent_label=f"{agent.first_name} {agent.last_name}".strip(),
        agent_driver=agent.agent_driver,
        description=inspection.description,
        category_id=skill.category_id,
        category_label=skill.category.label if skill.category is not None else None,
        available=inspection.available,
        valid=inspection.valid,
        global_state="enabled" if skill.global_enabled else "disabled",
        category_state=category_state,
        agent_state=agent_state,
        effective=effective and inspection.available and inspection.valid,
    )


async def list_authorizations(
    agent_id: int | None = None,
    skill_id: int | None = None,
    category_id: int | None = None,
    agent_ids: Collection[int] | None = None,
) -> list[SkillAuthorization]:
    agents = (
        [await _require_skill_agent(agent_id)]
        if agent_id is not None
        else await list_skill_agents(agent_ids=agent_ids)
    )
    if skill_id is not None:
        skill = await get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        skills: Sequence[Skill] = [skill]
    else:
        skills = await get_all()
    if category_id is not None:
        await _require_category(category_id)
        skills = [skill for skill in skills if skill.category_id == category_id]
    return [
        to_authorization(skill, agent)
        for skill in skills
        for agent in agents
    ]


async def set_global_authorization(
    skill_id: int,
    agent_id: int,
    state: SkillGlobalAuthorizationState,
) -> tuple[SkillAuthorization, list[int]]:
    agent = await _require_skill_agent(agent_id)
    record = await get(skill_id)
    if record is None:
        raise KeyError(skill_id)
    enabled = state == "enabled"
    changed = record.global_enabled != enabled
    runtime_agents = await list_managed_runtime_agents() if changed else []
    old_states = _configured_states(record, runtime_agents)
    record.global_enabled = enabled
    new_states = _configured_states(record, runtime_agents)
    db = get_db()
    await db.commit()
    await db.refresh(record, attribute_names=["assignments"])
    affected = _changed_agent_ids(old_states, new_states)
    return to_authorization(record, agent), affected


async def set_agent_authorization(
    skill_id: int,
    agent_id: int,
    state: SkillAuthorizationState,
) -> SkillAuthorization:
    agent = await _require_skill_agent(agent_id)
    record = await get(skill_id)
    if record is None:
        raise KeyError(skill_id)
    db = get_db()
    assignment = next(
        (item for item in record.assignments if item.agent_id == agent_id),
        None,
    )
    active = None if state == "default" else state == "enabled"
    if assignment is None:
        db.add(AgentSkill(agent_id=agent_id, skill_id=skill_id, active=active))
    else:
        assignment.active = active
    await db.commit()
    await db.refresh(record, attribute_names=["assignments"])
    return to_authorization(record, agent)


async def _require_skill_agent(agent_id: int) -> Agent:
    db = get_db()
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.agent_driver.in_(_skill_agent_drivers()),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent compatible avec les compétences introuvable : {agent_id}")
    return agent


async def get_assigned_codes(agent_id: int) -> list[str]:
    db = get_db()
    result = await db.execute(
        select(Skill.code)
        .outerjoin(SkillCategory, SkillCategory.id == Skill.category_id)
        .outerjoin(
            AgentSkillCategory,
            and_(
                AgentSkillCategory.category_id == SkillCategory.id,
                AgentSkillCategory.agent_id == agent_id,
            ),
        )
        .outerjoin(
            AgentSkill,
            and_(AgentSkill.skill_id == Skill.id, AgentSkill.agent_id == agent_id),
        )
        .where(
            or_(
                AgentSkill.active.is_(True),
                and_(
                    or_(AgentSkill.id.is_(None), AgentSkill.active.is_(None)),
                    or_(
                        AgentSkillCategory.active.is_(True),
                        and_(
                            or_(
                                AgentSkillCategory.id.is_(None),
                                AgentSkillCategory.active.is_(None),
                            ),
                            Skill.global_enabled.is_(True),
                        ),
                    ),
                ),
            )
        )
        .order_by(Skill.code)
    )
    codes = list(result.scalars().all())
    if "galaris-knowledge" in codes:
        from app.tools import has_documentation_access

        if not await has_documentation_access(agent_id):
            codes.remove("galaris-knowledge")
    return codes


def to_category_public(category: SkillCategory) -> SkillCategoryPublic:
    return SkillCategoryPublic(
        id=category.id,
        label=category.label,
        skill_count=len(category.skills),
    )


async def get_category(
    category_id: int,
    *,
    include_historized: bool = False,
) -> SkillCategory | None:
    db = get_db()
    query = (
        select(SkillCategory)
        .options(
            selectinload(SkillCategory.skills).selectinload(Skill.assignments),
            selectinload(SkillCategory.authorizations),
        )
        .where(SkillCategory.id == category_id)
    )
    if include_historized:
        query = query.execution_options(include_historized=True)
    return (await db.execute(query)).scalar_one_or_none()


async def get_categories() -> list[SkillCategory]:
    db = get_db()
    result = await db.execute(
        select(SkillCategory)
        .options(selectinload(SkillCategory.skills))
        .order_by(SkillCategory.label)
    )
    return list(result.scalars().all())


async def _require_category(category_id: int) -> SkillCategory:
    category = await get_category(category_id)
    if category is None:
        raise KeyError(category_id)
    return category


async def _category_with_label(
    label: str,
    *,
    include_historized: bool = False,
) -> SkillCategory | None:
    db = get_db()
    query = select(SkillCategory).where(func.lower(SkillCategory.label) == label.lower())
    if include_historized:
        query = query.execution_options(include_historized=True)
    return (await db.execute(query)).scalar_one_or_none()


async def create_category(data: SkillCategoryCreate) -> SkillCategory:
    existing = await _category_with_label(data.label, include_historized=True)
    if existing is not None and not existing.is_historized:
        raise FileExistsError(f"La catégorie {data.label} existe déjà")
    db = get_db()
    if existing is None:
        category = SkillCategory(label=data.label)
        db.add(category)
    else:
        category = existing
        category.restore()
        category.label = data.label
    await db.commit()
    await db.refresh(category, attribute_names=["skills"])
    return category


async def update_category(
    category_id: int,
    data: SkillCategoryUpdate,
) -> SkillCategory:
    category = await _require_category(category_id)
    duplicate = await _category_with_label(data.label)
    if duplicate is not None and duplicate.id != category_id:
        raise FileExistsError(f"La catégorie {data.label} existe déjà")
    category.label = data.label
    db = get_db()
    await db.commit()
    await db.refresh(category, attribute_names=["skills"])
    return category


async def set_category_authorization(
    category_id: int,
    agent_id: int,
    state: SkillCategoryAuthorizationState,
) -> tuple[SkillCategoryAuthorizationState, list[int]]:
    category = await _require_category(category_id)
    agent = await _require_skill_agent(agent_id)
    active = None if state == "default" else state == "enabled"
    old_states = {
        skill.id: _configured_enabled(skill, agent_id)
        for skill in category.skills
    }
    authorization = next(
        (item for item in category.authorizations if item.agent_id == agent_id),
        None,
    )
    if authorization is None:
        category.authorizations.append(
            AgentSkillCategory(agent_id=agent_id, active=active)
        )
    else:
        authorization.active = active
    new_states = {
        skill.id: _configured_enabled(skill, agent_id)
        for skill in category.skills
    }
    changed = old_states != new_states
    db = get_db()
    await db.commit()
    affected = (
        [agent_id]
        if changed and await runtime_requires_skill_sync(agent.id)
        else []
    )
    return state, affected


async def set_skill_category(
    skill_id: int,
    category_id: int | None,
) -> tuple[Skill, list[int]]:
    skill = await get(skill_id)
    if skill is None:
        raise KeyError(skill_id)
    category = await _require_category(category_id) if category_id is not None else None
    changed = skill.category_id != category_id
    runtime_agents = await list_managed_runtime_agents() if changed else []
    old_states = _configured_states(skill, runtime_agents)
    skill.category = category
    new_states = _configured_states(skill, runtime_agents)
    affected = _changed_agent_ids(old_states, new_states)
    db = get_db()
    await db.commit()
    await db.refresh(skill)
    await db.refresh(skill, attribute_names=["assignments", "category"])
    return skill, affected


async def delete_category(category_id: int) -> tuple[list[int], list[int]]:
    category = await _require_category(category_id)
    affected_skill_ids = [skill.id for skill in category.skills]
    affected_agents: set[int] = set()
    runtime_agents = await list_managed_runtime_agents()
    for skill in list(category.skills):
        old_states = _configured_states(skill, runtime_agents)
        skill.category = None
        new_states = _configured_states(skill, runtime_agents)
        affected_agents.update(_changed_agent_ids(old_states, new_states))
    # Categories use soft deletion, so clear scoped settings explicitly.
    category.authorizations.clear()
    category.soft_delete()
    db = get_db()
    await db.commit()
    return affected_skill_ids, sorted(affected_agents)


async def list_managed_runtime_agents() -> list[Agent]:
    from app.agent import projected_skill_agent_ids

    db = get_db()
    agent_ids = await projected_skill_agent_ids()
    if not agent_ids:
        return []
    result = await db.execute(
        select(Agent)
        .where(Agent.id.in_(agent_ids))
        .order_by(Agent.first_name, Agent.last_name)
    )
    return list(result.scalars().all())


async def list_skill_agents(
    *,
    agent_ids: Collection[int] | None = None,
) -> list[Agent]:
    db = get_db()
    query = (
        select(Agent)
        .where(Agent.agent_driver.in_(_skill_agent_drivers()))
        .order_by(Agent.first_name, Agent.last_name)
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    result = await db.execute(query)
    return list(result.scalars().all())
