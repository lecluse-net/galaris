"""Programmatic datasets compiled from bundled and installed skill sources."""

from __future__ import annotations

from typing import cast

from loguru import logger
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent, list_driver_specs
from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminRegistry

from . import storage
from .models import AgentSkill, Skill, SkillCategory


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
    for definition in storage.SYSTEM_SKILLS:
        if not storage.inspect(definition.code).valid:
            invalid.append(definition.code)
        system_rows.append(
            {
                "code": definition.code,
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
        if not storage.inspect(code).valid:
            invalid.append(code)
        installed_rows.append({"code": code, "label": code, "system": False})
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
    skill_ids = tuple(int(value) for value in (await session.scalars(select(Skill.id))).all())
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
        {"code": definition.code, "category_id": category_id}
        for definition in storage.SYSTEM_SKILLS
        if definition.code == "galaris" or definition.code.startswith("galaris-")
    )


def datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="app.skill.system",
            table=cast(Table, Skill.__table__),
            natural_key=("code",),
            rows=_system_skill_rows,
            # global_enabled is an installation default and remains admin-owned.
            update_columns=("label", "system"),
            depends_on=("app.tools.mandatory.connections",),
        ),
        DbAdminDataset(
            key="app.skill.installed",
            table=cast(Table, Skill.__table__),
            natural_key=("code",),
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
            natural_key=("code",),
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
