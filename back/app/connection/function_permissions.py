"""Read explicit permanent function grants without discovering remote MCP servers."""

from sqlalchemy import func, or_, select

from app.agent import AgentManagementScope
from app.tools import ToolModel
from core.database import get_db

from .models import Connection, ConnectionFunctionState


async def list_permissions(scope: AgentManagementScope, *, agent_id: int | None,
                           offset: int, limit: int) -> dict[str, object]:
    query = select(ConnectionFunctionState, Connection.agent_id, ToolModel.label, Connection.active).join(
        Connection, Connection.id == ConnectionFunctionState.connection_id,
    ).join(ToolModel, ToolModel.id == Connection.tool_id).where(
        ConnectionFunctionState.capability_kind == "tool",
        or_(ConnectionFunctionState.state == "enabled",
            ConnectionFunctionState.state.is_(None) & ConnectionFunctionState.enabled.is_(True)),
    )
    if scope.agent_ids is not None:
        query = query.where(Connection.agent_id.in_(scope.agent_ids))
    if agent_id is not None:
        query = query.where(Connection.agent_id == agent_id)
    db = get_db()
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(query.order_by(Connection.agent_id, ConnectionFunctionState.id).offset(offset).limit(limit))
    return {"total": total or 0, "items": [
        {"id": str(row.id), "agent_id": owner, "tool_label": label,
         "connection_id": row.connection_id, "capability_name": row.function_name,
         "active": active, "can_revoke": True}
        for row, owner, label, active in rows
    ]}
