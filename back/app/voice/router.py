"""Monitoring API; live media remains carried by platform bridges."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from core.i18n import tr
from app.agent import current_management_scope

from . import inspection_service, management_service, monitoring_service
from .schemas import (
    VoiceConversationDetail,
    VoiceConversationPage,
    VoiceConversationTopicUpdate,
    VoiceConversationTurnDetail,
)


router = APIRouter(prefix="/voice/conversations", tags=["voice"])
ConversationStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED", "ERROR"]


@router.get("", response_model=VoiceConversationPage)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_voice_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    agent_id: int | None = Query(default=None, gt=0),
    conversation_status: ConversationStatus | None = Query(
        default=None,
        alias="status",
    ),
    active: bool | None = Query(default=None),
    transport_kind: str | None = Query(default=None, max_length=100),
    topic_id: UUID | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=200),
) -> VoiceConversationPage:
    """List durable phone calls without manufacturing Task records."""

    scope = await current_management_scope()
    return await monitoring_service.list_conversations(
        page=page,
        page_size=page_size,
        agent_id=agent_id,
        status=conversation_status,
        active=active,
        transport_kind=transport_kind,
        topic_id=topic_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        agent_ids=scope.agent_ids,
    )


async def _conversation_or_404(conversation_id: UUID) -> VoiceConversationDetail:
    scope = await current_management_scope()
    conversation = await monitoring_service.get_conversation(conversation_id)
    if conversation is None or not scope.allows(conversation.agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )
    return conversation


async def _turn_or_404(turn_id: UUID) -> VoiceConversationTurnDetail:
    scope = await current_management_scope()
    turn = await monitoring_service.get_turn(turn_id)
    if turn is None or not scope.allows(turn.agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )
    return turn


@router.get("/turns/{turn_id}", response_model=VoiceConversationTurnDetail)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_voice_conversation_turn(
    turn_id: UUID,
) -> VoiceConversationTurnDetail:
    """Read one turn with its complete persisted driver exchange."""

    return await _turn_or_404(turn_id)


@router.put("/turns/{turn_id}/topic", response_model=VoiceConversationTurnDetail)
@authorize(privileges=Privileges.TASK_EDIT)
async def update_voice_conversation_turn_topic(
    turn_id: UUID,
    update: VoiceConversationTopicUpdate,
) -> VoiceConversationTurnDetail:
    await _turn_or_404(turn_id)
    updated = await management_service.update_turn_topic(turn_id, update.topic_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )
    turn = await monitoring_service.get_turn(turn_id)
    if turn is None:  # The committed row cannot disappear inside this request.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )
    return turn


@router.get("/turns/{turn_id}/dataset", response_model=dict[str, Any])
@authorize(privileges=Privileges.TASK_ACCESS)
async def export_voice_conversation_turn(turn_id: UUID) -> dict[str, Any]:
    await _turn_or_404(turn_id)
    dataset = await inspection_service.inspect_turn(turn_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )
    return dataset


@router.delete("/turns/{turn_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.TASK_EDIT)
async def delete_voice_conversation_turn(turn_id: UUID) -> None:
    await _turn_or_404(turn_id)
    try:
        deleted = await management_service.delete_turn(turn_id)
    except management_service.VoiceTurnConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("voice.conversation_not_found"),
        )


@router.get("/{conversation_id}", response_model=VoiceConversationDetail)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_voice_conversation(
    conversation_id: UUID,
) -> VoiceConversationDetail:
    """Read one complete phone-call transcript."""

    return await _conversation_or_404(conversation_id)


__all__ = ["router"]
