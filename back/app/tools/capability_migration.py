"""Populate capability selections without rewriting connections or protocol settings."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from .capabilities import capabilities_from_values, configuration_values
from .models import Tool


def _introduces_selections(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("tools", "capabilities")


async def _populate_selections(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    for tool in await session.scalars(select(Tool)):
        tool.capabilities = capabilities_from_values(configuration_values(tool))
    await session.flush()


async def _selections_populated(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return all(tool.capabilities == capabilities_from_values(configuration_values(tool))
        for tool in await session.scalars(select(Tool)))


def register_capability_migration(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.tools.capability_selections", phase=DbAdminPhase.AFTER_DATASET,
        checksum="protocol-dot-capability-from-existing-settings-v1",
        predicate=_introduces_selections, handler=_populate_selections,
        postcondition=_selections_populated, requires_schema=frozenset({"tools.capabilities"}),
    ))
