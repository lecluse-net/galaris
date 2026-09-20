"""Validated HTTP and MCP-facing schemas for governed memory."""

from __future__ import annotations

from .contracts import MemoryAccess
from .document_types import DocumentType

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .tag_icons import MAX_ICON_URI_LENGTH, SVG_PREFIX, validate_icon


MemoryType = Literal[
    "core", "working", "episodic", "semantic", "procedural", "social"
]
MemoryNodeKind = Literal["memory", "document", "attachment", "folder"]


class DocumentPdfExport(BaseModel):
    """Self-contained print snapshot, including the current unsaved edits."""

    html: str = Field(min_length=1, max_length=12_000_000)


class DocumentThumbnailRender(DocumentPdfExport):
    """Print snapshot of a specific saved document version."""

    revision: int = Field(ge=1)
    lock_version: int = Field(ge=1)


MemoryVisibility = Literal["private", "shared", "public"]
DocumentGlobalAccess = Literal[0, 1, 2]
MemorySortField = Literal[
    "title",
    "memory_type",
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


def _empty_memory_types() -> list[MemoryType]:
    return []


def _empty_node_kinds() -> list[MemoryNodeKind]:
    return []


def _empty_retrieval_sources() -> list[MemoryRetrievalSource]:
    return []


def _empty_memory_type_counts() -> dict[MemoryType, int]:
    return {}


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
    title: str = Field(min_length=1, max_length=500)
    payload: MemoryPayload
    memory_type: MemoryType = "semantic"
    node_kind: Literal["memory", "document"] = "memory"
    document_type: DocumentType = "html"
    content_type: str = Field(default="text", max_length=50)
    media_type: str = Field(default="text/markdown", max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    visibility: MemoryVisibility = "private"
    read_only: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    provider_code: str = Field(default="native", min_length=1, max_length=80)
    source: MemorySourceCreate | None = None

    @model_validator(mode="after")
    def validate_document(self) -> "MemoryItemCreate":
        if self.node_kind != "document":
            if self.document_type != "html":
                raise ValueError("Only a document can have a Dataset type.")
            return self
        if self.memory_type != "working":
            raise ValueError("A document must use memory_type='working'.")
        if self.document_type == "dataset" and self.media_type != "application/json":
            raise ValueError("A Dataset document must use application/json.")
        if self.content_type != "text" or (self.document_type == "html" and not self.media_type.startswith("text/")):
            raise ValueError("A document must contain text.")
        if self.visibility != "private":
            raise ValueError("A document must be private when created.")
        if self.read_only:
            raise ValueError("A working document must remain editable.")
        return self


class MemoryItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    payload: MemoryPayload | None = None
    memory_type: MemoryType | None = None
    content_type: str | None = Field(default=None, max_length=50)
    media_type: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    visibility: MemoryVisibility | None = None
    read_only: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class MemoryAccessPublic(BaseModel):
    can_read: bool
    can_write: bool


class MemoryGrantPublic(BaseModel):
    agent_id: int
    can_write: bool


class DocumentAttachmentPublic(BaseModel):
    id: UUID
    memory_item_id: UUID | None = None
    name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    created_at: datetime


class DocumentLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def public_https(cls, value: str) -> str:
        from urllib.parse import urlsplit
        uri = urlsplit(value)
        if uri.scheme != "https" or not uri.hostname or uri.username or uri.password:
            raise ValueError("Link cards require a public HTTPS URL")
        return value


class DocumentLinkCard(BaseModel):
    html: str
    attachment: DocumentAttachmentPublic | None = None


def _empty_grants() -> list[MemoryGrantPublic]:
    return []


class MemoryItemPublic(BaseModel):
    document_type: DocumentType = "html"
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
    memory_type: MemoryType
    node_kind: MemoryNodeKind
    content_type: str
    media_type: str
    filename: str | None
    keywords: list[str]
    metadata: dict[str, Any]
    visibility: MemoryVisibility
    global_access: DocumentGlobalAccess
    read_only: bool
    deletion_protected: bool
    source_managed: bool
    managed_source_kind: str | None
    managed_source_ref: str | None
    content_hash: str
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
    grants: list[MemoryGrantPublic] = Field(default_factory=_empty_grants)


class MemoryItemDetail(MemoryItemPublic):
    payload: MemoryPayload
    source_refs: list[str] = Field(default_factory=list)


class RecentMemoryItem(BaseModel):
    """Small activity projection that never exposes memory content."""

    id: UUID
    title: str
    memory_type: MemoryType
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


class DocumentContentRevisionPublic(BaseModel):
    media_type: str = "text/markdown"
    content_profile_version: int | None = None
    revision: int
    task_id: UUID | None
    content_hash: str
    author_agent_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentContentRevisionDetail(DocumentContentRevisionPublic):
    content: str


class DocumentContentRevisionPage(BaseModel):
    items: list[DocumentContentRevisionPublic]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    has_more: bool


DocumentDiffLineKind = Literal["context", "added", "removed"]


class DocumentContentDiffLine(BaseModel):
    kind: DocumentDiffLineKind
    text: str
    old_line: int | None = None
    new_line: int | None = None


class DocumentContentDiffHunk(BaseModel):
    old_start: int = Field(ge=1)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=1)
    new_count: int = Field(ge=0)
    lines: list[DocumentContentDiffLine]


class DocumentContentDiff(BaseModel):
    structure_changed: bool = False
    previous_html: str | None = None
    current_html: str | None = None
    revision: int
    current_revision: int
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    hunks: list[DocumentContentDiffHunk]


class DocumentContentRestore(BaseModel):
    expected_revision: int = Field(ge=1)


class MemorySearchRequest(BaseModel):
    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=4_000)
    recall_query: str | None = Field(default=None, max_length=4_000, exclude=True)
    keyword: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=8, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    memory_types: list[MemoryType] = Field(default_factory=_empty_memory_types)
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
    uri: str
    revision: int
    chunk_index: int
    excerpt: str
    block_start: int | None = None
    block_end: int | None = None
    section_path: list[str] = Field(default_factory=list[str])


class MemorySearchHit(BaseModel):
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
    query: str
    hits: list[MemorySearchHit]
    total: int = Field(ge=0)
    has_more: bool


class DocumentTagWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None
    icon: str | None = Field(default=None, max_length=MAX_ICON_URI_LENGTH)

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, value: str | None) -> str | None:
        return validate_icon(value) if value is not None else None


class DocumentIconWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    icon: str | None = Field(max_length=MAX_ICON_URI_LENGTH)

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, value: str | None) -> str | None:
        if value is not None and value.startswith(("folder:", "folder-open:")):
            raise ValueError("Folder icons are reserved for folders")
        return validate_icon(value) if value is not None else None


class DocumentIconRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[UUID] = Field(max_length=500)


class DocumentTagMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag_id: UUID | None


class DocumentOrderNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["tag", "document"]
    id: UUID


class DocumentOrderMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: DocumentOrderNode
    parent_id: UUID | None = None
    list_only: bool = False
    anchor: DocumentOrderNode | None = None
    after: bool = False


class DocumentOrderSort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: UUID | None = None
    descending: bool = False


class DocumentTagIconWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    data: str = Field(max_length=MAX_ICON_URI_LENGTH)

    @field_validator("data")
    @classmethod
    def valid_data(cls, value: str) -> str:
        if not value.startswith(SVG_PREFIX):
            raise ValueError("Expected an uploaded SVG")
        return validate_icon(value)


class DocumentTagIconPublic(DocumentTagIconWrite):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class DocumentTagPublic(DocumentTagWrite):
    memory_item_id: UUID | None = None
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int = 0


class DocumentTagCatalog(BaseModel):
    user_id: int
    tags: list[DocumentTagPublic]


class DocumentTagDeletionResult(BaseModel):
    deleted: bool
    tag_count: int
    document_count: int


class DocumentLibraryRequest(BaseModel):
    """Human document browse filters, scoped by the authorization layer."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=4_000)
    keyword: str | None = Field(default=None, max_length=100)
    document_type: DocumentType | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    tag_id: UUID | None = None
    include_descendants: bool = True
    include_owners: bool = False
    classification: Literal["all", "classified", "unclassified"] = "all"
    owner_kind: Literal["agent", "user"] | None = None
    owner: int | None = Field(default=None, gt=0)
    created_from: datetime | None = None
    created_until: datetime | None = None
    updated_from: datetime | None = None
    updated_until: datetime | None = None
    sort_by: Literal["position", "title", "created_at", "updated_at", "document_type"] = "title"
    sort_desc: bool = False

    @model_validator(mode="after")
    def validate_filters(self) -> DocumentLibraryRequest:
        if self.owner is not None and self.owner_kind is None:
            raise ValueError("An owner requires its kind")
        for start, end in ((self.created_from, self.created_until), (self.updated_from, self.updated_until)):
            for value in (start, end):
                if value is not None and value.tzinfo is None:
                    raise ValueError("Date filters require a timezone")
            if start is not None and end is not None and start >= end:
                raise ValueError("The end must follow the start")
        return self


class DocumentLibraryEntry(BaseModel):
    position: int = 0
    tags: list[DocumentTagPublic] = Field(default_factory=list[DocumentTagPublic])
    owner_label: str = ""
    item: MemoryItemPublic
    user_access: MemoryAccess = Field(default_factory=lambda: MemoryAccess(can_read=False, can_write=False))
    agent_ids: list[int]
    writable_agent_ids: list[int]


class DocumentFolderOption(BaseModel):
    path: str
    kind: Literal["custom", "goal"]
    shared: bool


class DocumentLibraryPage(BaseModel):
    owners: list[DocumentOwnerOption] = Field(default_factory=lambda: list[DocumentOwnerOption]())
    query: str
    entries: list[DocumentLibraryEntry]
    keywords: list[str]
    total: int = Field(ge=0)
    has_more: bool


class ManagedDocumentDetail(BaseModel):
    item: MemoryItemDetail
    agent_id: int | None = Field(default=None, gt=0)


class DocumentCollaborator(BaseModel):
    kind: Literal["agent", "user", "team"]
    id: int = Field(gt=0)
    label: str
    can_write: bool = False
    group_ids: list[int] = Field(default_factory=list[int])
    avatar_url: str | None = None
    has_avatar: bool = False


class DocumentSharing(BaseModel):
    lock_version: int
    can_manage: bool
    grants: list[DocumentCollaborator]
    options: list[DocumentCollaborator]
    level: Literal["private", "groups", "public"]
    can_write: bool
    owner: DocumentCollaborator | None
    owner_groups: list[DocumentCollaborator]


class DocumentSharingGrantUpdate(BaseModel):
    kind: Literal["agent", "user", "team"]
    id: int = Field(gt=0)
    can_write: bool = False


class DocumentSharingLevelUpdate(BaseModel):
    level: Literal["private", "groups", "public"]
    can_write: bool = False
    grants: list[DocumentSharingGrantUpdate]
    expected_lock_version: int = Field(ge=1)


class DocumentSharingUpdate(BaseModel):
    kind: Literal["agent", "user", "team"]
    id: int = Field(gt=0)
    can_write: bool | None
    expected_lock_version: int = Field(ge=1)


DocumentOwnerKind = Literal["agent", "user"]


class DocumentOwnerOption(BaseModel):
    kind: DocumentOwnerKind
    id: int = Field(gt=0)
    label: str
    subtitle: str
    avatar_url: str | None = None
    is_current_user: bool = False


class DocumentOwnerOptions(BaseModel):
    agents: list[DocumentOwnerOption]
    users: list[DocumentOwnerOption]


class DocumentCreate(BaseModel):
    """Create one human-managed document with an explicit owner and editor."""

    model_config = ConfigDict(extra="forbid")

    owner_kind: DocumentOwnerKind
    owner_id: int = Field(gt=0)
    actor_agent_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    document_type: DocumentType = "html"
    folder: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_owner_and_editor(self) -> "DocumentCreate":
        if self.owner_kind == "agent" and self.owner_id != self.actor_agent_id:
            raise ValueError("The owner Agent must also be the initial editor.")
        return self


class DocumentOwnerUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    kind: DocumentOwnerKind
    id: int = Field(gt=0)


class DocumentFolderUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    folder: str = Field(default="", max_length=500)

    @field_validator("folder")
    @classmethod
    def normalize_folder(cls, value: str) -> str:
        parts: list[str] = []
        for raw_part in value.strip().replace("\\", "/").split("/"):
            part = raw_part.strip()
            if not part:
                continue
            if part in {".", ".."}:
                raise ValueError("A document folder cannot contain '.' or '..'.")
            parts.append(part)
        normalized = "/".join(parts)
        if len(normalized) > 500:
            raise ValueError("A document folder cannot exceed 500 characters.")
        return normalized


class MemoryRecallRequest(BaseModel):
    """Bounded agent recall through the single canonical hybrid strategy."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=4_000)
    semantic_query: str | None = Field(default=None, max_length=4_000)
    limit: int | None = Field(default=None, ge=1, le=500)
    memory_types: list[MemoryType] = Field(default_factory=_empty_memory_types)
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
    memory_type: MemoryType
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
    by_memory_type: dict[MemoryType, int] = Field(
        default_factory=_empty_memory_type_counts
    )


class MemoryGraphCursor(BaseModel):
    """Stable keyset cursor whose identifier is contextual to the graph endpoint."""

    activity_at: datetime
    id: UUID


def _empty_memory_ids() -> list[UUID]:
    return []


class MemoryGraphRootsRequest(BaseModel):
    """Bounded recent roots for progressive graph exploration."""

    agent_id: int = Field(gt=0)
    query: str = Field(default="", max_length=4_000)
    memory_types: list[MemoryType] = Field(default_factory=_empty_memory_types)
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    limit: int = Field(default=60, ge=1, le=100)
    edge_limit: int = Field(default=300, ge=1, le=500)
    cursor: MemoryGraphCursor | None = None
    known_item_ids: list[UUID] = Field(
        default_factory=_empty_memory_ids,
        max_length=500,
    )


class MemoryGraphExpandRequest(BaseModel):
    """One keyset page of relations adjacent to a visible memory item."""

    agent_id: int = Field(gt=0)
    item_id: UUID
    query: str = Field(default="", max_length=4_000)
    memory_types: list[MemoryType] = Field(default_factory=_empty_memory_types)
    topic_item_id: UUID | None = None
    contact_item_id: UUID | None = None
    limit: int = Field(default=40, ge=1, le=100)
    cursor: MemoryGraphCursor | None = None
    known_item_ids: list[UUID] = Field(
        default_factory=_empty_memory_ids,
        max_length=3_000,
    )


class MemoryGraphNode(BaseModel):
    """Lightweight graph projection; memory payloads never travel in graph pages."""

    id: UUID
    resource_media_type: str | None = None
    node_kind: Literal["memory", "document", "attachment", "folder", "conversation"] = "memory"
    entity_kind: Literal["memory", "document", "attachment", "folder", "topic", "contact", "conversation"]
    owner_agent_id: int | None
    title: str
    memory_type: MemoryType
    visibility: MemoryVisibility
    source_managed: bool
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    activity_at: datetime
    has_relations: bool
    relation_count: int = Field(ge=0)


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


class MemoryGrantUpdate(BaseModel):
    can_write: bool = False
    expected_lock_version: int | None = Field(default=None, ge=1)


class DocumentGlobalAccessUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    global_access: DocumentGlobalAccess


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
    agent_id: int = Field(gt=0)
    action: AcquisitionAction = "create"
    target_item_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
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


class GoalFolderReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = Field(default=None, gt=0)
    goal_id: UUID | None = None


class GoalFolderReconciliationResult(BaseModel):
    job_id: UUID
