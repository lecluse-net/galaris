"""Validated HTTP and MCP-facing schemas for governed memory."""

from __future__ import annotations

from .temporal import MemoryTemporalAnchor, MemoryTemporalFilter, MemoryTemporalWindow

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


MemoryNodeKind = Literal["memory", "document", "attachment", "folder", "file", "directory"]


MemoryVisibility = Literal["private", "shared", "public"]
MemorySortField = Literal[
    "title",
    "visibility",
    "owner",
    "access_count",
    "last_accessed_at",
    "updated_at",
]
MemoryRetrievalMode = Literal["lexical", "hybrid"]
MemoryRetrievalSource = Literal[
    "thematic_lexical",
    "thematic_vector",
    "global_lexical",
    "global_vector",
    "graph_link",
    "structural_link",
    "suggested_topic_link",
]
MemoryRoleFilter = Literal["experience", "ordinary"]
MemoryMaintenanceMode = Literal["off", "manual", "automatic"]
MemoryFindingKind = Literal["duplicate", "contradiction", "aging"]
MemoryFindingStatus = Literal[
    "pending", "applied", "dismissed", "obsolete", "error"
]
ManualMemoryRelationType = Literal[
    "related_to",
    "supports",
    "contradicts",
    "depends_on",
    "precedes",
    "supersedes",
]
AcquisitionAction = Literal["create", "update", "link", "contradict", "skip"]
AcquisitionStatus = Literal["stored", "merged", "rejected"]
MemoryLinkReconciliationTriggerMode = Literal[
    "manual_only",
    "after_dream",
    "scheduled",
    "after_dream_and_scheduled",
]
MemoryLinkReconciliationJobStatus = Literal[
    "pending",
    "running",
    "success",
    "error",
]


def _empty_node_kinds() -> list[MemoryNodeKind]:
    return []


def _empty_retrieval_sources() -> list[MemoryRetrievalSource]:
    return []


class MemoryPayload(BaseModel):
    """Exactly one textual or base64-encoded payload."""

    text: str | None = Field(default=None, max_length=2_000_000)
    base64: str | None = None

    @model_validator(mode="after")
    def one_payload(self) -> "MemoryPayload":
        if (self.text is None) == (self.base64 is None):
            raise ValueError("Provide exactly one of text or base64.")
        return self


class MemorySourceCreate(BaseModel):
    source_kind: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=1_024)
    excerpt: str = Field(default="", max_length=8_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_agent_id: int = Field(gt=0)
    title: str = Field(default="", max_length=500)
    payload: MemoryPayload
    node_kind: Literal["memory"] = "memory"
    document_type: Literal["html"] = "html"
    content_type: str = Field(default="text", max_length=50)
    media_type: str = Field(default="text/markdown", max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["private"] = "private"
    read_only: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    temporal: MemoryTemporalAnchor | None = None
    provider_code: str = Field(default="native", min_length=1, max_length=80)
    source: MemorySourceCreate | None = None


class MemoryItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    payload: MemoryPayload | None = None
    content_type: str | None = Field(default=None, max_length=50)
    media_type: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    visibility: Literal["private"] | None = None
    read_only: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    temporal: MemoryTemporalAnchor | None = None


class MemoryAccessPublic(BaseModel):
    can_read: bool
    can_write: bool


class MemoryItemPublic(BaseModel):
    topic_id: UUID | None = None
    document_id: UUID | None = None
    thumbnail_id: UUID | None = None
    document_revision: int | None = None
    summary_document_revision: int | None = None
    summary_outdated: bool = False
    temporal: MemoryTemporalAnchor | None = None
    document_type: Literal["html", "dataset", "process"] = "html"
    semantic_fingerprint: str | None = Field(default=None, exclude=True)
    content_profile: Literal["rich-text", "document"] = "rich-text"
    content_profile_version: int | None = None
    id: UUID
    revision: int
    lock_version: int
    owner_agent_id: int | None
    owner_user_id: int | None
    provider_code: str
    title: str
    node_kind: MemoryNodeKind
    content_type: str
    media_type: str
    filename: str | None
    keywords: list[str]
    metadata: dict[str, Any]
    visibility: MemoryVisibility
    read_only: bool
    deletion_protected: bool
    source_managed: bool
    managed_source_kind: str | None
    managed_source_ref: str | None
    content_hash: str
    file_sha256: str | None = None
    file_media_type: str | None = None
    file_size_bytes: int | None = None
    primary_url: str | None = None
    urls: list[str] = Field(default_factory=list)
    size_bytes: int
    last_accessed_at: datetime | None
    access_count: int
    valid_from: datetime | None
    valid_until: datetime | None
    old_at: datetime | None
    old_reason: str | None
    created_at: datetime
    updated_at: datetime | None
    access: MemoryAccessPublic


class MemoryItemDetail(MemoryItemPublic):
    payload: MemoryPayload
    source_refs: list[str] = Field(default_factory=list)


class RecentMemoryItem(BaseModel):
    """Small activity projection that never exposes memory content."""

    id: UUID
    title: str
    created_at: datetime


class MemoryFindingPublic(BaseModel):
    id: UUID
    kind: MemoryFindingKind
    primary_item_id: UUID
    related_item_id: UUID | None
    primary_revision: int
    related_revision: int | None
    score: float | None
    threshold: float
    proposed_action: str
    status: MemoryFindingStatus
    details: dict[str, Any]
    detected_at: datetime
    resolved_at: datetime | None


class MemoryFindingAction(BaseModel):
    canonical_item_id: UUID | None = None


class MemoryRevisionPublic(BaseModel):
    temporal: MemoryTemporalAnchor | None = None
    media_type: str = "text/markdown"
    content_profile_version: int | None = None
    revision: int
    task_id: UUID | None
    content_hash: str
    title: str
    keywords: list[str]
    author_agent_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemorySearchRequest(BaseModel):
    exclude_temporal: bool = False
    hybrid: bool = False
    temporal: MemoryTemporalFilter | None = None
    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=4_000)
    recall_query: str | None = Field(default=None, max_length=4_000, exclude=True)
    keyword: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=8, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    node_kinds: list[MemoryNodeKind] = Field(default_factory=_empty_node_kinds)
    sort_by: MemorySortField | None = None
    sort_desc: bool = True
    task_id: UUID | None = None
    memory_role: MemoryRoleFilter | None = None
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    strict_contact_scope: bool = False
    filter_topic_item_id: UUID | None = None
    filter_contact_item_id: UUID | None = None
    exclude_topic_projections: bool = False
    exclude_agent_projections: bool = False
    exclude_source_managed: bool = False

    @model_validator(mode="after")
    def complete_conversation_scope(self) -> "MemorySearchRequest":
        if self.hybrid and self.temporal is not None and self.temporal.lookahead_hours != 0:
            raise ValueError("Hybrid browsing requires zero temporal lookahead.")
        if self.contact_item_id is not None and self.topic_item_id is None:
            # A contact-only request is reserved for the internal global branch:
            # it keeps memories learned from another interlocutor out of recall.
            return self
        return self


class MemoryTraversalStep(BaseModel):
    source_item_id: UUID
    target_item_id: UUID
    relation_type: str


class MemorySearchPassage(BaseModel):
    content_source: Literal["document", "memory"] = "document"
    source_revision: int | None = None
    uri: str
    revision: int
    chunk_index: int
    excerpt: str
    block_start: int | None = None
    block_end: int | None = None
    section_path: list[str] = Field(default_factory=list[str])


class MemoryConflictReference(BaseModel):
    """An accessible conflicting claim; recency never resolves its truth."""

    uri: str
    revision: int
    recorded_at: datetime
    source_refs: list[str] = Field(default_factory=list[str], max_length=3)
    excerpt: str


class MemorySearchHit(BaseModel):
    conflicts: list[MemoryConflictReference] = Field(default_factory=list[MemoryConflictReference])
    temporal_match_at: datetime | None = None
    item: MemoryItemPublic
    excerpt: str
    score: float
    semantic_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    passages: list[MemorySearchPassage] = Field(default_factory=list[MemorySearchPassage])
    source_refs: list[str] = Field(default_factory=list)
    structural_path: list[MemoryTraversalStep] = Field(default_factory=list[MemoryTraversalStep])
    retrieval_sources: list[MemoryRetrievalSource] = Field(
        default_factory=_empty_retrieval_sources
    )


class MemorySearchPage(BaseModel):
    recall_truncated: bool = False
    degradation_reason: str | None = None
    temporal_window: MemoryTemporalWindow | None = None
    query: str
    hits: list[MemorySearchHit]
    total: int = Field(ge=0)
    has_more: bool


class MemoryRecallRequest(BaseModel):
    """Bounded agent recall through the single canonical hybrid strategy."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(gt=0)
    exclude_temporal: bool = False
    target_at: AwareDatetime | None = None
    keyword: str | None = Field(default=None, max_length=100)
    filter_topic_item_id: UUID | None = None
    filter_contact_item_id: UUID | None = None
    query: str = Field(default="", max_length=4_000)
    semantic_query: str | None = Field(default=None, max_length=4_000)
    limit: int | None = Field(default=None, ge=1, le=500)
    node_kinds: list[MemoryNodeKind] = Field(default_factory=_empty_node_kinds)
    task_id: UUID | None = None
    memory_role: MemoryRoleFilter | None = None
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    strict_contact_scope: bool = False
    exclude_agent_projections: bool = False
    exclude_source_managed: bool = False

    @model_validator(mode="after")
    def complete_conversation_scope(self) -> "MemoryRecallRequest":
        return self


class MemoryIndexCoverage(BaseModel):
    model_code: str
    eligible_items: int = Field(ge=0)
    indexed_items: int = Field(ge=0)


class MemoryRecallResult(BaseModel):
    evidence_status: Literal["unassessed", "no_evidence"] = "unassessed"
    relevance_status: Literal["matched", "no_sufficient_evidence"] = "matched"
    admission_omitted_count: int = Field(default=0, ge=0)
    index_coverage: MemoryIndexCoverage | None = None
    query: str
    hits: list[MemorySearchHit]
    mode: MemoryRetrievalMode
    degraded: bool = False
    degradation_reason: str | None = None
    has_more: bool = False
    ranking_version: str = "memory-rrf/v1"
    thematic_candidate_count: int = Field(default=0, ge=0)
    global_candidate_count: int = Field(default=0, ge=0)
    thematic_result_count: int = Field(default=0, ge=0)
    global_result_count: int = Field(default=0, ge=0)


class MemorySimilarityCandidate(BaseModel):
    """One owner-local ordinary memory close to a proposed durable fact."""

    memory_id: UUID
    revision: int = Field(ge=1)
    title: str
    excerpt: str
    similarity: float = Field(ge=-1.0, le=1.0)


class MemoryDuplicatePreviewPair(BaseModel):
    """One non-destructive semantic duplicate candidate for administration."""

    owner_agent_id: int = Field(gt=0)
    first_memory_id: UUID
    first_title: str
    second_memory_id: UUID
    second_title: str
    similarity: float = Field(ge=-1.0, le=1.0)


def _empty_duplicate_pairs() -> list[MemoryDuplicatePreviewPair]:
    return []


class MemoryDuplicatePreview(BaseModel):
    """Bounded read-only estimate of near-duplicate ordinary memories."""

    threshold: float = Field(ge=0.0, le=1.0)
    total_pairs: int = Field(ge=0)
    pairs: list[MemoryDuplicatePreviewPair] = Field(
        default_factory=_empty_duplicate_pairs
    )
    has_more: bool = False
    degraded: bool = False
    degradation_reason: str | None = None


class MemoryRetentionPreview(BaseModel):
    """Read-only impact estimate before enabling inactivity-based forgetting."""

    days: int = Field(ge=0, le=36_500)
    inactivity_enabled: bool
    inactive_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    total_candidates: int = Field(ge=0)
    oldest_activity_at: datetime | None = None


class MemoryGraphCursor(BaseModel):
    """Stable keyset cursor whose identifier is contextual to the graph endpoint."""

    activity_at: datetime
    id: UUID
    role_rank: int | None = Field(default=None, ge=0, le=3)


def _empty_memory_ids() -> list[UUID]:
    return []


class MemoryGraphRootsRequest(BaseModel):
    include_saved_positions: bool = False
    """Bounded recent roots for progressive graph exploration."""

    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=4_000)
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    limit: int = Field(default=60, ge=1, le=500)
    edge_limit: int = Field(default=300, ge=1, le=10_000)
    order_by: Literal["activity", "hierarchy"] = "activity"
    defer_resource_children: bool = False
    defer_resource_files: bool = False
    cursor: MemoryGraphCursor | None = None
    include_matching_roots: bool = False
    known_item_ids: list[UUID] = Field(
        default_factory=_empty_memory_ids,
        max_length=3_000,
    )

    @model_validator(mode="after")
    def validate_order_cursor(self) -> MemoryGraphRootsRequest:
        if self.order_by == "hierarchy" and self.cursor is not None and self.cursor.role_rank is None:
            raise ValueError("Hierarchy-ordered graph pages require a role rank in the cursor.")
        return self


class MemoryGraphExpandRequest(BaseModel):
    """One keyset page of relations adjacent to a visible memory item."""

    agent_id: int = Field(gt=0)
    item_id: UUID
    children_only: bool = False
    include_saved_positions: bool = False
    query: str = Field(default="", max_length=4_000)
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    limit: int = Field(default=40, ge=1, le=500)
    cursor: MemoryGraphCursor | None = None
    known_item_ids: list[UUID] = Field(
        default_factory=_empty_memory_ids,
        max_length=3_000,
    )

    @model_validator(mode="after")
    def validate_child_cursor(self) -> MemoryGraphExpandRequest:
        if self.children_only and self.cursor is not None and self.cursor.role_rank is None:
            raise ValueError("Child pages require a role rank in the cursor.")
        return self


class MemoryGraphNode(BaseModel):
    """Lightweight graph projection; memory payloads never travel in graph pages."""

    id: UUID
    resource_media_type: str | None = None
    resource_uri: str | None = None
    node_kind: Literal["memory", "document", "attachment", "folder", "file", "directory", "conversation"] = "memory"
    entity_kind: Literal["memory", "document", "attachment", "folder", "file", "directory", "topic", "contact", "conversation"]
    owner_agent_id: int | None
    title: str
    visibility: MemoryVisibility
    source_managed: bool
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    activity_at: datetime
    has_relations: bool
    relation_count: int = Field(ge=0)
    children_count: int = Field(default=0, ge=0)


class MemoryGraphEdge(BaseModel):
    id: UUID
    source_item_id: UUID
    target_item_id: UUID
    relation_type: str
    confidence: float
    suggested: bool


def _empty_graph_nodes() -> list[MemoryGraphNode]:
    return []


def _empty_graph_edges() -> list[MemoryGraphEdge]:
    return []


class MemoryGraphPage(BaseModel):
    positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    nodes: list[MemoryGraphNode] = Field(default_factory=_empty_graph_nodes)
    edges: list[MemoryGraphEdge] = Field(default_factory=_empty_graph_edges)
    next_cursor: MemoryGraphCursor | None = None
    has_more: bool = False
    edges_truncated: bool = False


class MemoryFilterOption(BaseModel):
    id: UUID
    label: str


def _empty_filter_options() -> list[MemoryFilterOption]:
    return []


class MemoryFilterOptions(BaseModel):
    topics: list[MemoryFilterOption] = Field(default_factory=_empty_filter_options)
    contacts: list[MemoryFilterOption] = Field(default_factory=_empty_filter_options)


class MemoryLinkCreate(BaseModel):
    source_item_id: UUID
    target_item_id: UUID
    relation_type: str = Field(min_length=1, max_length=80)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    suggested: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManualMemoryLinkCreate(BaseModel):
    """User-authored link restricted to the canonical relation vocabulary."""

    source_item_id: UUID
    target_item_id: UUID
    relation_type: ManualMemoryRelationType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    suggested: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryLinkPublic(BaseModel):
    id: UUID
    source_item_id: UUID
    target_item_id: UUID
    relation_type: str
    confidence: float
    suggested: bool
    created_by_agent_id: int | None
    metadata: dict[str, Any]
    created_at: datetime


class MemoryLinkReconciliationStatus(BaseModel):
    """Operator-facing schedule and durable execution state."""

    trigger_mode: MemoryLinkReconciliationTriggerMode
    after_dream_enabled: bool
    scheduled_enabled: bool
    interval_hours: int = Field(ge=1, le=720)
    idle_only: bool = True
    latest_job_status: MemoryLinkReconciliationJobStatus | None = None
    latest_job_trigger: str | None = None
    latest_job_created_at: datetime | None = None
    last_completed_at: datetime | None = None
    next_scheduled_at: datetime | None = None
    job_pending: bool = False


class MemoryLinkReconciliationRunResult(BaseModel):
    """Counters returned by one synchronous manual reconciliation."""

    scope_item_id: UUID | None = None
    sources_scanned: int = Field(default=0, ge=0)
    desired: int = Field(default=0, ge=0)
    created: int = Field(default=0, ge=0)
    updated: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    unchanged: int = Field(default=0, ge=0)
    manual_conflicts: int = Field(default=0, ge=0)
    incomplete_sources: int = Field(default=0, ge=0)
    contact_memberships_created: int = Field(default=0, ge=0)
    contact_memberships_updated: int = Field(default=0, ge=0)
    contact_memberships_removed: int = Field(default=0, ge=0)
    topic_contact_memberships_created: int = Field(default=0, ge=0)
    topic_contact_memberships_updated: int = Field(default=0, ge=0)
    topic_contact_memberships_removed: int = Field(default=0, ge=0)
    suggestions_available: bool = True


class MemoryAcquisitionCreate(BaseModel):
    temporal: MemoryTemporalAnchor | None = None
    agent_id: int = Field(gt=0)
    action: AcquisitionAction = "create"
    target_item_id: UUID | None = None
    title: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    source_kind: str = Field(default="manual", min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=1_024)
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=128)


class MemoryAcquisitionResult(BaseModel):
    acquisition_id: UUID
    memory_id: UUID | None = None
    created: bool
    applied: bool
    status: AcquisitionStatus


class MemoryForgetResult(BaseModel):
    memory_id: UUID
    resources_deleted: int
