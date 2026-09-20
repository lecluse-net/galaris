"""Stable DTOs for native applications built on canonical Messenger data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


def resolve_effective_topic_id(
    message_topic_id: UUID | None,
    *,
    topic_overridden: bool,
    room_topic_id: UUID | None,
) -> UUID | None:
    """Resolve one message Topic without losing its persisted assignment origin."""

    if topic_overridden:
        return message_topic_id
    return room_topic_id or message_topic_id


def _empty_files() -> list[NativeMessengerFile]:
    return []


def _empty_members() -> list[NativeMessengerMember]:
    return []


class NativeMessengerAgent(BaseModel):
    agent_id: int
    connection_id: int
    code: str
    display_name: str
    active: bool


class NativeMessengerMember(BaseModel):
    id: UUID
    external_id: str
    display_name: str
    avatar_url: str | None = None
    is_ai: bool
    agent_id: int | None = None
    role: str = "member"
    joined_at: datetime | None = None
    muted: bool = False


class NativeMessengerFile(BaseModel):
    id: UUID
    uri: str
    name: str
    mime_type: str
    size_bytes: int | None = None
    kind: str


class NativeInteractionOption(BaseModel):
    id: str
    label: str


class NativeMessengerInteraction(BaseModel):
    """Human-visible choice state, without domain payloads or processing tokens."""

    id: UUID
    reference: str
    title: str
    body: str
    options: list[NativeInteractionOption]
    free_text: bool
    status: str
    expires_at: datetime
    selected_option_id: str | None = None
    can_answer: bool = False


class NativeMessengerMessage(BaseModel):
    id: UUID
    external_id: str
    room_id: UUID
    direction: str
    text: str
    topic_id: UUID | None = None
    topic_overridden: bool = False
    sender: NativeMessengerMember | None = None
    reply_to: str | None = None
    files: list[NativeMessengerFile] = Field(default_factory=_empty_files)
    status: str
    created_at: datetime
    is_mine: bool = False
    interaction: NativeMessengerInteraction | None = None


class NativeMessengerRoom(BaseModel):
    id: UUID
    external_id: str
    label: str
    kind: str
    conversation_type: str
    topic_id: UUID | None = None
    connection_id: int
    agent_id: int
    agent_name: str
    agent_active: bool
    source: str | None = None
    messenger_label: str
    messenger_active: bool
    writable: bool = False
    role: str
    muted: bool
    unread_count: int = 0
    show_last_message: bool = True
    archived: bool = False
    last_message: NativeMessengerMessage | None = None
    members: list[NativeMessengerMember] = Field(default_factory=_empty_members)


class NativeMessengerRoomPage(BaseModel):
    items: list[NativeMessengerRoom]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)


class NativeMessengerMessagePage(BaseModel):
    items: list[NativeMessengerMessage]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    provider_history: bool = False
    history_has_more: bool = False
    history_next_cursor: str | None = None


class MessageResourcePreview(BaseModel):
    uri: str
    deleted: bool = False
    kind: Literal[
        "document",
        "memory",
        "task",
        "text",
        "voice",
        "goal",
        "goal_cycle",
        "process",
        "skill",
        "file",
        "resource",
        "web",
        "youtube",
    ]
    title: str
    subtitle: str = ""
    description: str = ""
    media_type: str = "text/plain"
    content: str | None = None
    content_format: Literal["html", "markdown", "text", "json", "none"] = "none"
    truncated: bool = False
    image_available: bool = False
    download_available: bool = False
    open_mode: Literal["inline", "external"] = "inline"
    external_url: str | None = None
    embed_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])


class NativeMessengerFileAccess(BaseModel):
    id: UUID
    room_id: UUID
    connection_id: int
    name: str
    mime_type: str
    size_bytes: int | None = None
    kind: str


class NativeMessengerConnection(BaseModel):
    connection_id: int
    tool_id: int
    tool_code: str
    agent_id: int
    agent_code: str
    agent_name: str
    active: bool


class NativeMessengerIdentityMapping(BaseModel):
    tool_id: int
    tool_code: str
    tool_label: str
    source: str
    external_id: str | None = None
    display_name: str | None = None


class ChatViewerAgent(BaseModel):
    agent_id: int
    code: str
    display_name: str


__all__ = [
    "NativeInteractionOption",
    "NativeMessengerInteraction",
    "NativeMessengerAgent",
    "ChatViewerAgent",
    "NativeMessengerConnection",
    "NativeMessengerFile",
    "NativeMessengerFileAccess",
    "NativeMessengerMember",
    "NativeMessengerIdentityMapping",
    "NativeMessengerMessage",
    "NativeMessengerMessagePage",
    "MessageResourcePreview",
    "NativeMessengerRoom",
    "NativeMessengerRoomPage",
    "resolve_effective_topic_id",
]
