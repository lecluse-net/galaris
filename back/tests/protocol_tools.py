"""Explicit synthetic protocol providers for tests; these are never application seeds."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.models import Tool
from app.tools.protocols import ProtocolConfig, with_protocol_params


async def protocol_tool(db: AsyncSession, protocol: str) -> Tool:
    tool = await db.scalar(select(Tool).where(Tool.code == protocol))
    if tool is None:
        tool = Tool(code=protocol, label=f"Synthetic {protocol} provider",
            **{f"{protocol}_config": {}},
            connection_schema=with_protocol_params({}, mail=ProtocolConfig() if protocol == "mail" else None,
                calendar=ProtocolConfig() if protocol == "calendar" else None))
        db.add(tool)
        await db.flush()
    return tool
