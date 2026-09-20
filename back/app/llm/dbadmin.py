"""Programmatic DbAdmin data source for the permanent LLM profile baseline."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminDatasetResult,
    DbAdminRegistry,
)
from core.params import Param, Params, params_service

from .profile_models import LlmProfile
from .profile_service import DEFAULT_PROFILE_LABEL


async def _default_profile_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    labels = tuple((await session.scalars(select(LlmProfile.label))).all())
    if DEFAULT_PROFILE_LABEL in labels or not labels:
        return ({"label": DEFAULT_PROFILE_LABEL},)
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


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
