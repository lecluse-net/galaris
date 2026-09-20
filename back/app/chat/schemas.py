"""HTTP contracts for the Chat application."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.contracts import ReasoningEffort
from app.messenger import (
    ChatViewerAgent,
    NativeMessengerAgent,
    NativeMessengerMessage,
    NativeMessengerMessagePage,
    NativeMessengerIdentityMapping,
    NativeMessengerRoom,
    NativeMessengerRoomPage,
)


class ChatStatus(BaseModel):
    enabled: bool
    chat_enabled: bool
    max_attachment_bytes: int = Field(ge=1)
    page_sizes: list[int] = Field(default_factory=lambda: [10, 20, 50, 100, 500])


class RecipientCatalog(BaseModel):
    agents: list[NativeMessengerAgent]


ChatCommandCode = Literal[
    "task",
    "exec",
    "plan",
    "briefing",
    "standard",
    "high",
    "effort",
    "approve",
]

class ChatCommandCatalog(BaseModel):
    commands: list[ChatCommandCode]


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_id: int = Field(gt=0)
    label: str | None = Field(default=None, min_length=1, max_length=500)
    topic_id: UUID | None = None
    show_last_message: bool = True


class RoomPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=500)
    show_last_message: bool


class RoomTopicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: UUID | None = None


class IdentityMappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=512)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    text: str = Field(min_length=1, max_length=100_000)
    language: str = Field(default="", max_length=10)
    topic_id: UUID | None = None
    reply_to_message_id: UUID | None = None
    reasoning_effort_override: ReasoningEffort | None = None
    task_requested: bool = False
    displayed_document_id: UUID | None = None


class InteractionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=500)


class ConversationDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)


class MessageTopicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: UUID
    scope: Literal["message", "following_same_topic"] = "message"


class MessageTopicUpdateResult(BaseModel):
    updated_messages: int = Field(ge=0)


class ReadMarker(BaseModel):
    message_id: UUID | None = None


class MuteUpdate(BaseModel):
    muted: bool


class ArchiveUpdate(BaseModel):
    archived: bool


class MutationResult(BaseModel):
    ok: bool = True


class ChatInboxSummary(BaseModel):
    unread_count: int = Field(ge=0)


class PushConfiguration(BaseModel):
    available: bool
    public_key: str = ""


class PushSubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=4_096)
    expiration_time: float | None = Field(default=None, ge=0)
    keys: PushSubscriptionKeys


class PushSubscriptionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=4_096)


class PushSubscriptionRead(BaseModel):
    id: UUID
    enabled: bool


class HtmlPreviewTicket(BaseModel):
    url: str
    expires_in: int = Field(gt=0)


class DictationResult(BaseModel):
    text: str


class MessageSpeechStatus(BaseModel):
    available_agent_ids: list[int]


class EmojiUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emoji: str = Field(min_length=1, max_length=64)


class FrequentEmojiList(BaseModel):
    items: list[str]
    limit: int = 25


class WebRtcOffer(BaseModel):
    sdp: str = Field(min_length=1, max_length=1_000_000)
    type: Literal["offer"] = "offer"
    language: str = Field(default="fr", min_length=2, max_length=10)


class WebRtcIceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str | None = Field(
        default=None,
        max_length=16_384,
        pattern=r"^candidate:.+",
    )
    sdp_mid: str | None = Field(default=None, max_length=128)
    sdp_m_line_index: int | None = Field(default=None, ge=0, le=1_024)


class WebRtcIceCandidateBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[WebRtcIceCandidate] = Field(min_length=1, max_length=50)


class WebRtcAnswer(BaseModel):
    call_id: str
    sdp: str
    type: str
    created: bool


class ActiveCall(BaseModel):
    call_id: str
    started_at: float


class WebRtcIceServer(BaseModel):
    urls: list[str]
    username: str | None = None
    credential: str | None = None


class VoiceCallStatus(BaseModel):
    available: bool
    ice_servers: list[WebRtcIceServer]


__all__ = [
    "ActiveCall",
    "ChatStatus",
    "ChatInboxSummary",
    "ChatCommandCatalog",
    "ChatCommandCode",
    "ChatViewerAgent",
    "DictationResult",
    "EmojiUse",
    "FrequentEmojiList",
    "IdentityMappingUpdate",
    "HtmlPreviewTicket",
    "MessageCreate",
    "MessageSpeechStatus",
    "MessageTopicUpdate",
    "MessageTopicUpdateResult",
    "MutationResult",
    "PushConfiguration",
    "PushSubscriptionCreate",
    "PushSubscriptionDelete",
    "PushSubscriptionKeys",
    "PushSubscriptionRead",
    "MuteUpdate",
    "NativeMessengerMessage",
    "NativeMessengerMessagePage",
    "NativeMessengerIdentityMapping",
    "NativeMessengerRoom",
    "NativeMessengerRoomPage",
    "ReadMarker",
    "ReasoningEffort",
    "RecipientCatalog",
    "RoomCreate",
    "RoomPreferencesUpdate",
    "RoomTopicUpdate",
    "WebRtcAnswer",
    "WebRtcIceCandidate",
    "WebRtcIceCandidateBatch",
    "WebRtcIceServer",
    "WebRtcOffer",
    "VoiceCallStatus",
]
