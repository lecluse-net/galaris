"""Preserve historical Mail/Calendar connections while releasing their Service definitions."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

from .models import Service
from .protocols import ProtocolConfig, with_protocol_params


def _introduces_protocols(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("services", "mail_config") or transitions.column_added("services", "calendar_config")


async def _convert_legacy_tools(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    for tool in await session.scalars(select(Service).where(Service.code.in_(("mail", "calendar")))):
        if tool.code == "mail":
            tool.mail_config = {}
            if (tool.file_share_config or {}).get("service") == "mail":
                tool.file_share_config = None
            if (tool.messenger_config or {}).get("service") == "mail":
                tool.messenger_config = None
        else:
            tool.calendar_config = {}
        tool.connection_schema = with_protocol_params(tool.connection_schema or {},
            mail=ProtocolConfig.model_validate(tool.mail_config) if tool.mail_config is not None else None,
            calendar=ProtocolConfig.model_validate(tool.calendar_config) if tool.calendar_config is not None else None)
    await session.flush()


async def _legacy_tools_converted(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    for tool in await session.scalars(select(Service).where(Service.code.in_(("mail", "calendar")))):
        if tool.code == "mail" and tool.mail_config is None:
            return False
        if tool.code == "calendar" and tool.calendar_config is None:
            return False
    return True


def register_protocol_migration(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.tools.mail_calendar_protocols",
        phase=DbAdminPhase.AFTER_EXPAND,
        checksum="preserve-legacy-tool-and-connection-identities-v1",
        predicate=_introduces_protocols,
        handler=_convert_legacy_tools,
        postcondition=_legacy_tools_converted,
        requires_schema=frozenset({"services.mail_config", "services.calendar_config"}),
    ))
