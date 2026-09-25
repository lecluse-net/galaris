"""Programmatic DbAdmin data source for the permanent LLM profile baseline."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminDatasetResult,
    DbAdminRegistry,
    DbAdminAction,
    DbAdminPhase,
    SchemaTransitionSet,
)
from core.params import Param, Params, params_service

from .profile_models import LlmProfile
from .profile_service import DEFAULT_PROFILE_LABEL
from .profile_codes import profile_code


async def _default_profile_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    labels = tuple((await session.scalars(select(LlmProfile.label))).all())
    if DEFAULT_PROFILE_LABEL in labels or not labels:
        occupied = set((await session.scalars(select(LlmProfile.code))).all())
        return ({"label": DEFAULT_PROFILE_LABEL, "code": profile_code(DEFAULT_PROFILE_LABEL, occupied)},)
    # An installation already containing profiles uses its first profile as
    # baseline; do not inject an additional administrator-visible row.
    return ()


async def _current_profile_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    profile_ids = tuple(
        int(value)
        for value in (await session.scalars(select(LlmProfile.id).order_by(LlmProfile.id))).all()
    )
    if not profile_ids:
        raise RuntimeError("DbAdmin could not establish an LLM profile baseline")
    current = await session.scalar(
        select(Param.value).where(Param.name == Params.LLM_PROFILE_ID)
    )
    try:
        current_id = int(current) if current is not None else None
    except ValueError:
        current_id = None
    selected = current_id if current_id in profile_ids else profile_ids[0]
    return ({"name": Params.LLM_PROFILE_ID, "value": str(selected)},)


async def _reload_runtime_params(
    _session: AsyncSession,
    _result: DbAdminDatasetResult,
) -> None:
    await params_service.refresh()


def _datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="app.llm.default_profile",
            table=cast(Table, LlmProfile.__table__),
            natural_key=("label",),
            rows=_default_profile_rows,
            update_columns=(),
            depends_on=("core.params.declarations",),
        ),
        DbAdminDataset(
            key="app.llm.current_profile",
            table=cast(Table, Param.__table__),
            natural_key=("name",),
            rows=_current_profile_rows,
            update_columns=("value",),
            after_merge=_reload_runtime_params,
            depends_on=("app.llm.default_profile",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.llm", factory=_datasets)


def _needs_profile_codes(transitions: SchemaTransitionSet) -> bool:
    return any(item.key == "llm_profiles.code" for item in transitions.required_columns)


async def _backfill_profile_codes(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    table = cast(Table, LlmProfile.__table__)
    occupied = set((await session.scalars(select(LlmProfile.code).where(LlmProfile.code.is_not(None)))).all())
    rows = (await session.execute(
        select(LlmProfile.id, LlmProfile.label).where(LlmProfile.code.is_(None)).order_by(LlmProfile.id)
    )).all()
    for row in rows:
        code = profile_code(row.label, occupied)
        await session.execute(update(table).where(table.c.id == row.id).values(code=code))
        occupied.add(code)


async def _profile_codes_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return not await session.scalar(
        select(func.count()).select_from(LlmProfile).where(LlmProfile.code.is_(None))
    )


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
    registry.register_action(DbAdminAction(
        key="app.llm.profile_codes", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="ascii-stable-codes-v1", predicate=_needs_profile_codes,
        handler=_backfill_profile_codes, postcondition=_profile_codes_complete,
    ))
