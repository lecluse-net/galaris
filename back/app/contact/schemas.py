"""HTTP contracts for canonical contacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactIdentityRead(BaseModel):
    id: UUID
    kind: Literal["messenger", "galaris_user"]
    namespace: str
    external_id: str
    display_name: str
    galaris_user_id: int | None


class ContactRead(BaseModel):
    memory_item_id: UUID
    owner_agent_id: int
    display_name: str
    memory_title: str
    identities: list[ContactIdentityRead]
    linked_memory_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime | None


class ContactPage(BaseModel):
    items: list[ContactRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool


class ContactMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_contact_item_id: UUID


class ContactMergeResult(BaseModel):
    contact: ContactRead
    rewired: dict[str, int]


class ContactForgetResult(BaseModel):
    forgotten_contact_item_id: UUID
    forgotten_memories: int = Field(ge=0)
    resources_deleted: int = Field(ge=0)
    cleared: dict[str, int]


__all__ = [
    "ContactIdentityRead",
    "ContactForgetResult",
    "ContactMergeRequest",
    "ContactMergeResult",
    "ContactPage",
    "ContactRead",
]
