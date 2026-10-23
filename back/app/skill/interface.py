"""Shared package policy for agent Skills and File Share operations.

Callers supply the authenticated agent identity, never a scope from tool input.
Delegation is read from server-owned policy on every call. This module does not
register an MCP tool or a route; legacy code-only consumers remain generic-only.
"""

from dataclasses import replace
from typing import Literal
from uuid import UUID
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload, raiseload
from loguru import logger

from app.agent import Agent
from core.database import get_db
from core.util import complete_io

from . import skill_service, storage
from .contracts import (
    SKILLS_TOOL_CODE,
    SKILL_CATALOGUE_LOCK,
    SkillPackageCreate,
    SkillPackageRef,
    SkillRevisionConflict,
    SkillScope,
)
from .models import AgentSkill, Skill, SkillOwnershipRelease


MAX_PERSONAL_PACKAGES = 100
MAX_PERSONAL_TOTAL_SIZE = 200 * 1024 * 1024


async def lock_catalogue() -> None:
    """Serialize publication, import and rescan across workers and filesystem effects."""
    await get_db().execute(select(func.pg_advisory_xact_lock(SKILL_CATALOGUE_LOCK)))


def _reference(record: Skill) -> SkillPackageRef:
    return SkillPackageRef(
        id=record.id, code=record.code, owner_agent_id=record.owner_agent_id,
        revision=record.revision,
    )


async def get_agent_scope(actor_agent_id: int) -> SkillScope:
    """Fail closed without delegation or a currently active Skills connection.

    Ordinary usage remains independent of management delegation. Only the protected
    local connection parameter carries this policy. Unknown values are errors.
    """
    from app.connection.facade import get_management_scope
    return SkillScope(await get_management_scope(actor_agent_id, SKILLS_TOOL_CODE))


async def _actor(actor_agent_id: int, *, lock: bool = False) -> None:
    query = select(Agent.id).where(Agent.id == actor_agent_id)
    if lock:
        query = query.with_for_update()
    if await get_db().scalar(query) is None:
        raise PermissionError("An active calling agent is required")


async def manageable_agents(actor_agent_id: int, scope: SkillScope | None = None) -> frozenset[int] | None:
    scope = scope or await get_agent_scope(actor_agent_id)
    if scope == SkillScope.ALL:
        return None
    if scope == SkillScope.TEAM:
        from app.agent.facade import team_agent_ids
        return await team_agent_ids(actor_agent_id)
    return frozenset({actor_agent_id})


async def require_agent_administration(actor_agent_id: int, target_agent_id: int) -> None:
    await _actor(actor_agent_id)
    scope = await get_agent_scope(actor_agent_id)
    allowed = await manageable_agents(actor_agent_id, scope)
    if scope not in (SkillScope.TEAM, SkillScope.ALL) or (allowed is not None and target_agent_id not in allowed):
        raise PermissionError("The agent is outside the Skills administration scope")


async def _package(skill_id: int, *, lock: bool = False) -> Skill:
    query = (select(Skill).where(Skill.id == skill_id)
             .options(selectinload(Skill.assignments) if lock else raiseload(Skill.assignments))
             .execution_options(populate_existing=True))
    if lock:
        query = query.with_for_update()
    record = await get_db().scalar(query)
    if record is None:
        raise FileNotFoundError("Skill not found")
    return record


async def _authorize(
    record: Skill, actor_agent_id: int, *, write: bool = False, administration: bool = False,
) -> None:
    await _actor(actor_agent_id)
    scope = await get_agent_scope(actor_agent_id)
    own = record.owner_agent_id == actor_agent_id
    if record.owner_agent_id is not None and not own:
        allowed = await manageable_agents(actor_agent_id, scope)
        if scope not in (SkillScope.TEAM, SkillScope.ALL) or not administration or (allowed is not None and record.owner_agent_id not in allowed):
            raise FileNotFoundError("Skill not found")
    if administration and scope not in (SkillScope.TEAM, SkillScope.ALL):
        raise PermissionError("Skills administration is required")
    if write:
        if record.system:
            raise PermissionError("System skill packages are read-only")
        if scope != SkillScope.ALL and not (own and scope in (SkillScope.PERSONAL, SkillScope.TEAM)) and not (
            record.owner_agent_id is not None and scope == SkillScope.TEAM and administration):
            raise PermissionError("Skills management scope is required")
    elif not administration:
        if own:
            if scope == SkillScope.USAGE and not await get_db().scalar(select(AgentSkill.agent_id).where(
                AgentSkill.skill_id == record.id, AgentSkill.agent_id == actor_agent_id, AgentSkill.active.is_(True))):
                raise FileNotFoundError("Skill not found")
        elif record.code not in await skill_service.get_assigned_codes(actor_agent_id):
            raise FileNotFoundError("Skill not found")


async def _list_package_records(
    *, actor_agent_id: int, administration: bool = False,
    offset: int = 0, limit: int = 50, include_unavailable: bool = False,
    kind: Literal["generic", "personal"] | None = None, owner_agent_id: int | None = None,
    target_agent_id: int | None = None,
    code: str | None = None,
) -> list[Skill]:
    await _actor(actor_agent_id)
    scope = await get_agent_scope(actor_agent_id)
    if administration and scope not in (SkillScope.TEAM, SkillScope.ALL):
        raise PermissionError("Skills administration is required")
    if include_unavailable and scope == SkillScope.USAGE:
        raise PermissionError("Skills management scope is required")
    if offset < 0 or not 1 <= limit <= 501:
        raise ValueError("Invalid Skills pagination")
    if target_agent_id is not None and not administration:
        raise PermissionError("A target agent requires global administration")
    allowed = await manageable_agents(actor_agent_id, scope) if administration else None
    if target_agent_id is not None and allowed is not None and target_agent_id not in allowed:
        raise FileNotFoundError("Agent not found in the Skills administration scope")
    if administration and target_agent_id is None:
        query = select(Skill)
        if allowed is not None:
            query = query.where(Skill.owner_agent_id.is_(None) | Skill.owner_agent_id.in_(allowed))
    else:
        target = target_agent_id if target_agent_id is not None else actor_agent_id
        await _actor(target)
        codes = await skill_service.get_assigned_codes(target)
        query = select(Skill).outerjoin(
            AgentSkill,
            (AgentSkill.skill_id == Skill.id) & (AgentSkill.agent_id == target),
        ).where(
            (Skill.owner_agent_id.is_(None) & (True if administration and include_unavailable else Skill.code.in_(codes)))
            | ((Skill.owner_agent_id == target) & (True if include_unavailable else AgentSkill.active.is_(True)))
        )
    if kind is not None:
        query = query.where(Skill.owner_agent_id.is_(None) if kind == "generic" else Skill.owner_agent_id.is_not(None))
    if owner_agent_id is not None:
        query = query.where(Skill.owner_agent_id == owner_agent_id)
    if code is not None:
        query = query.where(Skill.code == storage.validate_code(code))
    records = (await get_db().scalars(
        query.options(raiseload(Skill.assignments)).order_by(Skill.id).offset(offset).limit(limit)
        .execution_options(populate_existing=True)
    )).all()
    return [
        record for record in records
        if administration or include_unavailable or storage.inspect(record.code, owner_agent_id=record.owner_agent_id).valid
    ]


async def list_packages(
    *, actor_agent_id: int, administration: bool = False,
    offset: int = 0, limit: int = 50, include_unavailable: bool = False,
    kind: Literal["generic", "personal"] | None = None, owner_agent_id: int | None = None,
    target_agent_id: int | None = None,
) -> list[SkillPackageRef]:
    return [_reference(record) for record in await _list_package_records(
        actor_agent_id=actor_agent_id, administration=administration, offset=offset, limit=limit,
        include_unavailable=include_unavailable, kind=kind, owner_agent_id=owner_agent_id,
        target_agent_id=target_agent_id)]


def _summary(record: Skill) -> dict[str, object]:
    inspected = storage.inspect(record.code, owner_agent_id=record.owner_agent_id)
    return {**_reference(record).model_dump(mode="json"), "label": record.label,
            "description": inspected.description, "available": inspected.available,
            "valid": inspected.valid, "file_count": inspected.file_count,
            "system": record.system, "total_size": inspected.total_size,
            "modified_at": (record.updated_at or record.created_at).isoformat()}


async def list_package_summaries(
    *, actor_agent_id: int, administration: bool = False,
    offset: int = 0, limit: int = 50, include_unavailable: bool = False,
    kind: Literal["generic", "personal"] | None = None,
    target_agent_id: int | None = None, code: str | None = None,
) -> list[dict[str, object]]:
    """Batch catalogue metadata without fetching agent/category matrices."""
    return [_summary(record) for record in await _list_package_records(
        actor_agent_id=actor_agent_id, administration=administration, offset=offset, limit=limit,
        include_unavailable=include_unavailable, kind=kind, target_agent_id=target_agent_id, code=code)]


async def read_package_file(
    skill_id: int, path: str, *, actor_agent_id: int, administration: bool = False,
) -> storage.SkillFileData:
    record = await _package(skill_id)
    await _authorize(record, actor_agent_id, administration=administration)
    return replace(storage.read_file(record.code, path, owner_agent_id=record.owner_agent_id), revision=record.revision)


async def create_package(
    data: SkillPackageCreate, *, actor_agent_id: int, generic: bool = False,
) -> SkillPackageRef:
    storage.metadata_from_markdown(data.markdown, expected_code=data.code)
    if len(data.markdown.encode("utf-8")) > storage.MAX_UPLOAD_SIZE:
        raise ValueError("SKILL.md exceeds the file size limit")
    if generic:
        await lock_catalogue()
    # Serialize quota checks and same-owner creations across workers.
    await _actor(actor_agent_id, lock=True)
    if await get_agent_scope(actor_agent_id) not in (SkillScope.PERSONAL, SkillScope.TEAM, SkillScope.ALL):
        raise PermissionError("Personal Skills management is required")
    if generic and await get_agent_scope(actor_agent_id) != SkillScope.ALL:
        raise PermissionError("Global Skills administration is required")
    if generic and data.code == "personnal":
        raise ValueError("The generic skill code personnal is reserved")
    owner = None if generic else actor_agent_id
    db = get_db()
    records = (await db.scalars(select(Skill).where(
        Skill.owner_agent_id == owner,
    ))).all()
    if any(record.code == data.code for record in records):
        raise FileExistsError("Personal skill already exists")
    if not generic and len(records) >= MAX_PERSONAL_PACKAGES:
        raise ValueError("Personal skill package budget exceeded")
    size = sum(storage.inspect(item.code, owner_agent_id=owner).total_size for item in records) if not generic else 0
    if not generic and size + len(data.markdown.encode("utf-8")) > MAX_PERSONAL_TOTAL_SIZE:
        raise ValueError("Personal skill storage budget exceeded")
    record = Skill(
        code=data.code, label=data.label, owner_agent_id=owner,
        creator_agent_id=actor_agent_id, assignments=[],
    )
    installed = False
    created_id: int | None = None
    try:
        db.add(record)
        await db.flush()
        created_id = record.id
        if owner is not None:
            record.assignments.append(AgentSkill(agent_id=owner, active=True))
        else:
            await skill_service.ensure_assignment_matrix(skill_id=record.id)
        await storage.install_markdown(
            data.code, data.label, data.markdown, owner_agent_id=owner,
        )
        installed = True
        await db.commit()
    except BaseException as primary:
        try:
            await db.rollback()
            persisted = await db.scalar(select(Skill.id).where(Skill.id == created_id)) if created_id else None
            if installed and persisted is None:
                quarantined = storage.quarantine(data.code, owner_agent_id=owner)
                storage.purge_quarantine(quarantined)
        except Exception as cleanup:
            primary.add_note(f"Personal skill recovery pending: {type(cleanup).__name__}")
            logger.exception("Personal skill creation recovery pending: actor_agent_id={}", actor_agent_id)
        raise
    await db.refresh(record, attribute_names=["assignments"])
    return _reference(record)


async def set_package_enabled(
    skill_id: int, enabled: bool, *, actor_agent_id: int, expected_revision: int,
    administration: bool = False,
) -> SkillPackageRef:
    record = await _package(skill_id, lock=True)
    await _authorize(record, actor_agent_id, write=True, administration=administration)
    if record.owner_agent_id is None:
        raise ValueError("Generic skills use the authorization cascade")
    if record.revision != expected_revision:
        raise SkillRevisionConflict("Skill package revision conflict")
    assignment = next((item for item in record.assignments
                       if item.agent_id == record.owner_agent_id), None)
    if assignment is None:
        record.assignments.append(AgentSkill(agent_id=record.owner_agent_id, active=enabled))
    else:
        assignment.active = enabled
    record.revision += 1
    await get_db().commit()
    return _reference(record)


async def resolve_package(
    code: str, *, actor_agent_id: int, owner_agent_id: int | None = None,
    write: bool = False, administration: bool = False,
) -> SkillPackageRef:
    normalized = storage.validate_code(code)
    record = await get_db().scalar(select(Skill).where(
        Skill.code == normalized, Skill.owner_agent_id == owner_agent_id,
    ).options(raiseload(Skill.assignments)).execution_options(populate_existing=True))
    if record is None:
        raise FileNotFoundError("Skill not found")
    await _authorize(record, actor_agent_id, write=write, administration=administration)
    return _reference(record)


async def describe_package(skill_id: int, *, actor_agent_id: int, administration: bool = False) -> dict[str, object]:
    record = await _package(skill_id)
    await _authorize(record, actor_agent_id, administration=administration)
    return _summary(record)


async def require_global_administration(actor_agent_id: int) -> None:
    await _actor(actor_agent_id)
    if await get_agent_scope(actor_agent_id) != SkillScope.ALL:
        raise PermissionError("Global Skills administration is required")


async def package_files(
    skill_id: int, *, actor_agent_id: int, administration: bool = False,
) -> list[storage.StoredSkillFile]:
    record = await _package(skill_id)
    await _authorize(record, actor_agent_id, administration=administration)
    return storage.list_files(record.code, owner_agent_id=record.owner_agent_id)


async def personal_packages(agent_id: int) -> list[SkillPackageRef]:
    """Usable personal identities for every Harness, independent of delegation."""
    if await get_db().scalar(select(Agent.id).where(Agent.id == agent_id)) is None:
        return []
    records = (await get_db().scalars(select(Skill).join(AgentSkill).where(
        Skill.owner_agent_id == agent_id, AgentSkill.agent_id == agent_id,
        AgentSkill.active.is_(True),
    ).order_by(Skill.id))).all()
    return [_reference(record) for record in records]


async def personal_owners(actor_agent_id: int, offset: int, limit: int) -> list[int]:
    await _actor(actor_agent_id)
    scope = await get_agent_scope(actor_agent_id)
    if scope not in (SkillScope.TEAM, SkillScope.ALL):
        return [actor_agent_id] if offset == 0 else []
    query = select(Skill.owner_agent_id).join(Agent, Agent.id == Skill.owner_agent_id).where(Skill.owner_agent_id.is_not(None))
    allowed = await manageable_agents(actor_agent_id, scope)
    if allowed is not None:
        query = query.where(Skill.owner_agent_id.in_(allowed))
    owners = await get_db().scalars(query.distinct().order_by(Skill.owner_agent_id).offset(offset).limit(limit))
    return [owner for owner in owners if owner is not None]


async def _mutation_record(skill_id: int, actor_agent_id: int, administration: bool) -> Skill:
    record = await _package(skill_id)
    if record.owner_agent_id is not None:
        # The owner lock serializes the cumulative budget across packages/workers.
        await get_db().scalar(select(Agent.id).where(Agent.id == record.owner_agent_id)
                              .with_for_update().execution_options(include_historized=True))
    record = await _package(skill_id, lock=True)
    await _authorize(record, actor_agent_id, write=True, administration=administration)
    return record


async def mutate_file(
    skill_id: int, path: str, *, actor_agent_id: int,
    operation: Literal["create", "write", "append", "delete", "move"],
    content: bytes = b"", destination: str | None = None,
    overwrite: bool = False, expected_revision: int | None = None,
    administration: bool = False,
    expected_identity: SkillPackageRef | None = None,
) -> storage.SkillFileData:
    record = await _mutation_record(skill_id, actor_agent_id, administration)
    if expected_identity is not None and (record.code, record.owner_agent_id) != (expected_identity.code, expected_identity.owner_agent_id):
        raise SkillRevisionConflict("Skill package identity changed")
    if expected_revision is not None and record.revision != expected_revision:
        raise SkillRevisionConflict("Skill package revision conflict")
    code, owner = record.code, record.owner_agent_id
    base_revision = record.revision
    paths = [path, *([destination] if destination is not None else [])]
    previous: dict[str, bytes | None] = {}
    for item in paths:
        source = storage.resolve_file(code, item, owner_agent_id=owner)
        previous[item] = source.read_bytes() if source.is_file() else None
    if owner is not None and operation in {"create", "write", "append"}:
        siblings = (await get_db().scalars(select(Skill).where(Skill.owner_agent_id == owner))).all()
        size = sum(storage.inspect(item.code, owner_agent_id=owner).total_size for item in siblings)
        added = len(content) if operation == "append" else len(content) - len(previous[path] or b"")
        if size + added > MAX_PERSONAL_TOTAL_SIZE:
            raise ValueError("Personal skill storage budget exceeded")
    try:
        if operation in {"create", "write"}:
            result = await storage.write_file(code, path, content, overwrite=operation == "write", owner_agent_id=owner)
        elif operation == "append":
            result = await storage.append_file(code, path, content.decode("utf-8"), owner_agent_id=owner)
        elif operation == "delete":
            result = await storage.delete_file(code, path, owner_agent_id=owner)
        else:
            if destination is None:
                raise ValueError("Move destination is required")
            result = await storage.move_file(code, path, destination, overwrite=overwrite, owner_agent_id=owner)
        record.revision += 1
        await get_db().commit()
    except BaseException as primary:
        try:
            await get_db().rollback()
            if owner is not None:
                await get_db().scalar(select(Agent.id).where(Agent.id == owner).with_for_update()
                                      .execution_options(include_historized=True))
            current = (await get_db().execute(select(Skill.revision, Skill.code, Skill.owner_agent_id)
                .where(Skill.id == skill_id).with_for_update().execution_options(include_historized=True))).one_or_none()
            if current == (base_revision, code, owner):
                storage.restore_files(code, previous, owner_agent_id=owner)
        except Exception as cleanup:
            primary.add_note(f"Skill file recovery pending: {type(cleanup).__name__}")
            logger.exception("Skill file recovery pending: skill_id={}", skill_id)
        raise
    logger.info("Skill package mutation: actor_agent_id={} skill_id={} operation={} revision={}",
                actor_agent_id, skill_id, operation, record.revision)
    return replace(result, revision=record.revision)


async def update_package(
    skill_id: int, label: str, *, actor_agent_id: int, expected_revision: int,
    administration: bool = False,
) -> SkillPackageRef:
    if not label.strip() or len(label) > 255:
        raise ValueError("Invalid skill label")
    record = await _mutation_record(skill_id, actor_agent_id, administration)
    if record.revision != expected_revision:
        raise SkillRevisionConflict("Skill package revision conflict")
    record.label = label.strip()
    record.revision += 1
    await get_db().commit()
    return _reference(record)


async def delete_package(
    skill_id: int, *, actor_agent_id: int, expected_revision: int,
    administration: bool = False,
) -> SkillPackageRef:
    record = await _mutation_record(skill_id, actor_agent_id, administration)
    if record.revision != expected_revision:
        raise SkillRevisionConflict("Skill package revision conflict")
    code, owner = record.code, record.owner_agent_id
    quarantined = storage.quarantine(code, owner_agent_id=owner)
    try:
        record.assignments.clear()
        record.revision += 1
        reference = _reference(record)
        record.soft_delete()
        await get_db().commit()
    except BaseException:
        storage.restore_quarantine(code, quarantined, owner_agent_id=owner)
        await get_db().rollback()
        raise
    storage.purge_quarantine(quarantined)
    return reference


async def deactivate_agent_skills(agent_id: int) -> None:
    """Part of the agent deletion transaction; restoration never reactivates."""
    await get_db().execute(update(AgentSkill).where(
        AgentSkill.skill_id.in_(select(Skill.id).where(Skill.owner_agent_id == agent_id)),
    ).values(active=False))


async def release_ownership(
    skill_id: int, *, expected_revision: int, operation_id: UUID,
    actor_agent_id: int | None = None, actor_user_id: int | None = None,
    new_code: str | None = None,
) -> dict[str, object]:
    """Explicit global conversion; replay returns its receipt without changing grants."""
    if (actor_agent_id is None) == (actor_user_id is None):
        raise PermissionError("Exactly one authenticated release actor is required")
    if actor_agent_id is not None:
        await require_global_administration(actor_agent_id)
    db = get_db()
    await lock_catalogue()
    receipt = await db.get(SkillOwnershipRelease, operation_id)
    if receipt is not None:
        if (receipt.skill_id != skill_id or receipt.actor_agent_id != actor_agent_id
                or receipt.actor_user_id != actor_user_id or receipt.expected_revision != expected_revision
                or receipt.requested_code != new_code):
            raise SkillRevisionConflict("Ownership release operation ID was already used differently")
        cleanup_pending = False
        try:
            released = await db.scalar(select(Skill).where(Skill.id == skill_id)
                                       .execution_options(include_historized=True, populate_existing=True))
            await complete_io(storage.recover_ownership_release, str(operation_id), committed=True,
                              deleted=released is not None and released.is_historized)
        except Exception:
            cleanup_pending = True
            logger.exception("Ownership release cleanup pending: operation_id={}", operation_id)
        return {"operation_id": str(operation_id), "skill_id": skill_id, "code": receipt.target_code,
            "uri": f"galaris://skill/{receipt.target_code}/", "revision": receipt.result_revision,
            "cleanup_pending": cleanup_pending}
    record = await _package(skill_id)
    if record.owner_agent_id is not None:
        await db.scalar(select(Agent.id).where(Agent.id == record.owner_agent_id)
                        .with_for_update().execution_options(include_historized=True))
    record = await _package(skill_id, lock=True)
    if await db.get(SkillOwnershipRelease, operation_id) is not None:
        return await release_ownership(skill_id, expected_revision=expected_revision, operation_id=operation_id,
            actor_agent_id=actor_agent_id, actor_user_id=actor_user_id, new_code=new_code)
    if actor_agent_id is not None:
        await _authorize(record, actor_agent_id, write=True, administration=True)
    if record.owner_agent_id is None or record.system:
        raise ValueError("Only a personal user skill can release ownership")
    if record.revision != expected_revision:
        raise SkillRevisionConflict("Skill package revision conflict")
    owner, code = record.owner_agent_id, record.code
    target = storage.validate_code(new_code or code)
    if target == "personnal" or storage.is_system_code(target):
        raise ValueError("Reserved generic skill code")
    if await db.scalar(select(Skill.id).where(Skill.owner_agent_id.is_(None), Skill.code == target)
                       .execution_options(include_historized=True)) is not None:
        raise FileExistsError("Generic skill code already exists; choose another code")
    try:
        await complete_io(storage.prune_incomplete_ownership_staging)
        await complete_io(storage.recover_ownership_release, str(operation_id), committed=False)
        await complete_io(storage.prepare_ownership_release, str(operation_id), skill_id, owner, code, target)
        record.assignments.clear()
        record.owner_agent_id = None
        record.code = target
        record.category_id = None
        record.global_enabled = False
        record.revision += 1
        db.add(SkillOwnershipRelease(id=operation_id, skill_id=skill_id, actor_agent_id=actor_agent_id,
            actor_user_id=actor_user_id, owner_agent_id=owner, source_code=code, target_code=target,
            requested_code=new_code,
            expected_revision=expected_revision, result_revision=record.revision))
        await db.flush()
        await skill_service.ensure_assignment_matrix(skill_id=skill_id)
        revision = record.revision
        await db.commit()
        await db.refresh(record, attribute_names=["assignments"])
    except BaseException as primary:
        try:
            await db.rollback()
            await lock_catalogue()
            actual = (await db.execute(select(Skill.owner_agent_id, Skill.code).where(Skill.id == skill_id)
                                       .execution_options(include_historized=True))).one_or_none()
            if actual is None:
                raise RuntimeError("Ownership release outcome is unknown; originals retained")
            if actual == (owner, code):
                await complete_io(storage.recover_ownership_release, str(operation_id), committed=False)
            elif actual == (None, target):
                await complete_io(storage.recover_ownership_release, str(operation_id), committed=True)
            else:
                raise RuntimeError("Ownership release has a conflicting outcome; originals retained")
        except Exception as cleanup:
            primary.add_note(f"Ownership release recovery pending: {type(cleanup).__name__}")
            logger.exception("Ownership release recovery pending: operation_id={}", operation_id)
        raise
    cleanup_pending = False
    try:
        await lock_catalogue()
        await complete_io(storage.recover_ownership_release, str(operation_id), committed=True)
    except Exception:
        cleanup_pending = True
        logger.exception("Ownership release cleanup pending: operation_id={}", operation_id)
    return {"operation_id": str(operation_id), "skill_id": skill_id, "code": target,
        "uri": f"galaris://skill/{target}/", "revision": revision, "cleanup_pending": cleanup_pending}
