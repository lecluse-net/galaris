"""Typed contracts for the IMAP/SMTP Mail bridge."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


MailSecurity = Literal["tls", "starttls"]
MailDeliveryStatus = Literal[
    "pending_approval",
    "claimed",
    "submitting",
    "sent",
    "rejected",
    "uncertain",
    "error",
]
MailDeliveryKind = Literal["send", "reply", "forward"]


class MailEndpointConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    security: MailSecurity
    username: str = Field(min_length=1, max_length=320)
    password: SecretStr


class MailConnectionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_id: int = Field(gt=0)
    agent_id: int = Field(gt=0)
    email_address: EmailStr
    display_name: str = Field(default="", max_length=200)
    agent_label: str = Field(default="", max_length=255)
    imap: MailEndpointConfig
    smtp: MailEndpointConfig
    sent_mailbox: str | None = Field(default=None, max_length=512)
    trash_mailbox: str | None = Field(default=None, max_length=512)
    connect_timeout_s: float = Field(ge=1, le=60)
    operation_timeout_s: float = Field(ge=1, le=120)
    poll_interval_s: float = Field(default=60, ge=5, le=86_400)
    max_attachment_bytes: int = Field(ge=1, le=25 * 1024 * 1024)
    max_total_attachment_bytes: int = Field(ge=1, le=50 * 1024 * 1024)
    approval_required: bool = False
    approver_user_id: int | None = Field(default=None, gt=0)


class MailMessageRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    mailbox: str = Field(min_length=1, max_length=512)
    uid_validity: int = Field(gt=0)
    uid: int = Field(gt=0)

    def encode(self) -> str:
        payload = self.model_dump_json().encode("utf-8")
        return "m1_" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "MailMessageRef":
        if not value.startswith("m1_") or len(value) > 2048:
            raise ValueError("Invalid or unsupported mail message reference")
        encoded = value[3:]
        padding = "=" * (-len(encoded) % 4)
        try:
            payload = base64.urlsafe_b64decode(encoded + padding)
            decoded = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid mail message reference") from exc
        return cls.model_validate(decoded)


class MailboxInfo(BaseModel):
    name: str
    delimiter: str | None = None
    attributes: list[str] = Field(default_factory=list[str])
    role: Literal["inbox", "sent", "trash", "drafts", "junk", "archive"] | None = None
    selectable: bool = True


class MailAttachment(BaseModel):
    part_id: str
    filename: str
    media_type: str = "application/octet-stream"
    size: int = Field(ge=0)
    content_id: str | None = None
    uri: str


class MailMessageSummary(BaseModel):
    ref: str
    subject: str = ""
    from_name: str = ""
    from_address: str = ""
    to_addresses: list[str] = Field(default_factory=list[str])
    date: datetime | None = None
    message_id: str | None = None
    seen: bool = False
    flagged: bool = False
    has_attachments: bool = False


class MailMessageDetail(MailMessageSummary):
    cc_addresses: list[str] = Field(default_factory=list[str])
    reply_to_addresses: list[str] = Field(default_factory=list[str])
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list[str])
    body: str = ""
    body_format: Literal["plain", "html-converted", "empty"] = "empty"
    body_start: int = Field(ge=0)
    body_end: int = Field(ge=0)
    body_total: int = Field(ge=0)
    next_body_offset: int | None = Field(default=None, ge=0)
    attachments: list[MailAttachment] = Field(default_factory=list[MailAttachment])
    untrusted_content: bool = True


class MailSearchPage(BaseModel):
    mailbox: str
    uid_validity: int = Field(gt=0)
    messages: list[MailMessageSummary] = Field(default_factory=list[MailMessageSummary])
    next_cursor: str | None = None
    truncated: bool = False


class MailPollBatch(BaseModel):
    mailbox: str = "INBOX"
    uid_validity: int = Field(gt=0)
    latest_uid: int = Field(ge=0)
    messages: list[MailMessageSummary] = Field(default_factory=list[MailMessageSummary])
    truncated: bool = False


class MailConnectionStatus(BaseModel):
    connection_id: int
    email_address: EmailStr
    imap_ok: bool
    smtp_ok: bool
    mailboxes: int = Field(ge=0)
    sent_mailbox: str | None = None
    trash_mailbox: str | None = None


class MailMutationResult(BaseModel):
    ref: str
    state: str
    seen: bool | None = None
    flagged: bool | None = None
    new_ref: str | None = None


class MailSendReceipt(BaseModel):
    delivery_id: UUID
    status: MailDeliveryStatus
    message_id: str
    accepted_recipients: int = Field(ge=0)
    rejected_recipients: int = Field(ge=0)
    disclosure_version: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MailSearchQuery:
    mailbox: str
    text: str = ""
    subject: str = ""
    from_address: str = ""
    to_address: str = ""
    since: str | None = None
    before: str | None = None
    unread: bool | None = None
    flagged: bool | None = None
    has_attachments: bool | None = None
    limit: int = 20
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class OutgoingAttachment:
    filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class OutgoingMail:
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    body: str
    html_body: str | None
    attachments: tuple[OutgoingAttachment, ...]
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()


class ImapOperations(Protocol):
    def status(self) -> tuple[list[MailboxInfo], int]: ...
    def search(self, query: MailSearchQuery) -> MailSearchPage: ...
    def poll_inbox(self, *, after_uid: int | None, limit: int) -> MailPollBatch: ...
    def get_message(
        self, ref: MailMessageRef, *, body_offset: int, body_limit: int
    ) -> MailMessageDetail: ...
    def set_flags(
        self,
        ref: MailMessageRef,
        *,
        seen: bool | None,
        flagged: bool | None,
    ) -> MailMutationResult: ...
    def move(self, ref: MailMessageRef, mailbox: str) -> MailMutationResult: ...
    def get_attachment(self, ref: MailMessageRef, part_id: str) -> OutgoingAttachment: ...
    def message_id_exists(self, mailbox: str, message_id: str) -> bool: ...


class SmtpOperations(Protocol):
    def status(self) -> None: ...
    def send(self, message: bytes, *, sender: str, recipients: tuple[str, ...]) -> tuple[int, int]: ...


__all__ = [
    "ImapOperations",
    "MailAttachment",
    "MailConnectionConfig",
    "MailConnectionStatus",
    "MailDeliveryStatus",
    "MailDeliveryKind",
    "MailEndpointConfig",
    "MailboxInfo",
    "MailMessageDetail",
    "MailMessageRef",
    "MailMessageSummary",
    "MailPollBatch",
    "MailMutationResult",
    "MailSearchPage",
    "MailSearchQuery",
    "MailSecurity",
    "MailSendReceipt",
    "OutgoingAttachment",
    "OutgoingMail",
    "SmtpOperations",
]
