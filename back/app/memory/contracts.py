"""Public contracts for durable Memory and interchangeable resource storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID


class ResourceStorageError(RuntimeError):
    """Base error raised by a resource-storage provider."""


class ResourceNotFoundError(ResourceStorageError):
    """The opaque resource identifier does not exist in its provider."""


class ResourceTooLargeError(ResourceStorageError):
    """The resource exceeds the configured provider limit."""


@runtime_checkable
class ResourceStorage(Protocol):
    """Small provider-neutral CRUD contract for opaque binary resources."""

    @property
    def code(self) -> str: ...

    async def create(self, content: bytes) -> str: ...

    async def read(self, resource_id: str) -> bytes: ...

    async def update(self, resource_id: str, content: bytes) -> None: ...

    async def delete(self, resource_id: str) -> bool: ...


@dataclass(frozen=True)
class MemoryAccess:
    """Effective item permissions for one agent."""

    can_read: bool
    can_write: bool


@dataclass(frozen=True)
class MemoryContextItem:
    """One bounded, sourced memory excerpt prepared for an agent run."""

    memory_id: str
    title: str
    excerpt: str
    score: float
    memory_type: str
    node_kind: str = "memory"
    source_refs: tuple[str, ...] = ()
    revision: int | None = None


@dataclass(frozen=True)
class MemoryBrief:
    """Deterministic long-term context shared by every concrete driver."""

    query: str
    items: tuple[MemoryContextItem, ...]
    rendered: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class MemorySearchItem:
    """One plain ranked result returned by the public search facade."""

    id: UUID
    title: str
    excerpt: str
    memory_type: str
    node_kind: str
    source_refs: tuple[str, ...] = ()
    uri: str = ""
    revision: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryUsageObservation:
    """One memory that was actually exposed to a Task run or planning decision."""

    memory_id: UUID
    access_kind: str
    memory_role: str
    created_at: datetime


@dataclass(frozen=True)
class MessengerContactObservation:
    """One human Messenger identity observed for an agent-owned private memory."""

    owner_agent_id: int
    messaging_id: str
    user_id: str
    display_name: str = ""
    galaris_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class MessengerContactIdentity:
    """One strong address attached to a canonical contact."""

    id: UUID
    kind: Literal["messenger", "galaris_user"]
    namespace: str
    external_id: str
    display_name: str
    galaris_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class MessengerContactRecord:
    """Administrative projection of one canonical contact Memory item."""

    memory_item_id: UUID
    owner_agent_id: int
    title: str
    display_name: str
    identities: tuple[MessengerContactIdentity, ...]
    linked_memory_count: int
    created_at: datetime
    updated_at: datetime | None


@runtime_checkable
class ContactReferenceRewriter(Protocol):
    """Port used while merging contact references owned by other domains."""

    async def __call__(
        self, source_contact_item_id: UUID, target_contact_item_id: UUID
    ) -> dict[str, int]: ...


@runtime_checkable
class ContactReferenceCleaner(Protocol):
    """Port used while clearing references to a forgotten contact."""

    async def __call__(self, contact_item_id: UUID) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class TaskMemoryStructureProjection:
    """Stable Task relations to project between already acquired memories."""

    owner_agent_id: int
    task_id: UUID
    parent_task_id: UUID | None = None
    source_task_id: UUID | None = None
    previous_conversation_task_id: UUID | None = None
    conversation_scope_hash: str | None = None
    conversation_kind: str | None = None
    conversation_channel: str | None = None
    conversation_title: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationMemoryStructureProjection:
    """One non-recallable conversation node and its safe display metadata."""

    owner_agent_id: int
    conversation_scope_hash: str
    conversation_kind: str
    conversation_channel: str = ""
    conversation_title: str = "Conversation"


@dataclass(frozen=True, slots=True)
class TaskMemoryAssociationResult:
    """Outcome of attaching one ordinary memory to its current Task subject."""

    associated: bool
    links_created: int = 0
    context_node_id: UUID | None = None


@dataclass(frozen=True)
class SourceMemoryDocument:
    """Provider-neutral Markdown projection derived from one canonical source row."""

    source_kind: str
    source_ref: str
    owner_agent_id: int | None
    memory_item_id: UUID | None
    title: str
    memory_type: str
    content: str
    filename: str
    keywords: tuple[str, ...]
    metadata: dict[str, object]
    visibility: Literal["private", "public"] = "private"
    topic_id: UUID | None = None
    media_type: str = "text/markdown"


@dataclass(frozen=True, slots=True)
class TopicLinkedMemory:
    """Administrative metadata for one memory attached to a Topic projection."""

    id: UUID
    title: str
    excerpt: str
    memory_type: str
    owner_agent_id: int | None
    visibility: str
    node_kind: str
    filename: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TopicLinkedDocument:
    """Compact working document attached to one public Topic projection."""

    topic_item_id: UUID
    id: UUID
    title: str
    filename: str | None


@dataclass(frozen=True, slots=True)
class TopicProjectionMatch:
    """One public Topic projection ranked by the current vector index."""

    memory_item_id: UUID
    similarity: float


@dataclass(frozen=True, slots=True)
class TopicProjectionRanking:
    """Fail-open vector shortlist used by the Topic domain."""

    matches: tuple[TopicProjectionMatch, ...]
    model_key: str | None = None
    degraded: bool = False
    degradation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TopicMaintenanceSuggestion:
    """One rebuildable, non-authoritative Topic graph suggestion."""

    source_item_id: UUID
    target_item_id: UUID
    relation_type: str
    confidence: float
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class TopicMaintenancePlan:
    """Bounded vector evidence checkpoint prepared before graph writes."""

    snapshot_id: str
    model_key: str
    suggestions: tuple[TopicMaintenanceSuggestion, ...]
    topic_count: int
    memory_count: int
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class TopicMaintenanceResult:
    """Idempotent refresh outcome for generated suggested links."""

    active: int
    created: int
    updated: int
    removed: int


__all__ = [
    "MemoryAccess",
    "MemoryBrief",
    "MemoryContextItem",
    "MemorySearchItem",
    "MemoryUsageObservation",
    "ContactReferenceRewriter",
    "ConversationMemoryStructureProjection",
    "MessengerContactIdentity",
    "MessengerContactObservation",
    "MessengerContactRecord",
    "ResourceNotFoundError",
    "ResourceStorage",
    "ResourceStorageError",
    "ResourceTooLargeError",
    "SourceMemoryDocument",
    "TaskMemoryAssociationResult",
    "TaskMemoryStructureProjection",
    "TopicLinkedMemory",
    "TopicProjectionMatch",
    "TopicProjectionRanking",
    "TopicMaintenancePlan",
    "TopicMaintenanceResult",
    "TopicMaintenanceSuggestion",
]
