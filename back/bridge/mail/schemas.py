"""HTTP schemas for Mail connection and outbound-journal administration."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .contracts import MailConnectionStatus, MailDeliveryKind, MailDeliveryStatus


class MailConnectionTest(BaseModel):
    connection_id: int
    status: MailConnectionStatus


class MailStatus(BaseModel):
    enabled: bool


class MailDeliveryListItem(BaseModel):
    id: UUID
    connection_id: int | None
    agent_id: int | None
    agent_label: str
    sender_address: str
    delivery_kind: MailDeliveryKind
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    subject: str
    body_preview: str
    attachment_count: int = Field(ge=0)
    status: MailDeliveryStatus
    approval_required: bool
    approver_user_id: int | None
    approver_label: str | None
    reviewed_by_user_id: int | None
    reviewed_by_label: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    accepted_recipients: int = Field(ge=0)
    rejected_recipients: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    can_review: bool = False


class MailDeliveryDetail(MailDeliveryListItem):
    body: str
    html_body: str | None
    attachments: list[dict[str, object]] = Field(
        default_factory=list[dict[str, object]]
    )
    message_id: str
    disclosure_version: str
    smtp_response_code: int | None


class MailDeliveryPage(BaseModel):
    items: list[MailDeliveryListItem] = Field(
        default_factory=list[MailDeliveryListItem]
    )
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)


class MailDeliveryAgentOption(BaseModel):
    id: int
    label: str


class MailApproverOption(BaseModel):
    id: int
    label: str
    email: str


class MailDeliveryReview(BaseModel):
    reason: str = Field(default="", max_length=2_000)


__all__ = [
    "MailConnectionTest",
    "MailStatus",
    "MailApproverOption",
    "MailDeliveryAgentOption",
    "MailDeliveryDetail",
    "MailDeliveryListItem",
    "MailDeliveryPage",
    "MailDeliveryReview",
]
