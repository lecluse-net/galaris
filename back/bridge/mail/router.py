"""Administrative Mail connection, journal, and approval routes."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger

from core.authorize import Privileges, authorize
from core.user import user_service
from app.agent import current_management_scope
from app.connection.facade import get_connection, has_any_active_tool_connection

from .assertions import MailApproverAssertion
from .schemas import (
    MailApproverOption,
    MailConnectionTest,
    MailDeliveryAgentOption,
    MailDeliveryDetail,
    MailDeliveryPage,
    MailDeliveryReview,
    MailStatus,
)
from .contracts import MailSendReceipt
from . import service


router = APIRouter(prefix="/mail", tags=["mail"])


def _current_user_id() -> int:
    user_id = user_service.get_current_user_id()
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user_id


def _review_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.MailDeliveryNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mail delivery not found")
    if isinstance(exc, service.MailApprovalForbiddenError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the configured approver can review this Mail delivery",
        )
    if isinstance(exc, service.MailDeliveryStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/status", response_model=MailStatus)
@authorize(privileges=Privileges.CONNECTION_ACCESS)
async def read_mail_status() -> MailStatus:
    scope = await current_management_scope()
    return MailStatus(
        enabled=await has_any_active_tool_connection(
            "mail", agent_ids=scope.agent_ids
        )
    )


@router.get("/outbound", response_model=MailDeliveryPage)
@authorize(privileges=Privileges.CONNECTION_ACCESS)
async def list_outbound_mail(
    scope: Literal["pending", "history", "all"] = Query(default="history"),
    agent_id: int | None = Query(default=None, gt=0),
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> MailDeliveryPage:
    management_scope = await current_management_scope()
    if agent_id is not None and not management_scope.allows(agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await service.list_deliveries(
        current_user_id=_current_user_id(),
        scope=scope,
        agent_id=agent_id,
        search_text=search,
        offset=offset,
        limit=limit,
        agent_ids=management_scope.agent_ids,
    )


@router.get("/outbound/agents", response_model=list[MailDeliveryAgentOption])
@authorize(privileges=Privileges.CONNECTION_ACCESS)
async def list_outbound_mail_agents() -> list[MailDeliveryAgentOption]:
    scope = await current_management_scope()
    return await service.list_delivery_agents(agent_ids=scope.agent_ids)


@router.get("/approvers", response_model=list[MailApproverOption])
@authorize(
    privileges=[
        Privileges.CONNECTION_ACCESS,
        Privileges.TOOL_EDIT,
        Privileges.CONNECTION_EDIT,
    ]
)
async def list_mail_approvers() -> list[MailApproverOption]:
    return await service.list_approvers()


@router.get("/outbound/{delivery_id}", response_model=MailDeliveryDetail)
@authorize(privileges=Privileges.CONNECTION_ACCESS)
async def read_outbound_mail(delivery_id: UUID) -> MailDeliveryDetail:
    try:
        scope = await current_management_scope()
        return await service.get_delivery(
            delivery_id,
            current_user_id=_current_user_id(),
            agent_ids=scope.agent_ids,
        )
    except service.MailDeliveryNotFoundError as exc:
        raise _review_error(exc) from exc


@router.post("/outbound/{delivery_id}/approve", response_model=MailSendReceipt)
@authorize(
    privileges=Privileges.CONNECTION_ACCESS,
    assertion=MailApproverAssertion,
)
async def approve_outbound_mail(delivery_id: UUID) -> MailSendReceipt:
    try:
        scope = await current_management_scope()
        return await service.approve_delivery(
            delivery_id,
            current_user_id=_current_user_id(),
            agent_ids=scope.agent_ids,
        )
    except (
        service.MailDeliveryNotFoundError,
        service.MailApprovalForbiddenError,
        service.MailDeliveryStateError,
        ValueError,
    ) as exc:
        raise _review_error(exc) from exc


@router.post("/outbound/{delivery_id}/reject", response_model=MailDeliveryDetail)
@authorize(
    privileges=Privileges.CONNECTION_ACCESS,
    assertion=MailApproverAssertion,
)
async def reject_outbound_mail(
    delivery_id: UUID,
    review: MailDeliveryReview,
) -> MailDeliveryDetail:
    try:
        scope = await current_management_scope()
        return await service.reject_delivery(
            delivery_id,
            current_user_id=_current_user_id(),
            reason=review.reason,
            agent_ids=scope.agent_ids,
        )
    except (
        service.MailDeliveryNotFoundError,
        service.MailApprovalForbiddenError,
        service.MailDeliveryStateError,
    ) as exc:
        raise _review_error(exc) from exc


@router.post("/connections/{connection_id}/test", response_model=MailConnectionTest)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def test_connection(connection_id: int) -> MailConnectionTest:
    try:
        connection = await get_connection(connection_id)
        scope = await current_management_scope()
        if connection is None or not scope.allows(connection.agent_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        result = await service.test_connection(connection_id)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "Mail connection test failed for connection {} (error_type={})",
            connection_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The IMAP or SMTP server rejected the connection test",
        ) from exc
    return MailConnectionTest(connection_id=connection_id, status=result)


__all__ = ["router"]
