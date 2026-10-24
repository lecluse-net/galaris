"""Durable peer communication using the existing delegated Task lifecycle."""

from uuid import UUID
from collections.abc import Sequence
from typing import Any
from sqlalchemy import Select, or_, select

from app.agent import get_agent_record
from core.i18n import render_prompt, t
from core.util import convert_to_html
from core.database import get_db
from .work_projection import (
    TaskWorkSnapshot as TaskWorkSnapshot,
    list_work_snapshots as list_work_snapshots,
)
from .input_requests import (
    request_task_input as request_task_input,
    answer_task_input as answer_task_input,
    consume_task_input as consume_task_input,
    replace_legacy_input_wait as replace_legacy_input_wait,
)


async def memory_scope_for_task(
    task_id: UUID, *, agent_id: int
) -> tuple[UUID | None, UUID | None] | None:
    """Read only the context of a Task owned by the requesting agent."""
    from .models import Task

    row = (
        await get_db().execute(
            select(Task.topic_id, Task.contact_memory_item_id).where(
                Task.id == task_id,
                Task.agent_id == agent_id,
            )
        )
    ).one_or_none()
    return (row.topic_id, row.contact_memory_item_id) if row is not None else None


def memory_capture_blocked_tasks() -> Select[tuple[UUID]]:
    """A refusal survives archiving and propagates through either lineage edge."""
    from .models import Task

    roots = Task.__table__.alias("memory_capture_root")
    descendants = Task.__table__.alias("memory_capture_descendant")
    blocked = select(roots.c.id).where(roots.c.data["memory_capture"].as_boolean().is_(False)).cte(
        "memory_capture_blocked", recursive=True, nesting=True,
    )
    blocked = blocked.union(select(descendants.c.id).join(blocked, or_(
        descendants.c.parent_id == blocked.c.id, descendants.c.source_task_id == blocked.c.id,
    )))
    return select(blocked.c.id)


def memory_evidence_task_tree(root_ids: Select[tuple[UUID]]) -> Select[tuple[UUID]]:
    """Query live descendants without widening an evidence consumer's agent ACL.

    Nest the CTE inside the consuming subquery: roots can be correlated to a
    conversation round. Distinct UNION terminates even with historical cycles.
    """
    from .models import Task

    blocked = memory_capture_blocked_tasks()
    tree = select(Task.id).where(Task.id.in_(root_ids), Task.deleted_at.is_(None),
        Task.id.not_in(blocked)).cte(
        "memory_evidence_task_tree", recursive=True, nesting=True,
    )
    tree = tree.union(select(Task.id).join(tree, or_(Task.parent_id == tree.c.id,
        Task.source_task_id == tree.c.id)).where(Task.deleted_at.is_(None),
            Task.id.not_in(blocked)))
    return select(tree.c.id)


async def inspect_workflow_tasks(identities: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    """Read bounded Task states after the owning workflow has authorized its run."""
    from .models import Task
    from .operational_state import operational_snapshot

    if len(identities) > 500:
        raise ValueError("Inspect at most 500 workflow Tasks at once")
    if not identities:
        return {}
    tasks = list(await get_db().scalars(select(Task).where(Task.id.in_(identities))))
    children = list(await get_db().scalars(select(Task).where(Task.parent_id.in_(identities))))
    grouped: dict[UUID, list[Task]] = {}
    for child in children:
        if child.parent_id is not None:
            grouped.setdefault(child.parent_id, []).append(child)
    snapshots = {task.id: operational_snapshot(task, grouped.get(task.id, [])) for task in tasks}
    return {task.id: {"operational_state": snapshots[task.id]["operational_state"],
        "pause_reasons": snapshots[task.id]["pause_reasons"], "waits": snapshots[task.id]["waits"],
        "status": task.status.value, "agent_id": task.agent_id,
        "last_error": task.last_error[:1000] if task.last_error else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        "next_attempt_at": task.next_attempt_at.isoformat() if task.next_attempt_at else None,
        "updated_at": (task.updated_at or task.created_at).isoformat(),
    } for task in tasks}


async def request_peer_message(
    *,
    requester_agent_id: int,
    peer_agent_id: int,
    message: str,
    language: str,
    source_task_id: UUID,
    connection_id: int | None = None,
) -> UUID:
    """Admit a colleague request without inventing a human Chat room.

    The normal delegated-child marker makes the source wait and resume with the
    peer's result. Admission does not grant contact, document or action permissions.
    """
    from . import mcp, runner, task_service
    from .models import TaskStatus

    if peer_agent_id == requester_agent_id:
        raise ValueError("A peer request must target another agent.")
    peer = await get_agent_record(peer_agent_id)
    if peer is None:
        raise ValueError("The recipient agent does not exist.")
    from app.messenger.facade import require_internal_peer_contact

    await require_internal_peer_contact(requester_agent_id, peer_agent_id, connection_id=connection_id)
    source = await task_service.get_by_id(source_task_id)
    if source is None or source.agent_id != requester_agent_id:
        raise PermissionError("The source task does not belong to the requesting agent.")
    if source.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
        raise ValueError("A terminal task cannot create a peer request.")
    blocked = await mcp.delegation_blocked_message(source_task_id)
    if blocked is not None:
        raise ValueError(blocked)
    peer_name = " ".join(part for part in (peer.first_name, peer.last_name) if part) or peer.code
    task_id = await mcp.create_task(
        requester_agent_id=requester_agent_id,
        agent_id=peer_agent_id,
        label=render_prompt(t("task_collab.request_label", language), peer=peer_name),
        objective=convert_to_html(message, "text/markdown"),
        source_task_id=source_task_id,
    )
    runner.go_next(task_id, fast=True)
    return task_id
