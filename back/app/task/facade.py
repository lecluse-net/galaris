"""Durable peer communication using the existing delegated Task lifecycle."""

from uuid import UUID

from app.agent import get_agent_record, require_agent_contact
from core.i18n import render_prompt, t
from core.util import convert_to_html


async def request_peer_message(
    *,
    requester_agent_id: int,
    peer_agent_id: int,
    message: str,
    language: str,
    source_task_id: UUID,
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
    await require_agent_contact(requester_agent_id, peer_agent_id=peer_agent_id)
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
