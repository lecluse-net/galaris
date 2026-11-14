"""Initial, administrator-overridable function defaults for the personal agenda."""

from typing import cast
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connection import ServiceFunctionState
from app.services import ServiceModel
from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminRegistry


async def _function_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    tool = await session.scalar(select(ServiceModel.id).where(ServiceModel.code == "agenda"))
    if tool is None:
        return ()
    return tuple({"service_id": tool, "function_name": name, "capability_kind": "tool", "state": "enabled", "enabled": True}
        for name in ("calendar_create_event", "calendar_update_event", "calendar_delete_event", "calendar_action_set"))


def datasets() -> tuple[DbAdminDataset, ...]:
    return (DbAdminDataset(key="app.calendar.personal_function_defaults", table=cast(Table, ServiceFunctionState.__table__),
        natural_key=("service_id", "capability_kind", "function_name"), rows=_function_rows, update_columns=(),
        depends_on=("app.services.mandatory.services",)),)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DbAdminDataSource(key="app.calendar", factory=datasets))
