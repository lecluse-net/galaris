"""Administrative lifecycle operations for persisted text conversation rounds."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from typing import Literal

from loguru import logger
from sqlalchemy import select, update

from app.llm import LLMCall
from core.database import get_db

from .models import (
    ConversationDeliveryResolution, ConversationRound, ConversationNotificationResolution,
    ConversationTaskLink, ConversationProcessLink,
)


class DeliveryResolutionConflict(ValueError):
    """Only an unresolved, unleased delivery may be resolved by an operator."""


async def resolve_unknown_delivery(
    round_id: UUID, *, actor_user_id: int,
    decision: Literal["DELIVERED", "SKIPPED"], evidence: str,
) -> None:
    evidence = evidence.strip()
    if len(evidence) < 10 or len(evidence) > 2000:
        raise DeliveryResolutionConflict("A bounded explanation of the verification is required")
    db = get_db()
    round_ = await db.scalar(select(ConversationRound).where(ConversationRound.id == round_id).with_for_update())
    if round_ is None:
        raise DeliveryResolutionConflict("Conversation round no longer exists")
    previous = await db.scalar(select(ConversationDeliveryResolution).where(ConversationDeliveryResolution.round_id == round_id))
    if previous is not None and previous.decision == decision and previous.evidence == evidence and previous.actor_user_id == actor_user_id:
        return
    if round_.delivery_state != "UNKNOWN" or round_.lease_token is not None or previous is not None:
        raise DeliveryResolutionConflict("Delivery is no longer unresolved or is still leased")
    db.add(ConversationDeliveryResolution(round_id=round_id, actor_user_id=actor_user_id, decision=decision, evidence=evidence))
    round_.delivery_state = decision
    await db.commit()


async def resolve_unknown_notification(
    round_id: UUID, *, kind: Literal["task", "process"], link_id: UUID,
    attempt_number: int, actor_user_id: int,
    decision: Literal["DELIVERED", "SKIPPED"], evidence: str,
) -> None:
    """Resolve only the observed attempt; never resend or touch the task/run result."""
    evidence = evidence.strip()
    if not 10 <= len(evidence) <= 2000:
        raise DeliveryResolutionConflict("A bounded explanation of the verification is required")
    db = get_db()
    if kind == "task":
        link = await db.scalar(select(ConversationTaskLink).where(
            ConversationTaskLink.id == link_id, ConversationTaskLink.round_id == round_id,
        ).with_for_update())
        target_filter = ConversationNotificationResolution.task_link_id == link_id
    else:
        link = await db.scalar(select(ConversationProcessLink).where(
            ConversationProcessLink.id == link_id, ConversationProcessLink.round_id == round_id,
        ).with_for_update())
        target_filter = ConversationNotificationResolution.process_link_id == link_id
    if link is None or link.notification_attempt_count != attempt_number:
        raise DeliveryResolutionConflict("Notification no longer exists or its attempt has changed")
    previous = await db.scalar(select(ConversationNotificationResolution).where(
        target_filter, ConversationNotificationResolution.attempt_number == attempt_number,
    ))
    if previous is not None and previous.decision == decision and previous.evidence == evidence and previous.actor_user_id == actor_user_id:
        return
    if link.notification_state != "UNKNOWN" or link.notification_lease_token is not None or previous is not None:
        raise DeliveryResolutionConflict("Notification is no longer unresolved or is still leased")
    db.add(ConversationNotificationResolution(
        task_link_id=link_id if kind == "task" else None,
        process_link_id=link_id if kind == "process" else None,
        attempt_number=attempt_number, actor_user_id=actor_user_id,
        decision=decision, evidence=evidence,
    ))
    link.notification_state = decision
    await db.commit()


async def update_round_topic(round_id: UUID, topic_id: UUID | None) -> bool:
    """Assign or clear the thematic topic of one persisted text round."""

    db = get_db()
    round_ = await db.scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == round_id,
            ConversationRound.voice_session_id.is_(None),
        )
        .with_for_update()
    )
    if round_ is None:
        return False
    round_.topic_id = topic_id
    await db.commit()
    return True


async def delete_round(round_id: UUID) -> bool:
    """Permanently remove one round in any state without deleting canonical messages.

    Canonical tasks and process runs launched by the round remain intact. Their lineage
    links and the round attempts are removed by PostgreSQL cascades; LLM calls are retained
    as audit records, closed when still running, and detached from the deleted round.
    """

    db = get_db()
    round_ = await db.scalar(
        select(ConversationRound)
        .where(ConversationRound.id == round_id)
        .with_for_update()
    )
    if round_ is None:
        return False

    # Holding the row lock prevents a scheduler claim from racing between cancellation and
    # deletion. A worker owned by another backend loses its durable lease as soon as this
    # transaction commits; the heartbeat then cancels its action on that process as well.
    from . import scheduler

    try:
        await scheduler.cancel_round(round_id)
    except Exception:
        # Administrative deletion must remain available even if a local runtime does not
        # cooperate. The durable row removal is the cross-process cancellation barrier.
        logger.exception(
            "Conversation round {} could not be cancelled locally before deletion",
            round_id,
        )

    now = datetime.now(timezone.utc)
    running_calls = list(
        (
            await db.scalars(
                select(LLMCall)
                .where(
                    LLMCall.conversation_round_id == round_id,
                    LLMCall.status == "running",
                )
                .with_for_update()
            )
        ).all()
    )
    for call in running_calls:
        call.status = "cancelled"
        call.completed_at = now
        call.duration = max(0.0, (now - call.started_at).total_seconds())
        call.error = call.error or (
            "LLM trace stopped because its conversation round was deleted."
        )

    await db.execute(
        update(LLMCall)
        .where(LLMCall.conversation_round_id == round_id)
        .values(conversation_round_id=None)
    )
    await db.delete(round_)
    await db.commit()
    return True


__all__ = ["delete_round", "update_round_topic"]
