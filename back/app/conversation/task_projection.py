"""Conversation-scoped projection of durable Task trees."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.messenger import Message
from app.task import Task, TaskRead
from core.database import get_db

from .contracts import ConversationTask, ConversationTaskTree
from .models import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)


async def visible_room_message_ids(
    room_id: UUID,
    from_message_id: UUID | None,
) -> tuple[UUID, ...]:
    """Return the contiguous message window currently projected by Chat."""

    query = Message.histo_filter(
        select(Message.id).where(Message.messenger_room_id == room_id)
    )
    if from_message_id is not None:
        anchor = await get_db().scalar(
            Message.histo_filter(
                select(Message).where(
                    Message.id == from_message_id,
                    Message.messenger_room_id == room_id,
                )
            )
        )
        if anchor is None:
            return ()
        query = query.where(
            or_(
                Message.created_at > anchor.created_at,
                and_(
                    Message.created_at == anchor.created_at,
                    Message.id >= anchor.id,
                ),
            )
        )
    rows = await get_db().scalars(query.order_by(Message.created_at, Message.id))
    return tuple(rows.all())


async def visible_room_round_ids(
    room_id: UUID,
    from_message_id: UUID | None,
) -> tuple[UUID, ...]:
    """Resolve rounds touching the visible, contiguous message window."""

    message_ids = await visible_room_message_ids(room_id, from_message_id)
    if not message_ids:
        return ()
    rows = await get_db().scalars(
        select(ConversationRoundMessage.round_id)
        .join(
            ConversationRound,
            ConversationRound.id == ConversationRoundMessage.round_id,
        )
        .where(
            ConversationRound.room_id == room_id,
            ConversationRoundMessage.message_id.in_(message_ids),
        )
        .distinct()
    )
    return tuple(rows.all())


async def list_room_task_ids_for_rounds(
    room_id: UUID,
    round_ids: Sequence[UUID],
) -> tuple[UUID, ...]:
    """Return every Task ID in the tree rooted in conversation rounds.

    ``parent_id`` is the canonical execution hierarchy. ``source_task_id`` is also
    traversed because it records causal delegation even when an explicit parent was
    supplied. A distinct recursive CTE makes arbitrary depth finite even if corrupt
    historical data contains a cycle.
    """

    normalized_round_ids = tuple(dict.fromkeys(round_ids))
    if not normalized_round_ids:
        return ()

    root_ids = (
        Task.histo_filter(
            select(Task.id)
            .join(ConversationTaskLink, ConversationTaskLink.task_id == Task.id)
            .join(ConversationRound, ConversationRound.id == ConversationTaskLink.round_id)
            .where(
                ConversationRound.room_id == room_id,
                ConversationRound.id.in_(normalized_round_ids),
            )
        )
        .cte("conversation_task_tree", recursive=True)
    )
    descendants = Task.histo_filter(
        select(Task.id).join(
            root_ids,
            or_(
                Task.parent_id == root_ids.c.id,
                Task.source_task_id == root_ids.c.id,
            ),
        )
    )
    task_tree = root_ids.union(descendants)
    return tuple((await get_db().scalars(select(task_tree.c.id))).all())


async def list_room_tasks_for_rounds(
    room_id: UUID,
    round_ids: Sequence[UUID],
    *,
    page: int = 1,
    page_size: int = 10,
) -> ConversationTaskTree:
    """Return one recent-first page of the Task tree rooted in conversation rounds."""

    normalized_round_ids = tuple(dict.fromkeys(round_ids))
    tree_ids = await list_room_task_ids_for_rounds(room_id, normalized_round_ids)
    if not tree_ids:
        return ConversationTaskTree(total=0, page=page, page_size=page_size)
    rows = list(
        (
            await get_db().scalars(
                Task.histo_filter(
                    select(Task)
                    .where(Task.id.in_(tree_ids))
                    .order_by(Task.created_at.desc(), Task.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
        ).all()
    )
    direct_topic_rows = (
        await get_db().execute(
            select(ConversationTaskLink.task_id, ConversationRound.topic_id)
            .join(ConversationRound, ConversationRound.id == ConversationTaskLink.round_id)
            .where(
                ConversationRound.room_id == room_id,
                ConversationRound.id.in_(normalized_round_ids),
                ConversationTaskLink.task_id.in_(tuple(row.id for row in rows)),
            )
        )
    ).all()
    direct_topics = {
        task_id: topic_id for task_id, topic_id in direct_topic_rows
    }
    direct_ids = set(direct_topics)
    visible_ids = set(tree_ids)
    items: list[ConversationTask] = []
    for row in rows:
        tree_parent_id = (
            row.parent_id
            if row.parent_id in visible_ids and row.parent_id != row.id
            else row.source_task_id
            if row.source_task_id in visible_ids and row.source_task_id != row.id
            else None
        )
        task_data = TaskRead.model_validate(row).model_dump()
        if row.id in direct_topics:
            # In the Messenger projection, a directly admitted Task carries the exact
            # conversation-round Topic. This also corrects historical rows that were
            # classified independently while their round still had no Topic.
            task_data["topic_id"] = direct_topics[row.id]
        items.append(
            ConversationTask(
                **task_data,
                tree_parent_id=tree_parent_id,
                directly_linked=row.id in direct_ids,
            )
        )
    return ConversationTaskTree(
        items=items,
        total=len(tree_ids),
        page=page,
        page_size=page_size,
    )


async def list_room_tasks(
    room_id: UUID,
    from_message_id: UUID | None = None,
    *,
    page: int = 1,
    page_size: int = 10,
) -> ConversationTaskTree:
    """Return linked Tasks, optionally limited to the Chat message window."""

    if from_message_id is None:
        round_ids = tuple(
            (
                await get_db().scalars(
                    select(ConversationRound.id).where(
                        ConversationRound.room_id == room_id
                    )
                )
            ).all()
        )
    else:
        round_ids = await visible_room_round_ids(room_id, from_message_id)
    return await list_room_tasks_for_rounds(
        room_id,
        round_ids,
        page=page,
        page_size=page_size,
    )
