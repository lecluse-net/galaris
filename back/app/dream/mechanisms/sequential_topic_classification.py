"""Sequential Topic classification for canonical conversation messages."""

from __future__ import annotations

from app.llm import model_usages

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast as sql_cast, exists, func, or_, select, update

from app.connection import Connection
from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.messenger import Interaction, Message, Room
from app.task import Task, TaskMessage
from app.topic import TopicClassification, runtime_topic_detection_dependencies
from app.topic.sequential_detection import detect_topic_with_diagnostics
from core.database import get_db, get_db_session
from core.i18n import normalize_language

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import (
    claim_replayable_topic_application,
    claim_retry,
    create_running_receipt,
    replayable_topic_application,
)
from .topic_classification import (
    apply_topic_classification,
    topic_classification_payload,
    topic_creation_mode,
)


def _timestamp(value: datetime | None) -> int:
    return int(value.timestamp()) if value is not None else 0


def _decision(run_topic_id: UUID, classification: TopicClassification | None) -> TopicClassification:
    if classification is None:
        return TopicClassification(action="reuse", topic_id=run_topic_id)
    if classification.action == "create" and classification.topic_id is None:
        return classification.model_copy(update={"topic_id": run_topic_id})
    return classification


def _journal_message(row: Message, *, agent_id: int) -> TaskMessage:
    return TaskMessage(
        messenger_message_id=row.id,
        external_message_id=row.remote_message_id,
        platform=row.platform,
        sender_id=row.messenger_user_id,
        sender_external_id=row.user_id or "",
        sender_agent_id=agent_id if row.direction == "outbound" else None,
        sender_is_ai=row.direction == "outbound",
        room_id=row.messenger_room_id,
        room_external_id=row.room_id or "",
        text=row.text,
        timestamp=_timestamp(row.created_at),
    )


def _pending_topic_approval(
    *, connection_id: object, room_id: object
) -> Any:
    """Block a room only while its Topic approval can still be resolved."""

    return exists(
        select(Interaction.id).where(
            Interaction.kind == "topic_creation_approval",
            or_(
                and_(
                    Interaction.status == "PENDING",
                    Interaction.expires_at > func.now(),
                ),
                Interaction.status == "PROCESSING",
            ),
            Interaction.connection_id == connection_id,
            Interaction.room_id == room_id,
        )
    )


def _room_has_default_topic(room_id: object) -> Any:
    return exists(
        select(Room.id).where(
            Room.id == room_id,
            Room.topic_id.is_not(None),
        )
    )


async def _message_window(
    row: Message, *, agent_id: int
) -> tuple[list[TaskMessage], UUID | None]:
    ordering = Message.created_at
    current_order = row.created_at
    records = list(
        (
            await get_db().scalars(
                select(Message)
                .where(
                    Message.messenger_room_id == row.messenger_room_id,
                    func.length(func.trim(Message.text)) > 0,
                    or_(
                        ordering < current_order,
                        and_(ordering == current_order, Message.id <= row.id),
                    ),
                )
                .order_by(ordering.desc(), Message.id.desc())
                .limit(10)
            )
        ).all()
    )
    records.reverse()
    previous_topic_id = records[-2].topic_id if len(records) > 1 else None
    return [
        _journal_message(item, agent_id=agent_id) for item in records
    ], previous_topic_id


async def propagate_classified_subject(
    subject: Message,
) -> None:
    """Project a classified message to its rounds and directly derived Tasks."""

    db = get_db()
    linked_ids = set(
        (
            await db.scalars(
                select(ConversationRoundMessage.round_id).where(
                    ConversationRoundMessage.message_id == subject.id
                )
            )
        ).all()
    )
    round_ids = list(linked_ids)
    if round_ids:
        output_message_ids = select(ConversationRoundMessage.message_id).where(
            ConversationRoundMessage.round_id.in_(round_ids),
            ConversationRoundMessage.role == "output",
        )
        await db.execute(
            update(Message)
            .where(
                Message.id.in_(output_message_ids),
                Message.topic_overridden.is_(False),
            )
            .values(
                topic_id=subject.topic_id,
                contact_memory_item_id=subject.contact_memory_item_id,
            )
        )
        await db.execute(
            update(ConversationRound)
            .where(ConversationRound.id.in_(round_ids))
            .values(
                topic_id=subject.topic_id,
                contact_memory_item_id=subject.contact_memory_item_id,
            )
        )
        task_ids = select(ConversationTaskLink.task_id).where(
            ConversationTaskLink.round_id.in_(round_ids)
        )
        await db.execute(
            update(Task)
            .where(Task.id.in_(task_ids), Task.topic_id.is_(None))
            .values(
                topic_id=subject.topic_id,
                contact_memory_item_id=subject.contact_memory_item_id,
            )
        )
    await db.commit()


class MessageTopicClassificationMechanism:
    key = "topic.classify_message"

    async def is_available(self) -> bool:
        async with get_db_session():
            from app.llm import profile_service

            return await profile_service.has_any_profile_value(model_usages.DREAM)

    async def count_pending(self) -> int:
        async with get_db_session():
            scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "message",
                    DreamReceipt.subject_id == sql_cast(Message.id, String),
                )
            )
            needs_replay = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "message",
                    DreamReceipt.subject_id == sql_cast(Message.id, String),
                    replayable_topic_application(),
                )
            )
            return int(
                await get_db().scalar(
                    select(func.count(Message.id)).where(
                        Message.messenger_room_id.is_not(None),
                        Message.direction == "inbound",
                        func.length(func.trim(Message.text)) > 0,
                        Message.topic_id.is_(None),
                        ~_room_has_default_topic(Message.messenger_room_id),
                        ~_pending_topic_approval(
                            connection_id=Message.connection_id,
                            room_id=sql_cast(Message.messenger_room_id, String),
                        ),
                        or_(~scanned, needs_replay),
                    )
                )
                or 0
            )

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        replay = await claim_replayable_topic_application(
            self.key,
            subject_kind="message",
            eligibility=exists(
                select(Message.id).where(
                    sql_cast(Message.id, String) == DreamReceipt.subject_id,
                    Message.messenger_room_id.is_not(None),
                    Message.direction == "inbound",
                    func.length(func.trim(Message.text)) > 0,
                    Message.topic_id.is_(None),
                    ~_room_has_default_topic(Message.messenger_room_id),
                    ~_pending_topic_approval(
                        connection_id=Message.connection_id,
                        room_id=sql_cast(Message.messenger_room_id, String),
                    ),
                )
            ),
        )
        if replay is not None:
            return replay
        async with get_db_session():
            row = await get_db().scalar(
                select(Message)
                .where(
                    Message.messenger_room_id.is_not(None),
                    Message.direction == "inbound",
                    func.length(func.trim(Message.text)) > 0,
                    Message.topic_id.is_(None),
                    ~_room_has_default_topic(Message.messenger_room_id),
                    ~_pending_topic_approval(
                        connection_id=Message.connection_id,
                        room_id=sql_cast(Message.messenger_room_id, String),
                    ),
                    ~exists(
                        select(DreamReceipt.id).where(
                            DreamReceipt.mechanism_key == self.key,
                            DreamReceipt.subject_kind == "message",
                            DreamReceipt.subject_id
                            == sql_cast(Message.id, String),
                        )
                    ),
                )
                .order_by(Message.created_at, Message.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            claim = create_running_receipt(
                mechanism_key=self.key,
                subject_kind="message",
                subject_id=str(row.id),
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        async with get_db_session():
            row = await get_db().get(Message, UUID(claim.subject_id))
            if row is None or row.direction != "inbound":
                return DreamPrepared(payload={})
            room = await get_db().get(Room, row.messenger_room_id)
            if room is not None and room.topic_id is not None:
                return DreamPrepared(payload={})
            connection = await get_db().get(Connection, row.connection_id)
            if connection is None:
                return DreamPrepared(payload={})
            messages, current_topic_id = await _message_window(
                row, agent_id=connection.agent_id
            )
            dependencies = await runtime_topic_detection_dependencies(
                task_id=None, agent_id=connection.agent_id
            )
            run = await detect_topic_with_diagnostics(
                messages,
                len(messages) - 1,
                current_topic_id,
                dependencies=dependencies,
            )
            decision = _decision(run.evaluation.topic_id, run.evaluation.classification)
            candidates = await dependencies.catalog.list_candidates(activity=row.text)
            language = await get_db().scalar(
                select(ConversationRound.language)
                .join(
                    ConversationRoundMessage,
                    ConversationRoundMessage.round_id == ConversationRound.id,
                )
                .where(
                    ConversationRoundMessage.message_id == row.id,
                    ConversationRoundMessage.role == "input",
                )
                .order_by(ConversationRound.created_at.desc())
                .limit(1)
            )
            payload = topic_classification_payload(
                decision,
                candidates,
                language=normalize_language(
                    language or (row.metadata_ or {}).get("language")
                ),
                creation_mode=topic_creation_mode(),
            )
            payload["diagnostics"] = run.evaluation.model_dump(mode="json")
            return DreamPrepared(payload=payload, cost=run.cost)

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        async with get_db_session():
            row = await get_db().get(Message, UUID(claim.subject_id))
            if row is None or row.direction != "inbound" or not payload:
                return 0
            room = await get_db().get(Room, row.messenger_room_id)
            if room is not None and room.topic_id is not None:
                return 0
            return await apply_topic_classification(
                claim=claim,
                payload=payload,
                subject=row,
            )


message_topic_classification_mechanism = MessageTopicClassificationMechanism()


__all__ = [
    "MessageTopicClassificationMechanism",
    "message_topic_classification_mechanism",
    "propagate_classified_subject",
]
