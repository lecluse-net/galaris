"""Public and model-output contracts for thematic dossiers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision: int
    title: str
    description: str
    keywords: list[str]
    memory_item_id: UUID | None
    created_at: datetime
    updated_at: datetime | None


class TopicRef(BaseModel):
    """Small Topic identity used by execution-monitoring badges."""

    id: UUID
    title: str


class TopicRelatedAgent(BaseModel):
    id: int
    name: str


class TopicRelatedTeam(BaseModel):
    id: int
    name: str


class TopicRelatedUser(BaseModel):
    id: UUID
    display_name: str
    user_id: str


class TopicRelatedDocument(BaseModel):
    id: UUID
    title: str
    filename: str | None


def _empty_related_agents() -> list[TopicRelatedAgent]:
    return []


def _empty_related_users() -> list[TopicRelatedUser]:
    return []


def _empty_related_documents() -> list[TopicRelatedDocument]:
    return []


class TopicMonthlyUsage(TopicRead):
    inference_cost: float = Field(default=0.0, ge=0.0)
    llm_calls: int = Field(default=0, ge=0)
    agents: list[TopicRelatedAgent] = Field(default_factory=_empty_related_agents)
    users: list[TopicRelatedUser] = Field(default_factory=_empty_related_users)
    teams: list[TopicRelatedTeam] = Field(default_factory=list[TopicRelatedTeam])
    documents: list[TopicRelatedDocument] = Field(
        default_factory=_empty_related_documents
    )


def _empty_topics() -> list[TopicMonthlyUsage]:
    return []


class TopicPage(BaseModel):
    items: list[TopicMonthlyUsage] = Field(default_factory=_empty_topics)
    total: int = Field(ge=0)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    available_months: list[str]


class TopicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4_000)
    keywords: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title", "description")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def normalize_topic_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip()[:80] for value in values if value.strip()))


class TopicUpdate(TopicCreate):
    revision: int = Field(ge=1)


class TopicMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_topic_id: UUID


class TopicSplitRequest(TopicCreate):
    memory_item_ids: list[UUID] = Field(min_length=1, max_length=5_000)

    @field_validator("memory_item_ids")
    @classmethod
    def unique_memory_ids(cls, values: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(values))


class TopicLinkedMemoryRead(BaseModel):
    id: UUID
    title: str
    excerpt: str
    memory_type: str
    owner_agent_id: int | None
    visibility: str


class TopicContentSummary(BaseModel):
    rooms: int = Field(default=0, ge=0)
    tasks: int = Field(default=0, ge=0)
    conversation_rounds: int = Field(default=0, ge=0)
    voice_turns: int = Field(default=0, ge=0)
    memories: int = Field(default=0, ge=0)
    documents: int = Field(default=0, ge=0)


class TopicRoomRead(BaseModel):
    id: UUID
    connection_id: int
    external_id: str
    label: str
    kind: str
    conversation_type: str


class TopicTaskRead(BaseModel):
    id: UUID
    label: str
    objective: str | None = None
    status: str
    agent_id: int | None = None
    agent_name: str | None = None
    created_at: datetime | None = None


class TopicRoundRead(BaseModel):
    id: UUID
    room_id: UUID
    room_label: str
    status: str
    preview: str
    response: str
    created_at: datetime


class TopicVoiceTurnRead(TopicRoundRead):
    session_id: UUID
    sequence: int


class TopicContentRead(BaseModel):
    topic: TopicRead
    summary: TopicContentSummary
    rooms: list[TopicRoomRead]
    tasks: list[TopicTaskRead]
    conversation_rounds: list[TopicRoundRead]
    voice_turns: list[TopicVoiceTurnRead]
    memories: list[TopicLinkedMemoryRead]
    documents: list[TopicRelatedDocument]


class TopicMutationResult(BaseModel):
    topic: TopicRead
    moved_memory_links: int = Field(default=0, ge=0)
    reassigned_tasks: int = Field(default=0, ge=0)
    reassigned_voice_sessions: int = Field(default=0, ge=0)
    reassigned_voice_turns: int = Field(default=0, ge=0)
    reassigned_messages: int = Field(default=0, ge=0)
    reassigned_conversation_rounds: int = Field(default=0, ge=0)


TopicItemKind = Literal[
    "task",
    "message",
    "conversation_round",
    "voice_turn",
    "memory",
    "document",
]


class TopicItemSelector(BaseModel):
    """Stable identity of one object whose Topic can be reassigned."""

    model_config = ConfigDict(extra="forbid")

    item_type: TopicItemKind
    item_id: UUID


class TopicItemRead(TopicItemSelector):
    topic_id: UUID
    title: str
    preview: str = ""
    created_at: datetime | None = None
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


def _empty_topic_items() -> list[TopicItemRead]:
    return []


class TopicItemPage(BaseModel):
    items: list[TopicItemRead] = Field(default_factory=_empty_topic_items)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)


class TopicItemMutationResult(BaseModel):
    item: TopicItemRead
    source_topic_id: UUID
    target_topic_id: UUID


class TopicSelectionSplitRequest(TopicCreate):
    items: list[TopicItemSelector] = Field(min_length=1, max_length=500)

    @field_validator("items")
    @classmethod
    def unique_items(cls, values: list[TopicItemSelector]) -> list[TopicItemSelector]:
        unique: list[TopicItemSelector] = []
        seen: set[tuple[TopicItemKind, UUID]] = set()
        for value in values:
            key = (value.item_type, value.item_id)
            if key not in seen:
                unique.append(value)
                seen.add(key)
        return unique


class TopicCandidate(BaseModel):
    """Compact server-owned candidate supplied to the classifier."""

    id: UUID
    title: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    activity_count: int = Field(default=0, ge=0)


class TopicClassification(BaseModel):
    """Bounded structured decision produced before any memory graph projection."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["reuse", "create"]
    topic_id: UUID | None = None
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=4_000)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)

    @field_validator("title", "description", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip()[:80] for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_action(self) -> "TopicClassification":
        if self.action == "reuse" and self.topic_id is None:
            raise ValueError("A reused Topic requires topic_id.")
        if self.action == "create" and not self.title:
            raise ValueError("A new Topic requires a title.")
        return self


__all__ = [
    "TopicClassification",
    "TopicCandidate",
    "TopicCreate",
    "TopicContentRead",
    "TopicContentSummary",
    "TopicLinkedMemoryRead",
    "TopicItemKind",
    "TopicItemMutationResult",
    "TopicItemPage",
    "TopicItemRead",
    "TopicItemSelector",
    "TopicMergeRequest",
    "TopicMutationResult",
    "TopicMonthlyUsage",
    "TopicPage",
    "TopicRead",
    "TopicRef",
    "TopicRelatedAgent",
    "TopicRelatedDocument",
    "TopicRelatedTeam",
    "TopicRelatedUser",
    "TopicRoomRead",
    "TopicRoundRead",
    "TopicSplitRequest",
    "TopicSelectionSplitRequest",
    "TopicUpdate",
    "TopicTaskRead",
    "TopicVoiceTurnRead",
]
