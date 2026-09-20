"""Persistent canonical models for internal messaging."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.database import Base, HistoryMixin


AUDIO_TRANSCRIPT_METADATA_KEY = "conversation_audio_transcripts"
CONVERSATION_OUTPUT_PENDING_METADATA_KEY = "conversation_output_pending"
CONVERSATION_ROUND_METADATA_KEY = "conversation_round_id"
TASK_REQUESTED_METADATA_KEY = "task_requested"
DISPLAYED_DOCUMENT_METADATA_KEY = "displayed_document_uri"
TASK_REASONING_EFFORT_METADATA_KEY = "task_reasoning_effort"


def conversation_audio_transcripts(
    metadata: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Normalize the schema-less durable STT projection stored in message metadata."""

    raw_transcripts: object = (metadata or {}).get(AUDIO_TRANSCRIPT_METADATA_KEY)
    if not isinstance(raw_transcripts, dict):
        return {}
    source = cast(dict[object, object], raw_transcripts)
    return {
        str(file_id): str(value).strip()
        for file_id, value in source.items()
        if str(value).strip()
    }


class ConversationType(str, Enum):
    """Medium used by one persisted Messenger room."""

    AUDIO = "audio"
    TEXT = "text"


class Room(HistoryMixin, Base):
    """One room known by a configured messaging connection."""

    __tablename__ = "messenger_rooms"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="group", server_default="group"
    )
    conversation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    topic_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_messenger_room_connection_external",
        ),
    )


class MessengerUser(HistoryMixin, Base):
    """One remote messaging identity known by Galaris."""

    __tablename__ = "messenger_users"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    galaris_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    is_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )

    __table_args__ = (
        CheckConstraint(
            "agent_id IS NULL OR is_ai",
            name="ck_messenger_user_agent_is_ai",
        ),
        UniqueConstraint(
            "tool_id",
            "external_id",
            name="uq_messenger_user_tool_external",
        ),
        UniqueConstraint(
            "tool_id",
            "galaris_user_id",
            name="uq_messenger_user_tool_galaris_user",
        ),
    )


class RoomUser(Base):
    """Current membership of one persisted user in one persisted room."""

    __tablename__ = "messenger_room_users"

    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_rooms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member", index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    custom_label: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    show_last_message: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_read_message_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    # Local unread truth. Unlike provider timestamps, this server-assigned position is
    # monotonic even when an imported message carries an old remote timestamp.
    read_through_position: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'manager', 'member')",
            name="ck_messenger_room_user_role",
        ),
    )


class Interaction(Base):
    """Persistent human interaction independent of messaging transport."""

    __tablename__ = "messenger_interactions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    reference: Mapped[str] = mapped_column(String(12), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", server_default="PENDING", index=True
    )
    agent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    connection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    room_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    free_text: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    prompt_message_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    resolution: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    processing_token: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    processing_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(HistoryMixin, Base):
    """Durable canonical journal used by bridges without remote history APIs."""

    __tablename__ = "messenger_messages"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    journal_position: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
        unique=True,
        index=True,
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    remote_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    messenger_room_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_rooms.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    messenger_user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # The historical messenger_user_id is the conversation counterpart for outbound
    # messages. Keep it for compatibility and persist the actual author separately.
    sender_messenger_user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    counts_as_unread: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    # Frozen identity at ingestion time: changing a Messenger mapping later must not authorize
    # historical messages retroactively.
    requester_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    room_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    topic_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    topic_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    contact_memory_item_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    reply_to: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="accepted", server_default="accepted", index=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "remote_message_id",
            "direction",
            name="uq_messenger_message_remote_direction",
        ),
        Index(
            "ix_messenger_messages_conversation_time",
            "connection_id",
            "room_id",
            "created_at",
        ),
    )

    @property
    def tool_code(self) -> str:
        """Exact Tool code hydrated with this message for resource URI projection."""

        return getattr(self, "_messenger_tool_code", "")

    @tool_code.setter
    def tool_code(self, value: str) -> None:
        self._messenger_tool_code = value

    @property
    def sender(self) -> MessengerUser | None:
        """Hydrated sender loaded by Messenger journal queries."""

        return getattr(self, "_messenger_sender", None)

    @sender.setter
    def sender(self, value: MessengerUser | None) -> None:
        self._messenger_sender = value

    @property
    def recipient(self) -> MessengerUser | None:
        """Hydrated recipient loaded by Messenger journal queries."""

        return getattr(self, "_messenger_recipient", None)

    @recipient.setter
    def recipient(self, value: MessengerUser | None) -> None:
        self._messenger_recipient = value

    @property
    def room(self) -> Room | None:
        """Hydrated room loaded by Messenger journal queries."""

        return getattr(self, "_messenger_room", None)

    @room.setter
    def room(self, value: Room | None) -> None:
        self._messenger_room = value

    @property
    def files(self) -> list[File]:
        """Hydrated remote file metadata in message order."""

        return getattr(self, "_messenger_files", [])

    @files.setter
    def files(self, value: list[File]) -> None:
        self._messenger_files = value

    @property
    def is_ai(self) -> bool:
        """Return whether the hydrated sender represents an AI identity."""

        return bool(self.sender and self.sender.is_ai)

    @property
    def conversation_text(self) -> str:
        """Return text plus durable STT results for model-facing conversation history."""

        transcripts = conversation_audio_transcripts(self.metadata_)
        if not transcripts:
            return self.text
        sections = [self.text.strip()] if self.text.strip() else []
        for file in self.files:
            transcript = transcripts.get(str(file.id), "")
            if not transcript:
                continue
            name = file.name.strip() or str(file.id)
            sections.append(f"[Audio transcript: {name}]\n{transcript}")
        return "\n\n".join(sections) or self.text


class File(HistoryMixin, Base):
    """Metadata for one remote attachment; file content stays at the provider."""

    __tablename__ = "messenger_files"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_identifier: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    name: Mapped[str] = mapped_column(
        String(512), nullable=False, default="", server_default=""
    )
    mime_type: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other", server_default="other"
    )
    remote_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_identifier",
            name="uq_messenger_file_connection_external",
        ),
    )


class Attachment(Base):
    """Ordered many-to-many relation between messages and remote files."""

    __tablename__ = "messenger_message_files"

    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class ListenerState(Base):
    """Persistent cursor and health information for one pull-based bridge connection."""

    __tablename__ = "messenger_listener_state"

    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cursor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reconnect_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Capability(str, Enum):
    """Optional capability a messaging bridge can declare."""

    SEND = "send"  # Room or user text messages.
    HISTORY = "history"  # Conversation history.
    UNREAD = "unread"  # Unread messages.
    REACT = "react"  # Outbound emoji reactions.
    FILES = "files"  # Attachments and file sharing.
    ROOMS = "rooms"  # Room listing and management.
    MEMBERS = "members"  # Participant management.
    TYPING = "typing"  # Typing and presence indicators.
    SEARCH_USERS = "search_users"  # User search.
    VOICE_NOTES = "voice_notes"  # Native asynchronous voice notes.


def kind_from_mime(mime: str) -> Literal["image", "audio", "video", "document", "other"]:
    """Infer an attachment kind from its MIME type."""
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "image"
    # OGG is a container but messaging platforms almost always use it for Opus voice notes.
    if m.startswith("audio/") or m in ("application/ogg", "application/x-ogg"):
        return "audio"
    if m.startswith("video/"):
        return "video"
    if (
        m.startswith("text/")
        or m in ("application/pdf", "application/json")
        or "word" in m
        or "spreadsheet" in m
        or "excel" in m
        or "presentation" in m
        or "document" in m
        or "csv" in m
    ):
        return "document"
    return "other"
