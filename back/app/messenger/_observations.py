"""Private provider observations consumed by the Messenger synchronization boundary.

These values are never canonical application entities. Bridges create them from remote
payloads, then :mod:`app.messenger` immediately persists them as ``Messenger*`` rows. They
must not be exported from the package or returned to another application domain.
"""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservedMessengerUser(BaseModel):
    """One identity as reported by a remote messaging provider."""

    id: str = ""
    display_name: str = ""
    agent_id: int | None = None
    is_ai: bool = False
    connection_id: int | None = None
    tool_id: int | None = None

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    @model_validator(mode="after")
    def agent_is_ai(self) -> Self:
        if self.agent_id is not None:
            object.__setattr__(self, "is_ai", True)
        return self


class ObservedMessengerRoom(BaseModel):
    """One room snapshot as reported by a remote messaging provider."""

    id: str = ""
    local_id: UUID | None = None
    label: str = ""
    kind: Literal["direct", "group"] = "group"
    conversation_type: Literal["audio", "text"] = "text"
    users: list[ObservedMessengerUser] = Field(
        default_factory=list[ObservedMessengerUser]
    )
    users_complete: bool = False
    connection_id: int | None = None
    tool_id: int | None = None

    model_config = ConfigDict(extra="ignore")

class ObservedMessengerFile(BaseModel):
    """Remote file metadata observed without downloading its content."""

    id: str = ""
    local_id: UUID | None = None
    name: str = ""
    mime: str = ""
    url: str | None = None
    size: int | None = None
    kind: Literal["image", "audio", "video", "document", "other"] = "other"
    text: str = ""

    model_config = ConfigDict(extra="ignore")

class ObservedMessengerMessage(BaseModel):
    """One provider message waiting at the private persistence boundary."""

    id: str = ""
    local_id: UUID | None = None
    platform: str = ""
    tool_id: int | None = None
    sender: ObservedMessengerUser | None = None
    recipient: ObservedMessengerUser | None = None
    room: ObservedMessengerRoom | None = None
    text: str = ""
    attachments: list[ObservedMessengerFile] = Field(
        default_factory=list[ObservedMessengerFile]
    )
    topic_id: UUID | None = None
    topic_overridden: bool = False
    reply_to: str | None = None
    time: int = 0

    model_config = ConfigDict(extra="ignore")

    @property
    def is_ai(self) -> bool:
        return bool(self.sender and self.sender.is_ai)
