"""Repository display scope: current controllers and explicitly linked live Tasks."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from app.code import link_repository, register_repository
from app.messenger import get_agent_chat_room, get_internal_room
from app.task import Task, TaskStatus
from app.tools import McpToolContext
from core.database import get_db

from .contracts import ConversationTurn
from .models import ConversationRound, ConversationTaskLink
from .preparation import ConversationSuperseded

RepositoryPublisher = Callable[[UUID, UUID, str | None, str, str], Awaitable[None]]
_publisher: RepositoryPublisher | None = None


def register_repository_display_publisher(publisher: RepositoryPublisher) -> None:
    global _publisher
    _publisher = publisher


async def repository_scope(ctx: McpToolContext) -> tuple[UUID, UUID, bool] | None:
    turn = ctx.resource("conversation_turn")
    if isinstance(turn, ConversationTurn):
        if turn.origin != "text" or turn.agent_id != ctx.agent_id:
            return None
        room = await get_agent_chat_room(ctx.agent_id, turn.room_id)
        return (turn.room_id, turn.round_id, True) if room is not None and room.source is None and room.messenger_active and room.agent_id == ctx.agent_id else None
    if ctx.task_id is None:
        return None
    task = await get_db().get(Task, ctx.task_id, populate_existing=True)
    if task is None or task.agent_id != ctx.agent_id or task.status != TaskStatus.EXEC or task.paused:
        return None
    if task.lease_token is None or task.lease_expires_at is None or task.lease_expires_at <= datetime.now(timezone.utc):
        return None
    origin = await get_db().scalar(select(ConversationRound).join(
        ConversationTaskLink, ConversationTaskLink.round_id == ConversationRound.id).where(
        ConversationTaskLink.task_id == ctx.task_id))
    if origin is None:
        return None
    if origin.requester_user_id is None:
        return None
    room = await get_internal_room(origin.requester_user_id, origin.room_id)
    if room is None or not room.messenger_active:
        return None
    newer = await get_db().scalar(select(ConversationRound.id).where(
        ConversationRound.room_id == origin.room_id, ConversationRound.created_at > origin.created_at).limit(1))
    return origin.room_id, origin.id, newer is None


async def can_show_repository(ctx: McpToolContext) -> bool:
    return _publisher is not None and await repository_scope(ctx) is not None


async def show_repository(ctx: McpToolContext, repository: str, file: str | None,
                          view: Literal["changes", "files"]) -> dict[str, str]:
    scope = await repository_scope(ctx)
    if scope is None or _publisher is None:
        raise PermissionError("Repository presentation requires an authorized internal Chat or its live linked Task")
    if file is not None:
        candidate = PurePosixPath(file)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in file or len(file) > 1024 or any(ord(char) < 32 for char in file):
            raise ValueError("file must be relative to the repository")
    workspace = await register_repository(repository, ctx.agent_id)
    turn = ctx.resource("conversation_turn")
    if isinstance(turn, ConversationTurn) and turn.assert_fresh_before_effect is not None and not await turn.assert_fresh_before_effect():
        raise ConversationSuperseded("Repository request superseded")
    # Revalidate the link after discovery, which may have awaited SSH.
    current = await repository_scope(ctx)
    if current is None or current[:2] != scope[:2]:
        raise PermissionError("Repository presentation scope expired")
    sequence = await link_repository(workspace, scope[0], ctx.task_id, file, view)
    await get_db().commit()
    if current[2]:
        await _publisher(scope[0], workspace.id, file, view, str(sequence))
    return {"status": "requested" if current[2] else "referenced", "uri": f"galaris://code/{workspace.id}", "room_id": str(scope[0])}
