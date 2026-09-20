"""Authenticated read-only monitoring routes for Dream."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope

from . import monitoring_service
from .schemas import (
    DreamOverview,
    DreamReceiptDetail,
    DreamReceiptPage,
    DreamRuntimeView,
    DreamTopicAssignmentAudit,
    TopicAssignmentSubjectKind,
)


router = APIRouter(prefix="/dream", tags=["dream"])
ReceiptStatus = Literal["running", "retry", "success", "error"]


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global Agent management is required",
        )


@router.get("/runtime", response_model=DreamRuntimeView)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_dream_runtime() -> DreamRuntimeView:
    await _require_global_scope()
    return await monitoring_service.get_runtime()


@router.get("/overview", response_model=DreamOverview)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_dream_overview() -> DreamOverview:
    await _require_global_scope()
    return await monitoring_service.get_overview()


@router.get("/receipts", response_model=DreamReceiptPage)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_dream_receipts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    receipt_status: ReceiptStatus | None = Query(default=None, alias="status"),
    active: bool | None = Query(default=None),
    date_from: date | None = None,
    date_to: date | None = None,
    mechanism: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=200),
) -> DreamReceiptPage:
    await _require_global_scope()
    return await monitoring_service.list_receipts(
        page=page,
        page_size=page_size,
        status=receipt_status,
        active=active,
        date_from=date_from,
        date_to=date_to,
        mechanism=mechanism,
        search=search,
    )


@router.get("/topic-assignment", response_model=DreamTopicAssignmentAudit)
@authorize(
    privileges=[
        Privileges.TASK_ACCESS,
        Privileges.CHAT_ACCESS,
        Privileges.TOPIC_ACCESS,
        Privileges.TOPIC_EDIT,
    ]
)
async def read_topic_assignment(
    topic_id: UUID,
    subject_kind: TopicAssignmentSubjectKind,
    subject_id: UUID,
) -> DreamTopicAssignmentAudit:
    """Explain whether the displayed Topic came from Dream or a human."""

    scope = await current_management_scope()
    agent_id = await monitoring_service.get_topic_assignment_agent_id(
        subject_kind=subject_kind,
        subject_id=subject_id,
    )
    if not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail="Topic assignment not found")

    return await monitoring_service.get_topic_assignment_audit(
        topic_id=topic_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
    )


@router.get("/receipts/{receipt_id}", response_model=DreamReceiptDetail)
@authorize(privileges=Privileges.TASK_ACCESS)
async def read_dream_receipt(receipt_id: UUID) -> DreamReceiptDetail:
    await _require_global_scope()
    receipt = await monitoring_service.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dream receipt not found.",
        )
    return receipt


__all__ = ["router"]
