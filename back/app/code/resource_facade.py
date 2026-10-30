"""Authorized metadata projections; opening a reference never launches an IDE."""

from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from .models import CodeGrant, CodeWorkspace
from .service import info, workspace_for_agent


def _projection(workspace: CodeWorkspace) -> dict[str, object]:
    return {"id": str(workspace.id), "label": info(workspace, "read").label, "branch": workspace.branch,
            "head": workspace.head, "uri": f"galaris://code/{workspace.id}",
            "description": "Current shared Git checkout; this reference is not a historical snapshot."}


async def read_code_resource(identifier: UUID, agent_id: int) -> dict[str, object] | None:
    try:
        return _projection(await workspace_for_agent(identifier, agent_id))
    except (PermissionError, FileNotFoundError):
        return None


async def list_code_resources(agent_id: int, query: str, offset: int, limit: int) -> list[dict[str, object]]:
    records = (await get_db().scalars(select(CodeWorkspace).join(CodeGrant).where(
        CodeGrant.agent_id == agent_id, CodeWorkspace.label.ilike("%" + query.replace("%", "\\%").replace("_", "\\_") + "%")
    ).order_by(CodeWorkspace.created_at.desc(), CodeWorkspace.id).offset(max(0, offset)).limit(min(500, max(1, limit))))).all()
    return [_projection(record) for record in records]
