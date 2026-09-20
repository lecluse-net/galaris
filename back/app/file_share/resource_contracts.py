"""Typed contracts returned by the URI-oriented file facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

from app.agent.contracts import RuntimeName


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


class ResourceDescriptor(BaseModel):
    uri: str
    name: str = ""
    is_collection: bool = False
    media_type: str = "application/octet-stream"
    size: int | None = Field(default=None, ge=0)
    modified_at: str | None = None
    revision: int | None = Field(default=None, ge=1)
    checksum: str | None = None
    capabilities: list[ResourceCapability] = Field(default_factory=_empty_capabilities)
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])


class ResourceListing(BaseModel):
    uri: str
    entries: list[ResourceDescriptor] = Field(default_factory=_empty_descriptors)
    truncated: bool = False
    next_cursor: str | None = None


class ResourceRead(BaseModel):
    uri: str
    content: str
    encoding: Literal["utf-8", "base64"] = "utf-8"
    media_type: str = "text/plain"
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    revision: int | None = Field(default=None, ge=1)


class EditorialResourceRead(ResourceRead):
    """HTML-only read metadata; native and skill read contracts stay unchanged."""

    offset_unit: Literal["block"] = "block"
    content_profile: Literal["rich-text", "document"]
    content_profile_version: int = 1
    blocks: list[dict[str, Any]] = Field(default_factory=lambda: list[dict[str, Any]]())


class ResourceMutation(BaseModel):
    uri: str
    operation: Literal["append", "create", "delete", "edit", "move", "write"]
    state: str
    source_uri: str | None = None
    size: int | None = Field(default=None, ge=0)
    revision: int | None = Field(default=None, ge=1)


class ResourceTransfer(BaseModel):
    source_uri: str
    uri: str
    size: int = Field(ge=0)
    moved: bool = False


class ResourceSearchHit(BaseModel):
    resource: ResourceDescriptor
    score: float | None = None
    excerpt: str = ""
    retrieval_sources: list[str] = Field(default_factory=list[str])
    source_refs: list[str] = Field(default_factory=list[str])
    passages: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class ResourceSearchResult(BaseModel):
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
    scheme: str
    label: str
    example: str
    capabilities: list[ResourceCapability]
    native: bool


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
class ResourceListingTransport(Protocol):
    async def resource_list(
        self, path: str, *, recursive: bool, limit: int
    ) -> "FileListing": ...


@runtime_checkable
class ResourceDeletionTransport(Protocol):
    async def resource_delete(self, path: str) -> "FileMutation": ...


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
    "ResourceListingTransport",
    "ResourceMetadataTransport",
    "ResourceRelocationTransport",
    "ResourceSchemeDescription",
    "ResourceSearchHit",
    "ResourceSearchResult",
    "ResourceRead",
    "ResourceTransfer",
]


from .file_contracts import FileEntry, FileListing, FileMutation
