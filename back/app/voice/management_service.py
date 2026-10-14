"""Administrative lifecycle operations for persisted voice conversation turns."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.conversation import ConversationRound
from core.database import get_db


class VoiceTurnConflictError(RuntimeError):
    """Deletion is fenced durably but runtime teardown has not finished."""


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
    """Fence an audio owner before removing its round, preserving canonical records.

    Lock order is session then round, like start_turn. Close an active call as a
    deliberate safety boundary: deleting its live context must not let native SDK
    callbacks recreate it. Commit the fence first so cancellation finalizers cannot
    wait on locks held by this request. The fence survives request failure/restart.
    """
    from . import conversation_service
    from .models import VoiceConversationSession, VoiceConversationStatus, VoiceTurnDeletion
    from .runtime_control import cancel_session
    from app.tools.facade import invalidate_authorization_context

    db = get_db()
    session_id = await db.scalar(
        select(ConversationRound.voice_session_id).where(
            ConversationRound.id == turn_id,
        )
    )
    if session_id is None:
        # DELETE is idempotent, but must never delete a text round through this API.
        return await db.get(ConversationRound, turn_id, populate_existing=True) is None
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(
            VoiceConversationSession.id == session_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        return True
    round_ = await db.scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == turn_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None:
        return True
    _, agent_id, _ = await conversation_service.message_context(session)
    request = await db.get(VoiceTurnDeletion, turn_id)
    if request is None:
        request = VoiceTurnDeletion(
            id=turn_id,
            session_id=session_id,
            agent_id=agent_id,
            requested_at=datetime.now(timezone.utc),
            status="PENDING",
        )
        db.add(request)
    await invalidate_authorization_context(agent_id, f"voice:{session_id}:round:{turn_id}")
    await invalidate_authorization_context(agent_id, f"round:{turn_id}")
    round_.status = "CANCELLED"
    round_.encrypted_checkpoint = None
    round_.lease_token = None
    round_.lease_owner = None
    round_.lease_expires_at = None
    if session.status == VoiceConversationStatus.ACTIVE.value:
        session.status = VoiceConversationStatus.CANCELLED.value
        session.finished_at = datetime.now(timezone.utc)
        session.error = "Appel fermé par la suppression administrative d’un tour audio."
    await db.commit()

    await cancel_session(session_id)
    await process_deletions(turn_id=turn_id)
    request = await db.get(VoiceTurnDeletion, turn_id, populate_existing=True)
    if request is not None and request.status != "COMPLETED":
        raise VoiceTurnConflictError(
            "Suppression enregistrée ; fermeture audio en cours. "
            "La demande sera reprise automatiquement et son état est consultable."
        )
    await conversation_service.publish_session("update", session_id, status=session.status)
    return True


async def deletion_status(turn_id: UUID) -> dict[str, object] | None:
    from .models import VoiceTurnDeletion

    request = await get_db().get(VoiceTurnDeletion, turn_id, populate_existing=True)
    if request is None:
        return None
    return {
        "turn_id": str(request.id),
        "agent_id": request.agent_id,
        "status": request.status,
        "last_error": request.last_error,
    }


async def process_deletions(*, turn_id: UUID | None = None) -> None:
    """Claim requests transactionally on any worker, including after a restart."""
    from app.conversation import delete_round
    from .models import VoiceConversationSession, VoiceTurnDeletion
    from .runtime_control import session_stopped

    db = get_db()
    query = select(VoiceTurnDeletion).where(VoiceTurnDeletion.status != "COMPLETED")
    if turn_id is not None:
        query = query.where(VoiceTurnDeletion.id == turn_id)
    requests = list(
        (await db.scalars(query.order_by(VoiceTurnDeletion.requested_at).limit(50))).all()
    )
    # Read candidate IDs without holding round/session locks over runtime probing.
    ids = [request.id for request in requests]
    await db.commit()
    for request_id in ids:
        request = await db.scalar(
            select(VoiceTurnDeletion)
            .where(VoiceTurnDeletion.id == request_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if request is None or request.status == "COMPLETED":
            await db.commit()
            continue
        try:
            session = await db.get(
                VoiceConversationSession, request.session_id, populate_existing=True
            )
            if session is None or session.status == "ACTIVE":
                request.last_error = "La révocation durable de l’appel doit être confirmée."
            elif session.teardown_error:
                request.last_error = "Fermeture du transport échouée : " + session.teardown_error
            elif not await session_stopped(request.session_id):
                request.last_error = "Un worker audio termine encore son nettoyage."
            else:
                # Round deletion commits; a crash here is safe: retry sees no round.
                await delete_round(request_id)
                request.status = "COMPLETED"
                request.completed_at = datetime.now(timezone.utc)
                request.last_error = None
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def force_hangup(turn_id: UUID) -> dict[str, object] | None:
    """Revoke a whole audio session without erasing its rounds or canonical history.

    Session -> rounds is the admission lock order. Commit before cancelling owners:
    finalizers need these same locks. An already closed session is still fenced and
    its orphan rounds are retired; no live transport registry is required.
    """
    from app.llm import LLMCall
    from app.tools.facade import invalidate_authorization_context
    from app.conversation import publish_round_activity
    from app.conversation import scheduler
    from . import conversation_service, runtime_control
    from .models import VoiceConversationSession, VoiceConversationStatus

    db = get_db()
    session_id = await db.scalar(
        select(ConversationRound.voice_session_id).where(
            ConversationRound.id == turn_id,
        )
    )
    if session_id is None:
        return None
    session = await db.scalar(
        select(VoiceConversationSession)
        .where(
            VoiceConversationSession.id == session_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        return None
    rounds = list(
        (
            await db.scalars(
                select(ConversationRound)
                .where(
                    ConversationRound.voice_session_id == session_id,
                )
                .order_by(ConversationRound.id)
                .with_for_update()
                .execution_options(
                    populate_existing=True,
                )
            )
        ).all()
    )
    if not any(round_.id == turn_id for round_ in rounds):
        return None
    _, agent_id, _ = await conversation_service.message_context(session)
    now = datetime.now(timezone.utc)
    if session.status == VoiceConversationStatus.ACTIVE.value:
        session.status = VoiceConversationStatus.CANCELLED.value
        session.finished_at = now
        session.error = "Appel fermé par raccrochage forcé administratif."
    retired: list[UUID] = []
    for round_ in rounds:
        await invalidate_authorization_context(agent_id, f"voice:{session_id}:round:{round_.id}")
        await invalidate_authorization_context(agent_id, f"round:{round_.id}")
        if round_.status not in ("FROZEN", "CLAIMED", "RUNNING", "WAITING_APPROVAL"):
            continue
        round_.status = "INTERRUPTED"
        round_.finished_at = now
        round_.interrupted_at = now
        round_.last_error = "Traitement audio révoqué par raccrochage forcé administratif."
        round_.encrypted_checkpoint = None
        round_.lease_token = None
        round_.lease_owner = None
        round_.lease_expires_at = None
        retired.append(round_.id)
    calls = list(
        (
            await db.scalars(
                select(LLMCall)
                .where(
                    LLMCall.conversation_round_id.in_([round_.id for round_ in rounds]),
                    LLMCall.status == "running",
                )
                .with_for_update()
            )
        ).all()
    )
    for call in calls:
        call.status = "cancelled"
        call.completed_at = now
    session_status = session.status
    round_ids = [round_.id for round_ in rounds]
    await db.commit()

    # Cancellation is bounded and comes after the durable cross-process barrier.
    globally_stopped = await runtime_control.cancel_session(session_id)
    await db.refresh(session)
    globally_stopped = globally_stopped and session.teardown_error is None
    for round_id in round_ids:
        await scheduler.cancel_round(round_id)
    await conversation_service.publish_session("update", session_id, status=session_status)
    for round_id in retired:
        await publish_round_activity(round_id)
    return {
        "session_id": str(session_id),
        "revoked": True,
        "local_audio_stopped": globally_stopped,
        "audio_stopped": globally_stopped,
        "interrupted_round_ids": [str(round_id) for round_id in retired],
    }


__all__ = ["VoiceTurnConflictError", "delete_turn", "force_hangup", "update_turn_topic"]
