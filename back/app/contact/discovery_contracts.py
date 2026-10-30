"""Bounded contact-owner evidence and decisions; coordinates are never generated."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactOwnerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["identified", "ignore", "unresolved"]
    display_name: str = Field(default="", max_length=500)
    evidence_quotes: list[str] = Field(default_factory=list, max_length=6)
    messaging_platform: Literal["telegram", "signal", "discord", "matrix", "whatsapp", "one_bot", "nextcloud_talk"] | None = None


class ContactDiscoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["create", "enrich", "ignore", "unresolved", "known"]
    contact_item_id: UUID | None = None
    expected_contact_fingerprint: str | None = None
    expected_directory_fingerprint: str | None = None
    owner: ContactOwnerEvidence | None = None
    decision: dict[str, object] = Field(default_factory=dict)


class ContactMergeCandidate(BaseModel):
    agent_id: int
    source_contact_item_id: UUID
    target_contact_item_id: UUID
    fingerprint: str
    similarity: float
    source: dict[str, object]
    target: dict[str, object]


class ContactDiscoveryRead(BaseModel):
    id: UUID
    agent_id: int
    status: str
    coordinate: dict[str, object]
    contact_item_id: UUID | None
    attempts: int
    last_error: str | None
