"""Task access for agents: ownership, delegated reads, and explicit administration."""

from sqlalchemy import or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.services.facade import AdministrationScope, administration_scope

from .models import Task


async def task_management_scope(agent_id: int) -> AdministrationScope:
    return await administration_scope(agent_id, "task")


async def agent_task_filter(agent_id: int, *, manage: bool = False, allow_delegation: bool = True) -> ColumnElement[bool]:
    """Membership alone grants no management; explicit administration is scoped."""
    scope = await task_management_scope(agent_id) if allow_delegation else AdministrationScope("personal", frozenset({agent_id}))
    if scope.is_global:
        return true()
    owners = Task.agent_id.in_((scope.agent_ids or frozenset()) | {agent_id})
    return owners if manage else or_(owners, Task.requester_agent_id == agent_id)


async def require_agent_task_access(task: Task, agent_id: int, *, manage: bool = False) -> None:
    if task.agent_id == agent_id:
        return
    if not manage and task.requester_agent_id == agent_id:
        return
    if not (await task_management_scope(agent_id)).allows(task.agent_id):
        raise PermissionError("Task not found in the current agent scope.")
