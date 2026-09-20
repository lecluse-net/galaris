"""Monitoring API for priority text conversations."""

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
    ConversationMessagePage,
    ConversationRoundDetail,
    ConversationTopicUpdate,
    ConversationDeliveryResolve,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])
ConversationStatus = Literal["IDLE", "READY", "RUNNING"]


@router.get("/messages", response_model=ConversationMessagePage)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_conversation_messages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    agent_id: int | None = Query(default=None, gt=0),
    conversation_status: ConversationStatus | None = Query(default=None, alias="status"),
    errors_only: bool = Query(default=False),
    active: bool | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    channel_kind: str | None = Query(default=None, max_length=100),
    topic_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
) -> ConversationMessagePage:
    scope = await current_management_scope()
    return await monitoring_service.list_messages(
        page=page,
        page_size=page_size,
        agent_id=agent_id,
        status=conversation_status,
        errors_only=errors_only,
        active=active,
        date_from=date_from,
        date_to=date_to,
        channel_kind=channel_kind,
        topic_id=topic_id,
        search=search,
        agent_ids=scope.agent_ids,
    )


async def _round_or_404(round_id: UUID) -> ConversationRoundDetail:
    scope = await current_management_scope()
    round_ = await monitoring_service.get_round(round_id)
    if round_ is None or not scope.allows(round_.agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("conversation.round_not_found"),
        )
    return round_


@router.get("/rounds/{round_id}", response_model=ConversationRoundDetail)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_conversation_round(round_id: UUID) -> ConversationRoundDetail:
    return await _round_or_404(round_id)


@router.put("/rounds/{round_id}/topic", response_model=ConversationRoundDetail)
@authorize(privileges=Privileges.TASK_EDIT)
async def update_conversation_round_topic(
    round_id: UUID,
    update: ConversationTopicUpdate,
) -> ConversationRoundDetail:
    await _round_or_404(round_id)
    updated = await management_service.update_round_topic(round_id, update.topic_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("conversation.round_not_found"),
        )
    round_ = await monitoring_service.get_round(round_id)
    if round_ is None:  # The committed row cannot disappear inside this request.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("conversation.round_not_found"),
        )
    return round_


@router.get("/rounds/{round_id}/dataset", response_model=dict[str, Any])
@authorize(privileges=Privileges.TASK_ACCESS)
async def export_conversation_round(round_id: UUID) -> dict[str, Any]:
    await _round_or_404(round_id)
    dataset = await inspection_service.inspect_round(round_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("conversation.round_not_found"),
        )
    return dataset


@router.post("/rounds/{round_id}/delivery-resolution", response_model=ConversationRoundDetail)
@authorize(privileges=Privileges.TASK_EDIT)
async def resolve_conversation_delivery(
    round_id: UUID, resolution: ConversationDeliveryResolve,
) -> ConversationRoundDetail:
    await _round_or_404(round_id)
    scope = await current_management_scope()
    try:
        if resolution.notification is None:
            await management_service.resolve_unknown_delivery(
                round_id, actor_user_id=scope.user_id,
                decision=resolution.decision, evidence=resolution.evidence,
            )
        else:
            target = resolution.notification
            await management_service.resolve_unknown_notification(
                round_id, kind=target.kind, link_id=target.link_id,
                attempt_number=target.attempt_number, actor_user_id=scope.user_id,
                decision=resolution.decision, evidence=resolution.evidence,
            )
    except management_service.DeliveryResolutionConflict as exc:
        raise HTTPException(status_code=409, detail=await tr("conversation.delivery_resolution_conflict")) from exc
    return await _round_or_404(round_id)


@router.delete("/rounds/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.TASK_EDIT)
async def delete_conversation_round(round_id: UUID) -> None:
    await _round_or_404(round_id)
    deleted = await management_service.delete_round(round_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("conversation.round_not_found"),
        )


__all__ = ["router"]
