"""Document API contracts, independent of personal memory storage."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from core.util import TemporalAnchor as DocumentTemporalAnchor
from .contracts import DocumentAccess
from .document_types import DocumentType
from .tag_icons import validate_icon
from app.share import Collaborator, SharingState, GrantUpdate, SharingUpdate, SingleGrantUpdate

DocumentNodeKind = Literal["document"]

class DocumentPdfExport(BaseModel):
    """Self-contained print snapshot, including the current unsaved edits."""

    html: str = Field(min_length=1, max_length=12_000_000)

class DocumentThumbnailRender(DocumentPdfExport):
    """Print snapshot of a specific saved document version."""

    revision: int = Field(ge=1)
    lock_version: int = Field(ge=1)

DocumentVisibility = Literal["private", "shared", "public"]

DocumentGlobalAccess = Literal[0, 1, 2]

class DocumentPayload(BaseModel):
    """Exactly one textual or base64-encoded payload."""

    text: str | None = Field(default=None, max_length=2_000_000)
    base64: str | None = None

    @model_validator(mode="after")
    def one_payload(self) -> "DocumentPayload":
        if (self.text is None) == (self.base64 is None):
            raise ValueError("Provide exactly one of text or base64.")
        return self

class DocumentSourceCreate(BaseModel):
    source_kind: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=1_024)
    excerpt: str = Field(default="", max_length=8_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

class DocumentItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_agent_id: int = Field(gt=0)
    title: str = Field(default="", max_length=500)
    payload: DocumentPayload
    node_kind: Literal["document"] = "document"
    document_type: DocumentType = "html"
    content_type: str = Field(default="text", max_length=50)
    media_type: str = Field(default="text/html", max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    visibility: DocumentVisibility = "private"
    read_only: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    temporal: DocumentTemporalAnchor | None = None
    provider_code: str = Field(default="native", min_length=1, max_length=80)
    source: DocumentSourceCreate | None = None

    @model_validator(mode="after")
    def validate_document(self) -> "DocumentItemCreate":
        if self.document_type != "html":
            raise ValueError("Documents contain editorial HTML; use Dataset or Process for their native resources")
        if self.node_kind != "document":
            if self.document_type != "html":
                raise ValueError("Only a document can have a Dataset type.")
            return self
        if not self.title.strip():
            raise ValueError("A document title is required.")
        if self.content_type != "text" or (self.document_type == "html" and not self.media_type.startswith("text/")):
            raise ValueError("A document must contain text.")
        if self.visibility != "private":
            raise ValueError("A document must be private when created.")
        if self.read_only:
            raise ValueError("A working document must remain editable.")
        return self

class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    payload: DocumentPayload | None = None
    content_type: str | None = Field(default=None, max_length=50)
    media_type: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=500)
    keywords: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    visibility: DocumentVisibility | None = None
    read_only: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    temporal: DocumentTemporalAnchor | None = None

class DocumentAccessPublic(BaseModel):
    can_read: bool
    can_write: bool

class DocumentGrantPublic(BaseModel):
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
            raise ValueError("Document resources require a public HTTPS URL")
        return value

class DocumentLinkCard(BaseModel):
    html: str
    attachment: DocumentAttachmentPublic | None = None

def _empty_grants() -> list[DocumentGrantPublic]:
    return []

class DocumentPublic(BaseModel):
    topic_id: UUID | None = None
    document_id: UUID | None = None
    thumbnail_id: UUID | None = None
    document_revision: int | None = None
    summary_document_revision: int | None = None
    summary_outdated: bool = False
    temporal: DocumentTemporalAnchor | None = None
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
    node_kind: DocumentNodeKind
    content_type: str
    media_type: str
    filename: str | None
    keywords: list[str]
    metadata: dict[str, Any]
    visibility: DocumentVisibility
    global_access: DocumentGlobalAccess
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
    access: DocumentAccessPublic
    grants: list[DocumentGrantPublic] = Field(default_factory=_empty_grants)

class DocumentDetail(DocumentPublic):
    payload: DocumentPayload
    source_refs: list[str] = Field(default_factory=list)

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

class DocumentTagWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None
    icon: str | None = None

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, value: str | None) -> str | None:
        return validate_icon(value) if value is not None else None

class DocumentIconWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    icon: str | None

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

class DocumentParentMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_document_id: UUID | None

class DocumentOrderNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["tag", "document"]
    id: UUID

class DocumentOrderMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: DocumentOrderNode
    parent_id: UUID | None = None
    parent_document_id: UUID | None = None
    list_only: bool = False
    anchor: DocumentOrderNode | None = None
    after: bool = False

    @model_validator(mode="after")
    def validate_parent(self) -> DocumentOrderMove:
        if self.parent_document_id is not None and (self.parent_id is not None or self.list_only or self.node.kind != "document"):
            raise ValueError("A document parent only accepts documents outside the flat list")
        return self

class DocumentOrderSort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: UUID | None = None
    descending: bool = False

class DocumentTagIconWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    data: str

    @field_validator("data")
    @classmethod
    def valid_data(cls, value: str) -> str:
        if not value.startswith("data:image/"):
            raise ValueError("Expected an uploaded image")
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
    parent_document_id: UUID | None = None
    include_descendants: bool = True
    include_owners: bool = False
    include_keywords: bool = True
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
        if self.tag_id is not None and self.parent_document_id is not None:
            raise ValueError("Choose either a folder or a document parent")
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
    parent_document_id: UUID | None = None
    children_count: int = Field(default=0, ge=0)
    position: int = 0
    tags: list[DocumentTagPublic] = Field(default_factory=list[DocumentTagPublic])
    owner_label: str = ""
    item: DocumentPublic
    user_access: DocumentAccess = Field(default_factory=lambda: DocumentAccess(can_read=False, can_write=False))
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
    item: DocumentDetail
    agent_id: int | None = Field(default=None, gt=0)

class DocumentResourceRedirect(BaseModel):
    """A verified historical document reference now owned by another domain."""

    resource_type: Literal["dataset"] = "dataset"
    resource_uri: str = Field(pattern=r"^data://[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")

class DocumentDatasetAttachment(BaseModel):
    uri: str
    title: str | None
    available: bool

class DocumentDatasetAttachments(BaseModel):
    items: list[DocumentDatasetAttachment]
    lock_version: int

class DocumentDatasetAttachmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID
    expected_lock_version: int = Field(ge=1)

class DocumentInternalAttachmentWrite(BaseModel):
    uris: list[str] = Field(min_length=1, max_length=150)
    resource_agent_id: int = Field(gt=0)
    expected_lock_version: int = Field(ge=1)
    remove: bool = False

class DocumentProcessAttachmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uri: str = Field(max_length=4096)
    expected_lock_version: int = Field(ge=1)
    remove: bool = False

DocumentCollaborator = Collaborator

DocumentSharing = SharingState

DocumentSharingGrantUpdate = GrantUpdate

DocumentSharingLevelUpdate = SharingUpdate

DocumentSharingUpdate = SingleGrantUpdate

DocumentOwnerKind = Literal["agent", "user"]

class DocumentOwnerOption(BaseModel):
    kind: DocumentOwnerKind
    id: int = Field(gt=0)
    label: str
    subtitle: str
    avatar_url: str | None = None
    has_avatar: bool = False
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
    document_type: Literal["html"] = "html"
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

class DocumentGlobalAccessUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=1)
    global_access: DocumentGlobalAccess

class DocumentDeletionResult(BaseModel):
    document_id: UUID
    resources_deleted: int = 0

class GoalFolderReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = Field(default=None, gt=0)
    goal_id: UUID | None = None

class GoalFolderReconciliationResult(BaseModel):
    job_id: UUID

class DocumentGrantUpdate(BaseModel):
    can_write: bool
    expected_lock_version: int | None = Field(default=None, ge=1)
