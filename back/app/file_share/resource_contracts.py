"""Typed contracts returned by the URI-oriented file facade."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from app.agent.contracts import RuntimeName
from app.tools.contracts import FileIndexingMode

from .resource_uri import parse_resource_uri

if TYPE_CHECKING:
    from app.agent import AgentManagementScope


ResourceCapability = Literal[
    "append",
    "copy",
    "create",
    "delete",
    "edit",
    "info",
    "list",
    "move",
    "read",
    "rename",
    "search",
    "share",
    "write",
]


def _empty_capabilities() -> list[ResourceCapability]:
    return []


def _empty_descriptors() -> list["ResourceDescriptor"]:
    return []


def _empty_search_hits() -> list["ResourceSearchHit"]:
    return []


@dataclass(frozen=True, slots=True)
class ResourceContext:
    """Server-owned authorization and runtime context for one resource operation."""

    agent_id: int
    runtime: RuntimeName
    task_id: UUID | None = None
    console_resource: Any | None = None
    language: str | None = None
    skill_management: bool = False
    conversation_turn: object | None = None
    management_scope: AgentManagementScope | None = None
    browser_navigation: bool = False


class ResourceDescriptor(BaseModel):
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    uri: str
    name: str = ""
    label_code: str | None = None  # Optional system label translated by UI consumers.
    is_collection: bool = False
    media_type: str = "application/octet-stream"
    size: int | None = Field(default=None, ge=0)
    modified_at: str | None = None
    revision: int | None = Field(default=None, ge=1)
    lock_version: int | None = Field(default=None, ge=1)
    checksum: str | None = None
    etag: str | None = None
    capabilities: list[ResourceCapability] = Field(default_factory=_empty_capabilities)
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])

    @computed_field
    @property
    def entry_name(self) -> str:
        """Unique navigation key in the canonical parent, independent of source labels.

        ``name`` remains the original filename/title used for display and copies.
        URI segments carry identity even when two attachments share a filename.
        """
        reference = parse_resource_uri(self.uri, allow_empty=True)
        if reference.scheme in {"http", "https"}:
            from urllib.parse import unquote, urlsplit

            path = urlsplit(str(reference)).path.rstrip("/")
            return unquote(path.rsplit("/", 1)[-1]) or reference.scheme
        return reference.segments[-1] if reference.segments else reference.scheme


class ResourceListing(BaseModel):
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    uri: str
    entries: list[ResourceDescriptor] = Field(default_factory=_empty_descriptors)
    ancestors: list[ResourceDescriptor] = Field(default_factory=_empty_descriptors)
    truncated: bool = False
    next_cursor: str | None = None


class ResourceRead(BaseModel):
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    uri: str
    content: str
    encoding: Literal["utf-8", "base64"] = "utf-8"
    media_type: str = "text/plain"
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    revision: int | None = Field(default=None, ge=1)
    etag: str | None = None


class EditorialResourceRead(ResourceRead):
    """HTML-only read metadata; native and skill read contracts stay unchanged."""

    offset_unit: Literal["block"] = "block"
    content_profile: Literal["rich-text", "document"]
    content_profile_version: int = 1
    blocks: list[dict[str, Any]] = Field(default_factory=lambda: list[dict[str, Any]]())


class ResourceMutation(BaseModel):
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    uri: str
    operation: Literal["append", "create", "delete", "edit", "move", "rename", "write"]
    state: str
    source_uri: str | None = None
    size: int | None = Field(default=None, ge=0)
    revision: int | None = Field(default=None, ge=1)
    lock_version: int | None = Field(default=None, ge=1)
    name: str | None = None


class ResourceTransfer(BaseModel):
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    source_uri: str
    uri: str
    size: int = Field(ge=0)
    moved: bool = False


class ResourceSearchHit(BaseModel):
    conflicts: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    resource: ResourceDescriptor
    score: float | None = None
    excerpt: str = ""
    retrieval_sources: list[str] = Field(default_factory=list[str])
    source_refs: list[str] = Field(default_factory=list[str])
    passages: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class ResourceSearchResult(BaseModel):
    evidence_status: Literal["unassessed", "no_evidence"] | None = None
    indexing_status: Literal["excluded", "indexed", "failed"] = "excluded"
    uri: str
    query: str
    mode: Literal["name", "text", "semantic"]
    hits: list[ResourceSearchHit] = Field(default_factory=_empty_search_hits)
    truncated: bool = False
    next_cursor: str | None = None
    retrieval_mode: Literal["lexical", "hybrid"] | None = None
    relevance_status: Literal["matched", "no_sufficient_evidence"] | None = None
    degraded: bool = False
    degradation_reason: str | None = None
    ranking_version: str | None = None
    candidate_window_exhausted: bool = False
    index_coverage: dict[str, Any] | None = None


class ResourceSchemeDescription(BaseModel):
    """Indexing preferences cover file transports, never Messenger branches."""
    scheme: str
    label: str
    label_code: str | None = None
    example: str
    capabilities: list[ResourceCapability]
    native: bool
    root_listable: bool = True
    file_indexing_mode: FileIndexingMode = "excluded"


@dataclass(frozen=True, slots=True)
class MaterializedResource:
    """Server-side local copy of a resource, never exposed as a model URI."""

    uri: str
    name: str
    media_type: str
    size: int


@dataclass(frozen=True, slots=True)
class DeliveredResource:
    """Resource copied to a Messenger destination through bounded staging."""

    source_uri: str
    uri: str
    name: str
    media_type: str
    size: int


@runtime_checkable
class ResourceMetadataTransport(Protocol):
    async def resource_info(
        self, path: str, *, include_sha256: bool = False
    ) -> "FileEntry": ...


@runtime_checkable
class ResourceBatchMetadataTransport(Protocol):
    """Live metadata, omitting inaccessible paths and propagating cancellation."""

    async def resource_infos(self, paths: Sequence[str]) -> dict[str, FileEntry]: ...


@runtime_checkable
class ResourceListingTransport(Protocol):
    async def resource_list(
        self, path: str, *, recursive: bool, limit: int
    ) -> "FileListing": ...


@runtime_checkable
class ResourcePaginatedListingTransport(Protocol):
    async def resource_list_page(
        self, path: str, *, recursive: bool, limit: int, cursor: str | None = None
    ) -> "FileListing": ...


@runtime_checkable
class ResourceDeletionTransport(Protocol):
    async def resource_delete(self, path: str) -> "FileMutation": ...


@runtime_checkable
class ResourceCollectionDeletionTransport(Protocol):
    """Explicit recursive removal; ordinary file deletion remains non-recursive."""

    async def resource_delete_collection(self, path: str) -> "FileMutation": ...


@runtime_checkable
class ResourceConditionalDeletionTransport(Protocol):
    async def resource_delete_conditional(
        self, path: str, *, expected_etag: str
    ) -> "FileMutation": ...


@runtime_checkable
class ResourceRelocationTransport(Protocol):
    async def resource_copy(
        self, source: str, destination: str, *, overwrite: bool
    ) -> "FileMutation": ...

    async def resource_move(
        self, source: str, destination: str, *, overwrite: bool
    ) -> "FileMutation": ...


__all__ = [
    "ResourceCapability",
    "ResourceContext",
    "DeliveredResource",
    "ResourceDescriptor",
    "ResourceListing",
    "MaterializedResource",
    "ResourceMutation",
    "ResourceDeletionTransport",
    "ResourceConditionalDeletionTransport",
    "ResourceListingTransport",
    "ResourcePaginatedListingTransport",
    "ResourceMetadataTransport",
    "ResourceBatchMetadataTransport",
    "ResourceRelocationTransport",
    "ResourceSchemeDescription",
    "ResourceSearchHit",
    "ResourceSearchResult",
    "ResourceRead",
    "ResourceTransfer",
]


from .file_contracts import FileEntry, FileListing, FileMutation
