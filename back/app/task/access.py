"""Task access for agents: ownership, delegated reads, and explicit administration."""

from sqlalchemy import or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.tools import has_galaris_admin_access

from .models import Task


async def agent_task_filter(agent_id: int, *, manage: bool = False) -> ColumnElement[bool]:
    """Membership alone grants no management; explicit administration is scoped."""
    from app.tools.facade import administration_scope
    scope = await administration_scope(agent_id, "galaris_admin")
    administrative = true() if scope.is_global else Task.agent_id.in_(scope.agent_ids or ())
    owner = Task.agent_id == agent_id
    return or_(administrative, owner) if manage else or_(administrative, owner, Task.requester_agent_id == agent_id)


async def require_agent_task_access(task: Task, agent_id: int, *, manage: bool = False) -> None:
    if task.agent_id == agent_id:
        return
    if not manage and task.requester_agent_id == agent_id:
        return
    if not await has_galaris_admin_access(agent_id, target_agent_id=task.agent_id):
        raise PermissionError("Task not found in the current agent scope.")
