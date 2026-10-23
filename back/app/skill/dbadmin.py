"""Programmatic datasets compiled from bundled and installed skill sources."""

from __future__ import annotations

from typing import cast

from loguru import logger
from sqlalchemy import Table, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent, list_driver_specs
from core.dbadmin import DbAdminAction, DbAdminPhase, SchemaTransitionSet, DbAdminDataSource, DbAdminDataset, DbAdminRegistry, DbAdminReconciler

from . import storage
from .models import AgentSkill, Skill, SkillCategory
from .contracts import SKILL_CATALOGUE_LOCK


async def _tool_renamed(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    from app.tools import ToolModel
    reserved = await session.scalar(select(Skill.id).where(Skill.owner_agent_id.is_(None), Skill.code == "personnal"))
    return reserved is None and await session.scalar(select(ToolModel.id).where(ToolModel.code == "skill_management")) is None


async def _rename_tool(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    from app.tools import ToolModel
    from app.connection import Connection, ConnectionParam
    from app.tools.contracts import MANAGEMENT_SCOPE_PARAM
    if await session.scalar(select(Skill.id).where(Skill.owner_agent_id.is_(None), Skill.code == "personnal")) is not None:
        raise RuntimeError("Historical generic skill 'personnal' must be renamed explicitly before reserving that URI branch; its files and record are preserved")
    legacy = await session.scalar(select(ToolModel).where(ToolModel.code == "skill_management").with_for_update())
    if legacy is None:
        return
    if await session.scalar(select(ToolModel.id).where(ToolModel.code == "skills")) is not None:
        raise RuntimeError("Conflicting Skills Tool identities; migration requires review")
    for connection_id in await session.scalars(select(Connection.id).where(
        Connection.tool_id == legacy.id, Connection.active.is_(True),
    )):
        if await session.scalar(select(ConnectionParam.id).where(
            ConnectionParam.connection_id == connection_id, ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM)) is None:
            session.add(ConnectionParam(connection_id=connection_id, param_name=MANAGEMENT_SCOPE_PARAM, param_value="all"))
    # Keep the PK: connections, function settings and approval references survive.
    legacy.code = "skills"
    await session.flush()


async def _recover_releases(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(SKILL_CATALOGUE_LOCK)))
    storage.prune_incomplete_ownership_staging()
    for state in storage.pending_ownership_releases():
        record = await session.scalar(select(Skill).where(Skill.id == int(str(state["skill_id"]))).with_for_update()
                                      .execution_options(include_historized=True, populate_existing=True))
        if record is None:
            raise RuntimeError("Ownership release recovery cannot find its package")
        committed = record.owner_agent_id is None and record.code == state["target_code"]
        if not committed and record.owner_agent_id != int(str(state["owner"])):
            raise RuntimeError("Ownership release recovery found conflicting ownership")
        storage.recover_ownership_release(str(state["operation"]), committed=committed, deleted=record.is_historized)


def compile_skill_rows() -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    """Compile every filesystem source without touching the database."""

    system_rows: list[dict[str, object]] = []
    installed_rows: list[dict[str, object]] = []
    invalid: list[str] = []
    root = storage.ensure_root()
    pending_codes = {str(item["target_code"]) for item in storage.pending_ownership_releases()}
    for definition in storage.SYSTEM_SKILLS:
        if not storage.inspect(definition.code).valid:
            invalid.append(definition.code)
        system_rows.append(
            {
                "code": definition.code,
                "owner_agent_id": None,
                "label": definition.label,
                "system": True,
                "global_enabled": definition.default_enabled,
            }
        )
    for directory in sorted(root.iterdir()):
        if directory.name.startswith(".") or not directory.is_dir() or directory.is_symlink():
            continue
        try:
            code = storage.validate_code(directory.name)
        except ValueError:
            invalid.append(directory.name)
            continue
        if storage.is_system_code(code):
            continue
        if code in pending_codes:
            continue
        if code == "personnal":
            raise RuntimeError("Legacy generic skill 'personnal' conflicts with the reserved URI branch; preserve and rename it explicitly")
        if not storage.inspect(code).valid:
            invalid.append(code)
        installed_rows.append({"code": code, "owner_agent_id": None, "label": code, "system": False})
    if invalid:
        logger.warning("DbAdmin found invalid skill directories: {}", invalid)
    return tuple(system_rows), tuple(installed_rows), tuple(invalid)


async def _system_skill_rows(
    _session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    rows, _installed, _invalid = compile_skill_rows()
    return rows


async def _installed_skill_rows(
    _session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    await _session.execute(select(func.pg_advisory_xact_lock(SKILL_CATALOGUE_LOCK)))
    _system, rows, _invalid = compile_skill_rows()
    return rows


async def _assignment_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    driver_codes = tuple(spec.code for spec in list_driver_specs())
    agent_ids = tuple(
        int(value)
        for value in (
            await session.scalars(
                select(Agent.id).where(Agent.agent_driver.in_(driver_codes))
            )
        ).all()
    )
    skill_ids = tuple(int(value) for value in (await session.scalars(
        select(Skill.id).where(Skill.owner_agent_id.is_(None))
    )).all())
    return tuple(
        {"agent_id": agent_id, "skill_id": skill_id, "active": None}
        for skill_id in skill_ids
        for agent_id in agent_ids
    )


async def _galaris_category_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    category_id = await session.scalar(
        select(SkillCategory.id).where(SkillCategory.label == "Galaris")
    )
    if category_id is None:
        raise RuntimeError("DbAdmin could not resolve the Galaris skill category")
    return tuple(
        {"code": definition.code, "owner_agent_id": None, "category_id": category_id}
        for definition in storage.SYSTEM_SKILLS
        if definition.code == "galaris" or definition.code.startswith("galaris-")
    )


def datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="app.skill.system",
            table=cast(Table, Skill.__table__),
            natural_key=("owner_agent_id", "code"),
            rows=_system_skill_rows,
            # global_enabled is an installation default and remains admin-owned.
            update_columns=("label", "system"),
            depends_on=("app.tools.mandatory.connections",),
        ),
        DbAdminDataset(
            key="app.skill.installed",
            table=cast(Table, Skill.__table__),
            natural_key=("owner_agent_id", "code"),
            rows=_installed_skill_rows,
            # User labels and activation policy remain untouched.
            update_columns=(),
            depends_on=("app.skill.system",),
        ),
        DbAdminDataset(
            key="app.skill.galaris_category",
            table=cast(Table, SkillCategory.__table__),
            natural_key=("label",),
            rows=({"label": "Galaris"},),
            update_columns=(),
            depends_on=("app.skill.installed",),
        ),
        DbAdminDataset(
            key="app.skill.galaris_category_assignments",
            table=cast(Table, Skill.__table__),
            natural_key=("owner_agent_id", "code"),
            rows=_galaris_category_rows,
            update_columns=("category_id",),
            # Fill missing defaults while preserving administrator classifications.
            update_only_null=True,
            depends_on=("app.skill.galaris_category",),
        ),
        DbAdminDataset(
            key="app.skill.assignments",
            table=cast(Table, AgentSkill.__table__),
            natural_key=("agent_id", "skill_id"),
            rows=_assignment_rows,
            update_columns=(),
            depends_on=("app.skill.galaris_category_assignments",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.skill", factory=datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
    registry.register_action(DbAdminAction(
        key="app.skill.rename_tool", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="same-tool-id-explicit-legacy-active-all-v1",
        predicate=lambda _delta: True, handler=_rename_tool, postcondition=_tool_renamed,
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.skill.ownership_recovery", handler=_recover_releases,
        depends_on=("app.skill.assignments",),
    ))
