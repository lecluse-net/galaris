"""Explicit synthetic protocol providers for tests; these are never application seeds."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.models import Service
from app.services.protocols import ProtocolConfig, with_protocol_params


async def protocol_tool(db: AsyncSession, protocol: str) -> Service:
    code = "synthetic-calendar-provider" if protocol == "calendar" else protocol
    tool = await db.scalar(select(Service).where(Service.code == code))
    if tool is None:
        tool = Service(code=code, label=f"Synthetic {protocol} provider",
            **{f"{protocol}_config": {}},
            connection_schema=with_protocol_params({}, mail=ProtocolConfig() if protocol == "mail" else None,
                calendar=ProtocolConfig() if protocol == "calendar" else None))
        db.add(tool)
        await db.flush()
    return tool
