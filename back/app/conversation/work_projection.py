"""Message-window projections of conversation documents and processes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select

from app.messenger import Message, extract_preview_references
from app.process import list_run_summaries_page_for_scope
from app.task import Task, parse_working_set
from core.database import get_db

from .context import conversation_document_references
from .document_metadata import (
    resolve_conversation_document_metadata,
    resolve_conversation_room_documents,
)
from .contracts import (
    ConversationDocument,
    ConversationDocumentList,
    ConversationProcessList,
)
from .models import ConversationProcessLink, ConversationRound
from .task_projection import (
    list_room_task_ids_for_rounds,
    visible_room_message_ids,
    visible_room_round_ids,
)


def _document_id(reference: str) -> UUID | None:
    prefix = "document://"
    if not reference.startswith(prefix):
        return None
    try:
        return UUID(reference.removeprefix(prefix))
    except ValueError:
        return None


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0


async def list_room_documents(
    room_id: UUID,
    from_message_id: UUID,
    *,
    agent_id: int,
    page: int = 1,
    page_size: int = 10,
) -> ConversationDocumentList:
    """List working documents tied to messages currently loaded in Chat."""

    message_ids = await visible_room_message_ids(room_id, from_message_id)
    round_ids = await visible_room_round_ids(room_id, from_message_id)
    documents: dict[UUID, ConversationDocument] = {}

    def add(
        reference: str,
        *,
        label: str = "",
        revision: int | None = None,
        source_task_id: UUID | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        document_id = _document_id(reference)
        if document_id is None:
            return
        current = documents.get(document_id)
        if current is None:
            documents[document_id] = ConversationDocument(
                id=document_id,
                uri=f"document://{document_id}",
                label=label,
                revision=revision,
                source_task_id=source_task_id,
                updated_at=updated_at,
            )
            return
        documents[document_id] = current.model_copy(
            update={
                "label": label or current.label,
                "revision": revision or current.revision,
                "source_task_id": source_task_id or current.source_task_id,
                "updated_at": (
                    updated_at
                    if _timestamp(updated_at) >= _timestamp(current.updated_at)
                    else current.updated_at
                ),
            }
        )

    room_documents = await resolve_conversation_room_documents(room_id, agent_id)
    for metadata in room_documents:
        add(
            f"document://{metadata.id}",
            label=metadata.title,
            revision=metadata.revision,
            updated_at=metadata.updated_at,
        )

    messages = list(
        (
            await get_db().scalars(
                Message.histo_filter(
                    select(Message)
                    .where(Message.id.in_(message_ids))
                    .order_by(Message.created_at, Message.id)
                )
            )
        ).all()
    )
    for message in messages:
        for reference in extract_preview_references(message.text):
            add(reference, updated_at=message.created_at)

    if round_ids:
        rounds = list(
            (
                await get_db().scalars(
                    select(ConversationRound)
                    .where(ConversationRound.id.in_(round_ids))
                    .order_by(ConversationRound.created_at, ConversationRound.id)
                )
            ).all()
        )
        for round_ in rounds:
            result = (
                cast(Mapping[str, object], round_.execution_result)
                if isinstance(round_.execution_result, Mapping)
                else None
            )
            for reference, label, _operation in conversation_document_references(result):
                add(
                    reference,
                    label=label,
                    updated_at=round_.finished_at or round_.created_at,
                )

        task_ids = await list_room_task_ids_for_rounds(room_id, round_ids)
        if task_ids:
            tasks = list(
                (
                    await get_db().scalars(
                        Task.histo_filter(
                            select(Task)
                            .where(Task.id.in_(task_ids))
                            .order_by(Task.created_at, Task.id)
                        )
                    )
                ).all()
            )
            for task in tasks:
                try:
                    resources = parse_working_set(task).active()
                except (TypeError, ValueError):
                    continue
                for resource in resources:
                    reference = resource.reference
                    if resource.resource_type == "memory_document" and "://" not in reference:
                        try:
                            reference = f"document://{UUID(reference)}"
                        except ValueError:
                            continue
                    add(
                        reference,
                        label=resource.label,
                        revision=resource.revision,
                        source_task_id=resource.producer_task_id or task.id,
                        updated_at=resource.updated_at,
                    )

    metadata_by_id = await resolve_conversation_document_metadata(tuple(documents))
    for document_id, metadata in metadata_by_id.items():
        if metadata.deleted:
            continue
        current = documents.get(document_id)
        if current is None:
            continue
        documents[document_id] = current.model_copy(
            update={
                "label": metadata.title,
                "revision": metadata.revision,
                "updated_at": metadata.updated_at or current.updated_at,
            }
        )

    items = sorted(
        documents.values(),
        key=lambda item: (_timestamp(item.updated_at), str(item.id)),
        reverse=True,
    )
    total = len(items)
    offset = (page - 1) * page_size
    return ConversationDocumentList(
        items=items[offset : offset + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )


async def list_room_processes(
    room_id: UUID,
    from_message_id: UUID,
    *,
    page: int = 1,
    page_size: int = 10,
) -> ConversationProcessList:
    """List process runs launched by visible rounds or their Task trees."""

    round_ids = await visible_room_round_ids(room_id, from_message_id)
    if not round_ids:
        return ConversationProcessList(total=0, page=page, page_size=page_size)
    task_ids = await list_room_task_ids_for_rounds(room_id, round_ids)
    direct_run_ids = tuple(
        (
            await get_db().scalars(
                select(ConversationProcessLink.process_run_id).where(
                    ConversationProcessLink.round_id.in_(round_ids)
                )
            )
        ).all()
    )
    runs, total = await list_run_summaries_page_for_scope(
        direct_run_ids,
        task_ids,
        page=page,
        page_size=page_size,
    )
    return ConversationProcessList(
        items=runs,
        total=total,
        page=page,
        page_size=page_size,
    )


__all__ = ["list_room_documents", "list_room_processes"]
