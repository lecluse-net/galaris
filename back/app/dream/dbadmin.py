"""DbAdmin reconciliation for rebuildable Dream Topic assignments."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import String, cast as sql_cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connection import Connection
from app.messenger import Interaction, Message, MessengerUser
from app.task import Task
from app.topic import Topic, TopicClassification
from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .models import DreamReceipt
from .service import replayable_topic_application


def _checkpoint_topic_id(payload: object) -> UUID | None:
    if not isinstance(payload, dict):
        return None
    checkpoint = cast(dict[str, Any], payload)
    try:
        decision = TopicClassification.model_validate(checkpoint.get("decision"))
    except ValueError:
        return None
    creation_mode = str(checkpoint.get("creation_mode") or "propose")
    if decision.action == "create" and creation_mode != "auto":
        return None
    return decision.topic_id


async def _reconcile_topic_assignments(session: AsyncSession) -> None:
    """Restore direct Topic projections from successful durable checkpoints."""

    rows = (
        await session.execute(
            select(
                DreamReceipt.subject_kind,
                DreamReceipt.subject_id,
                DreamReceipt.prepared_payload,
            ).where(
                DreamReceipt.mechanism_key.in_(
                    ("topic.classify_message", "topic.classify_task")
                ),
                replayable_topic_application(),
            )
        )
    ).all()
    message_ids: dict[UUID, list[UUID]] = defaultdict(list)
    task_ids: dict[UUID, list[UUID]] = defaultdict(list)
    for subject_kind, raw_subject_id, payload in rows:
        topic_id = _checkpoint_topic_id(payload)
        if topic_id is None:
            continue
        try:
            subject_id = UUID(str(raw_subject_id))
        except ValueError:
            continue
        if subject_kind == "message":
            message_ids[topic_id].append(subject_id)
        elif subject_kind == "task":
            task_ids[topic_id].append(subject_id)

    candidate_topic_ids = set(message_ids) | set(task_ids)
    if not candidate_topic_ids:
        return
    active_topic_ids = set(
        (
            await session.scalars(
                select(Topic.id).where(
                    Topic.id.in_(candidate_topic_ids),
                    Topic.deleted_at.is_(None),
                )
            )
        ).all()
    )
    restored_messages = 0
    restored_tasks = 0
    for topic_id in sorted(active_topic_ids, key=str):
        target_message_ids = message_ids.get(topic_id, [])
        if target_message_ids:
            restored_message_ids = await session.scalars(
                update(Message)
                .where(
                    Message.id.in_(target_message_ids),
                    Message.topic_id.is_(None),
                    Message.deleted_at.is_(None),
                )
                .values(topic_id=topic_id)
                .returning(Message.id)
            )
            restored_messages += len(restored_message_ids.all())
        target_task_ids = task_ids.get(topic_id, [])
        if target_task_ids:
            restored_task_ids = await session.scalars(
                update(Task)
                .where(
                    Task.id.in_(target_task_ids),
                    Task.topic_id.is_(None),
                    Task.deleted_at.is_(None),
                )
                .values(topic_id=topic_id)
                .returning(Task.id)
            )
            restored_tasks += len(restored_task_ids.all())
    logger.info(
        "Dream Topic assignment reconciliation: messages={} tasks={}",
        restored_messages,
        restored_tasks,
    )


async def _reconcile_topic_approval_recipients(session: AsyncSession) -> None:
    """Repair the recipient projection of pending message-based Topic approvals.

    The source message and its exact Tool/connection/room must prove the identity.
    Captured decisions and approvals for Tasks or other domains remain untouched.
    """

    repaired = await session.scalars(
        update(Interaction)
        .where(
            Interaction.kind == "topic_creation_approval",
            Interaction.status == "PENDING",
            Interaction.expires_at > func.now(),
            Interaction.metadata_["subject_kind"].as_string() == "message",
            Interaction.metadata_["subject_id"].as_string() == sql_cast(Message.id, String),
            Message.direction == "inbound",
            Message.deleted_at.is_(None),
            Interaction.connection_id == Message.connection_id,
            Connection.id == Message.connection_id,
            Connection.agent_id == Interaction.agent_id,
            Interaction.tool_id == Message.tool_id,
            Interaction.room_id == sql_cast(Message.messenger_room_id, String),
            MessengerUser.id == Message.messenger_user_id,
            MessengerUser.tool_id == Message.tool_id,
            MessengerUser.external_id == Message.user_id,
            MessengerUser.deleted_at.is_(None),
            Interaction.user_id == sql_cast(MessengerUser.id, String),
            Interaction.user_id != MessengerUser.external_id,
        )
        .values(user_id=MessengerUser.external_id)
        .returning(Interaction.id)
        .execution_options(synchronize_session=False)
    )
    logger.info("Dream Topic approval recipient reconciliation: repaired={}", len(repaired.all()))


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.dream.topic_approval_recipients",
            handler=_reconcile_topic_approval_recipients,
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.dream.topic_assignments",
            handler=_reconcile_topic_assignments,
        )
    )


__all__ = ["register_dbadmin"]
