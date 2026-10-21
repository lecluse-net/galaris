"""HTTP contracts for canonical contacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=500)
    split_identity_ids: list[UUID] = Field(default_factory=list[UUID], max_length=500)
    expected_identity_ids: list[UUID] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_identity_snapshot(self) -> ContactUpdate:
        if self.split_identity_ids and self.expected_identity_ids is None:
            raise ValueError("The current identity snapshot is required to split identities.")
        return self

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=500)
    email: EmailStr

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


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
    "ContactCreate",
    "ContactForgetResult",
    "ContactMergeRequest",
    "ContactMergeResult",
    "ContactPage",
    "ContactRead",
    "ContactUpdate",
]
