"""Administrative lifecycle operations for persisted voice conversation turns."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.conversation import ConversationRound
from core.database import get_db

from .models import VoiceTurnStatus


class VoiceTurnConflictError(RuntimeError):
    """Raised when a live voice turn cannot be removed safely."""


async def update_turn_topic(turn_id: UUID, topic_id: UUID | None) -> bool:
    """Assign or clear the thematic topic of one persisted voice turn."""

    db = get_db()
    round_ = await db.scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == turn_id,
            ConversationRound.voice_session_id.is_not(None),
        )
        .with_for_update()
    )
    if round_ is None:
        return False
    round_.topic_id = topic_id
    await db.commit()
    return True


async def delete_turn(turn_id: UUID) -> bool:
    """Permanently remove one terminal turn while retaining detached LLM audit calls."""

    db = get_db()
    round_ = await db.get(ConversationRound, turn_id)
    if round_ is None or round_.voice_session_id is None:
        return False
    if round_.status == VoiceTurnStatus.RUNNING.value or (
        round_.status in {VoiceTurnStatus.INTERRUPTED.value, VoiceTurnStatus.FAILED.value}
        and round_.resolved_by_round_id is None
        and round_.effective_objective is not None
    ):
        raise VoiceTurnConflictError("An active voice conversation turn cannot be deleted")

    await db.delete(round_)
    await db.commit()
    return True


__all__ = ["VoiceTurnConflictError", "delete_turn", "update_turn_topic"]
