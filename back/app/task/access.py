"""Task access for agents: ownership, delegated reads, and explicit administration."""

from sqlalchemy import or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.tools import has_galaris_admin_access

from .models import Task


async def agent_task_filter(agent_id: int, *, manage: bool = False) -> ColumnElement[bool]:
    """Team membership never grants task management; requesters can follow their delegation."""
    if await has_galaris_admin_access(agent_id):
        return true()
    owner = Task.agent_id == agent_id
    return owner if manage else or_(owner, Task.requester_agent_id == agent_id)


async def require_agent_task_access(task: Task, agent_id: int, *, manage: bool = False) -> None:
    if task.agent_id == agent_id:
        return
    if not manage and task.requester_agent_id == agent_id:
        return
    if not await has_galaris_admin_access(agent_id):
        raise PermissionError("Task not found in the current agent scope.")
