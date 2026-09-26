"""URI-oriented virtual file facade across Galaris resource providers."""

from __future__ import annotations

import base64
import asyncio
import json
import mimetypes
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import unquote, urlsplit
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from .file_share_service import (
    describe_targets,
    resolve_resource_transport_with_service,
)
from .messenger_transport import MessengerFileTransport
from .resource_contracts import (
    MaterializedResource,
    ResourceCapability,
    ResourceContext,
    ResourceDescriptor,
    ResourceDeletionTransport,
    ResourceListing,
    ResourceListingTransport,
    ResourceMetadataTransport,
    ResourceMutation,
    ResourceRelocationTransport,
    ResourceSchemeDescription,
    ResourceSearchHit,
    ResourceSearchResult,
    ResourceRead,
    EditorialResourceRead,
    ResourceTransfer,
)
from .resource_uri import (
    ResourceUri, ResourceUriError, ResourceValidationError,
    ResourceRevisionConflict, parse_resource_uri,
)
from .service_references import (
    normalize_destination_reference,
    normalize_source_reference,
    reference_filename,
)
from .transport import FileTransport, transfer
from .file_contracts import FileResourceTransport, FileEntry
from .web_transport import PublicHttpsFileTransport


_LIST_LIMIT = 500
_TEXT_READ_LIMIT = 50_000
_TEXT_WRITE_LIMIT = 500_000
_FILE_WRITE_LIMIT = 16_000_000
_BINARY_READ_LIMIT = 1_048_576
_SEARCH_SCAN_LIMIT = 500

_MUTABLE_FILE_CAPABILITIES: list[ResourceCapability] = [
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
    "write",
]
_TRANSPORT_CAPABILITIES: list[ResourceCapability] = [
    "copy",
    "create",
    "info",
    "read",
    "write",
]
_NEXTCLOUD_CAPABILITIES: list[ResourceCapability] = [
    capability
    for capability in _MUTABLE_FILE_CAPABILITIES
    if capability != "append"
]
_MEMORY_CAPABILITIES: list[ResourceCapability] = [
    "copy",
    "info",
    "read",
    "search",
]
_DOCUMENT_CAPABILITIES: list[ResourceCapability] = [
    "append",
    "copy",
    "edit",
    "info",
    "read",
    "search",
    "write",
]
_DOCUMENT_SCHEME_CAPABILITIES: list[ResourceCapability] = [
    "create",
    "delete",
    "list",
    *_DOCUMENT_CAPABILITIES,
]
_DOCUMENT_ATTACHMENT_CAPABILITIES: list[ResourceCapability] = [
    "copy",
    "info",
    "read",
]
_DOCUMENT_ATTACHMENT_COLLECTION_CAPABILITIES: list[ResourceCapability] = [
    "info",
    "list",
    "search",
]
_MESSENGER_CAPABILITIES: list[ResourceCapability] = [
    "copy",
    "info",
    "list",
    "read",
    "search",
    "write",
]
_WEB_CAPABILITIES: list[ResourceCapability] = ["copy", "info", "read"]
_GALARIS_CAPABILITIES: list[ResourceCapability] = [
    "copy",
    "info",
    "list",
    "read",
    "search",
]
_MAIL_CAPABILITIES: list[ResourceCapability] = ["copy", "info", "list", "read"]


def _json_model(value: Any) -> str:
    return json.dumps(
        jsonable_encoder(value, exclude_none=True),
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _resource_name(reference: ResourceUri, fallback: str = "resource") -> str:
    locator = (
        urlsplit(str(reference)).path
        if reference.scheme in {"http", "https"}
        else reference.locator
    )
    name = PurePosixPath(unquote(locator.rstrip("/"))).name
    return name if name not in {"", ".", ".."} else fallback


def _uri(scheme: str, locator: str, *, collection: bool = False) -> str:
    suffix = "/" if collection and locator and not locator.endswith("/") else ""
    return str(parse_resource_uri(f"{scheme}://{locator}{suffix}", allow_empty=True))


def _document_attachment_ids(
    reference: ResourceUri,
) -> tuple[UUID, UUID | None] | None:
    """Return document/attachment ids for the document attachment URI namespace."""

    if reference.scheme != "document":
        return None
    segments = reference.segments
    if len(segments) == 2 and segments[1] == "attachments":
        return UUID(segments[0]), None
    if len(segments) == 3 and segments[1] == "attachments":
        return UUID(segments[0]), UUID(segments[2])
    return None


def _attachment_capabilities(can_write: bool) -> list[ResourceCapability]:
    capabilities = list(_DOCUMENT_ATTACHMENT_CAPABILITIES)
    if can_write:
        capabilities.append("delete")
    return capabilities


def _attachment_collection_capabilities(
    can_write: bool,
) -> list[ResourceCapability]:
    capabilities = list(_DOCUMENT_ATTACHMENT_COLLECTION_CAPABILITIES)
    if can_write:
        capabilities.append("create")
    return capabilities


def _resource_read_from_bytes(
    reference: ResourceUri,
    content: bytes,
    *,
    media_type: str,
    start: int,
    limit: int,
) -> ResourceRead:
    textual = media_type.startswith("text/") or media_type in {
        "application/json",
        "application/xml",
    } or media_type.endswith(("+json", "+xml"))
    text_content: str | None = None
    if textual:
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            textual = False
    if not textual:
        if len(content) > _BINARY_READ_LIMIT:
            raise ResourceValidationError(
                f"Binary resource is {len(content)} bytes; file_read can return base64 only "
                f"up to {_BINARY_READ_LIMIT} bytes. Pass its URI to a specialized "
                "tool, or copy it to console:// when console software must handle it."
            )
        return ResourceRead(
            uri=str(reference),
            content=base64.b64encode(content).decode("ascii"),
            encoding="base64",
            media_type=media_type,
            start=0,
            end=len(content),
            total=len(content),
        )
    assert text_content is not None
    bounded_start = min(start, len(text_content))
    end = min(len(text_content), bounded_start + limit)
    return ResourceRead(
        uri=str(reference),
        content=text_content[bounded_start:end],
        media_type=media_type,
        start=bounded_start,
        end=end,
        total=len(text_content),
        next_offset=end if end < len(text_content) else None,
    )


def preferred_local_resource_uri(ctx: ResourceContext, path: str) -> str:
    """Return the console URI for a run that explicitly owns a console."""

    if ctx.console_resource is None:
        raise RuntimeError(
            "No local filesystem is available; use a writable provider returned by "
            "file_schemes."
        )
    return _uri("console", path)


def _entry_descriptor(
    scheme: str,
    entry: FileEntry,
    *,
    capabilities: list[ResourceCapability] | None = None,
) -> ResourceDescriptor:
    return ResourceDescriptor(
        uri=_uri(scheme, entry.path, collection=entry.is_dir),
        name=PurePosixPath(entry.path).name or entry.path,
        is_collection=entry.is_dir,
        media_type=entry.mime_type,
        size=None if entry.is_dir else entry.size,
        modified_at=entry.modified_at or None,
        checksum=entry.sha256 or None,
        capabilities=list(capabilities or _MUTABLE_FILE_CAPABILITIES),
    )


def _console_uri(path: str, *, collection: bool = False) -> str:
    """Return the canonical URI for a console-home-relative path."""

    normalized = "" if path in {"", "."} else path.strip("/")
    return _uri("console", normalized, collection=collection)


async def _console_transport(ctx: ResourceContext) -> FileResourceTransport:
    from app.console import ConsoleRunResource, build_run_resource

    resource = ctx.console_resource
    transport = (
        resource.files
        if isinstance(resource, ConsoleRunResource)
        else (await build_run_resource(ctx.agent_id)).files
    )
    return transport


def _as_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _as_int(value)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _console_path(reference: ResourceUri, *, allow_root: bool = False) -> str:
    path = reference.decoded_locator.strip("/")
    if not path and not allow_root:
        raise ResourceUriError("console:// requires a file path.")
    return path or "."


async def _console_reference(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> tuple[FileResourceTransport, str]:
    if reference.scheme != "console":
        raise ResourceUriError(f"{reference.scheme}:// is not the console provider.")
    transport = await _console_transport(ctx)
    path = await transport.normalize_resource_path(
        _console_path(reference, allow_root=True),
        allow_root=True,
    )
    return transport, path


async def _connected_transport(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> tuple[FileTransport, str, str, str]:
    if reference.scheme == "http":
        raise ResourceUriError("http:// resources are disabled; use public HTTPS.")
    if reference.scheme == "https":
        return PublicHttpsFileTransport(), "https", str(reference), ""
    if reference.scheme == "image":
        raise ResourceUriError(
            "image:// is not a file provider; use the dedicated image tools."
        )
    if reference.scheme == "galaris":
        raise ResourceUriError(
            "galaris:// is a native provider, not a connected file service."
        )
    transport, service = await resolve_resource_transport_with_service(
        ctx.agent_id,
        reference.scheme,
        reference.decoded_locator,
        language=ctx.language,
    )
    source = normalize_source_reference(service, reference.decoded_locator)
    if isinstance(transport, MessengerFileTransport):
        transport = transport.for_task(ctx.task_id, reference.scheme)
    return transport, service, source.remote, source.target


async def _connected_destination_transport(
    ctx: ResourceContext,
    reference: ResourceUri,
    *,
    fallback_locator: str,
) -> tuple[FileTransport, str]:
    """Resolve a writable provider without imposing source-reference semantics."""

    if reference.scheme in {"http", "https"}:
        raise PermissionError(f"{reference.scheme}:// resources are read-only.")
    if reference.scheme == "image":
        raise ResourceUriError(
            "image:// is not a file provider; use the dedicated image tools."
        )
    if reference.scheme == "galaris":
        raise ResourceUriError(
            "galaris:// is a native provider, not a connected file service."
        )
    transport, service = await resolve_resource_transport_with_service(
        ctx.agent_id,
        reference.scheme,
        reference.decoded_locator or fallback_locator,
        language=ctx.language,
    )
    if isinstance(transport, MessengerFileTransport):
        transport = transport.for_task(ctx.task_id, reference.scheme)
    return transport, service


async def _transfer_source_name(
    ctx: ResourceContext,
    source: ResourceUri,
) -> str:
    """Return the provider-visible source filename for a collection destination."""

    descriptor = await resource_info(ctx, source)
    return reference_filename(descriptor.name, _resource_name(source, "resource.bin"))


async def _existing_destination_is_collection(
    ctx: ResourceContext,
    destination: ResourceUri,
) -> bool:
    """Detect an existing collection even when the caller omitted the trailing slash."""

    if destination.is_collection:
        return True
    if destination.scheme == "console":
        transport, path = await _console_reference(ctx, destination)
        try:
            entry = await transport.file_info(path, include_sha256=False)
        except FileNotFoundError:
            return False
        return entry.is_dir
    if destination.scheme == "galaris":
        segments = destination.segments
        # Accept the common model shorthand for the root of one editable skill package.
        return len(segments) == 2 and segments[0] == "skill"
    if destination.scheme in {"document", "memory", "http", "https"}:
        return False
    transport, service = await _connected_destination_transport(
        ctx,
        destination,
        fallback_locator="destination-placeholder",
    )
    if isinstance(transport, ResourceMetadataTransport):
        try:
            entry = await transport.resource_info(
                destination.decoded_locator,
                include_sha256=False,
            )
        except FileNotFoundError:
            pass
        else:
            return entry.is_dir
    segments = destination.segments
    if service in {"affine", "image", "messenger"}:
        return len(segments) == 1
    if service == "grav":
        last_segment = segments[-1] if segments else ""
        return bool(last_segment) and "." not in last_segment
    return False


async def _resolve_transfer_destination(
    ctx: ResourceContext,
    source: ResourceUri,
    destination: ResourceUri,
) -> ResourceUri:
    """Complete an existing collection destination with the source filename."""

    if destination.is_collection or not await _existing_destination_is_collection(
        ctx, destination
    ):
        return destination
    source_name = await _transfer_source_name(ctx, source)
    locator = "/".join(
        part
        for part in (destination.decoded_locator.rstrip("/"), source_name)
        if part
    )
    return parse_resource_uri(f"{destination.scheme}://{locator}")


def _canonical_created_locator(
    scheme: str,
    service: str,
    location: str,
    *,
    target: str,
    filename: str,
) -> str:
    if service == "messenger":
        return location.removeprefix("messenger:").strip("/")
    if service == "affine":
        key = unquote(urlsplit(location).path.rstrip("/").rsplit("/", 1)[-1])
        return f"{target.strip('/')}/{key}"
    if service == "grav" and location.startswith(("http://", "https://")):
        path = unquote(urlsplit(location).path).strip("/")
        return path or f"{target.strip('/')}/{filename}".strip("/")
    return location.strip("/") or f"{target.strip('/')}/{filename}".strip("/")


async def list_schemes(ctx: ResourceContext) -> list[ResourceSchemeDescription]:
    """Describe native and connected resource schemes for an agent."""

    galaris_capabilities = list(_GALARIS_CAPABILITIES)
    if ctx.skill_management:
        galaris_capabilities.extend(("append", "create", "delete", "edit", "move", "write"))
    schemes = [
        ResourceSchemeDescription(
            scheme="https",
            label="Public HTTPS resource",
            example="https://example.org/files/report.pdf",
            capabilities=list(_WEB_CAPABILITIES),
            native=True,
        ),
        ResourceSchemeDescription(
            scheme="memory",
            label="Galaris memory",
            example="memory://<uuid>",
            capabilities=list(_MEMORY_CAPABILITIES),
            native=True,
        ),
        ResourceSchemeDescription(
            scheme="document",
            label="Galaris document",
            example="document://<uuid>",
            capabilities=list(_DOCUMENT_SCHEME_CAPABILITIES),
            native=True,
        ),
        ResourceSchemeDescription(
            scheme="galaris",
            label="Galaris business resources",
            example="galaris://task/<uuid>",
            capabilities=galaris_capabilities,
            native=True,
        ),
    ]
    if ctx.console_resource is not None:
        schemes.append(
            ResourceSchemeDescription(
                scheme="console",
                label="Local files (SSH console home)",
                example="console://reports/result.pdf",
                capabilities=list(_MUTABLE_FILE_CAPABILITIES),
                native=True,
            )
        )
    targets = await describe_targets(ctx.agent_id, language=ctx.language)
    for target in targets:
        scheme = target["code"]
        capabilities: list[ResourceCapability] = []
        if bool(target["has_file_share"]):
            capabilities.extend(
                _MAIL_CAPABILITIES
                if target["service"] == "mail"
                else (
                    _NEXTCLOUD_CAPABILITIES
                    if target["service"] == "nextcloud"
                    else _TRANSPORT_CAPABILITIES
                )
            )
        if bool(target["has_messenger"]):
            capabilities.extend(_MESSENGER_CAPABILITIES)
        capabilities = list(dict.fromkeys(capabilities))
        example = (
            f"{scheme}://<room-id>/<attachment-id>"
            if bool(target["has_messenger"]) and not bool(target["has_file_share"])
            else (
                f"{scheme}://attachment/<message-ref>/<part-id>/file.ext"
                if target["service"] == "mail"
                else f"{scheme}://path/file.ext"
            )
        )
        if target["service"] == "affine":
            example = f"{scheme}://<workspace-id>/<blob-key>"
        schemes.append(
            ResourceSchemeDescription(
                scheme=scheme,
                label=target["label"],
                example=example,
                capabilities=capabilities,
                native=False,
            )
        )
    unique = {item.scheme: item for item in schemes}
    return [unique[scheme] for scheme in sorted(unique)]


async def resource_info(
    ctx: ResourceContext,
    uri: object,
    *,
    include_checksum: bool = False,
) -> ResourceDescriptor:
    reference = parse_resource_uri(uri, allow_empty=True)
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_info

        return await galaris_resource_info(ctx, reference)
    if reference.scheme == "console":
        transport, path = await _console_reference(ctx, reference)
        entry = await transport.file_info(path, include_sha256=include_checksum)
        descriptor = _entry_descriptor(reference.scheme, entry)
        descriptor.uri = _console_uri(entry.path, collection=entry.is_dir)
        return descriptor
    attachment_ids = _document_attachment_ids(reference)
    if attachment_ids is not None:
        from app.memory import (
            describe_document_attachment_file_resource,
            list_document_attachment_file_resources,
        )

        document_id, attachment_id = attachment_ids
        if attachment_id is None:
            data = await list_document_attachment_file_resources(
                document_id,
                agent_id=ctx.agent_id,
            )
            return ResourceDescriptor(
                uri=_uri(
                    "document",
                    f"{document_id}/attachments",
                    collection=True,
                ),
                name="attachments",
                is_collection=True,
                media_type="inode/directory",
                capabilities=_attachment_collection_capabilities(
                    bool(data["can_write"])
                ),
                metadata={"document_id": str(document_id)},
            )
        data = await describe_document_attachment_file_resource(
            document_id,
            attachment_id,
            agent_id=ctx.agent_id,
        )
        return ResourceDescriptor(
            uri=str(reference),
            name=str(data["name"]),
            media_type=str(data["media_type"]),
            size=_as_int(data["size_bytes"]),
            modified_at=str(data["created_at"]),
            capabilities=_attachment_capabilities(bool(data["can_write"])),
            metadata={
                "document_id": str(document_id),
                "attachment_id": str(attachment_id),
                "memory_item_id": data.get("memory_item_id"),
            },
        )
    if (
        reference.scheme in {"memory", "document"}
        and _document_attachment_ids(reference) is None
    ):
        from app.memory import describe_file_resource

        data = await describe_file_resource(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            expected_kind=cast(Literal["memory", "document"], reference.scheme),
        )
        capabilities = (
            list(_DOCUMENT_CAPABILITIES)
            if reference.scheme == "document" and bool(data["can_write"])
            else list(_MEMORY_CAPABILITIES)
        )
        return ResourceDescriptor(
            uri=str(reference),
            name=str(data["filename"] or data["title"]),
            media_type=str(data["media_type"]),
            size=_as_int(data["size"]),
            modified_at=cast(str | None, data["updated_at"]),
            revision=_as_int(data["revision"]),
            checksum=str(data["checksum"]) if include_checksum else None,
            capabilities=capabilities,
            metadata=cast(dict[str, Any], data["metadata"]),
        )
    transport, service, remote, target = await _connected_transport(ctx, reference)
    if isinstance(transport, MessengerFileTransport):
        resource = await transport.describe_attachment_resource(target, remote)
        attachment = resource.attachment
        return ResourceDescriptor(
            uri=_uri(
                reference.scheme,
                f"{resource.room_locator}/{attachment.id}",
            ),
            name=attachment.name,
            media_type=attachment.mime_type or "application/octet-stream",
            size=attachment.size_bytes,
            capabilities=list(_MESSENGER_CAPABILITIES),
        )
    if isinstance(transport, ResourceMetadataTransport):
        entry = await transport.resource_info(
            str(reference)
            if reference.scheme == "https"
            else reference.decoded_locator,
            include_sha256=include_checksum,
        )
        if reference.scheme == "https":
            return ResourceDescriptor(
                uri=str(reference),
                name=_resource_name(reference),
                media_type=entry.mime_type,
                size=entry.size,
                modified_at=entry.modified_at or None,
                capabilities=list(_WEB_CAPABILITIES),
            )
        descriptor = _entry_descriptor(
            reference.scheme,
            entry,
            capabilities=(
                _MAIL_CAPABILITIES if service == "mail" else _TRANSPORT_CAPABILITIES
            ),
        )
        if service == "affine" and not PurePosixPath(descriptor.name).suffix:
            descriptor.name += mimetypes.guess_extension(entry.mime_type) or ""
        return descriptor
    return ResourceDescriptor(
        uri=str(reference),
        name=_resource_name(reference),
        media_type=mimetypes.guess_type(_resource_name(reference))[0]
        or "application/octet-stream",
        capabilities=list(_TRANSPORT_CAPABILITIES),
    )


async def resource_list(
    ctx: ResourceContext,
    uri: object,
    *,
    recursive: bool = False,
    max_entries: int = 100,
    cursor: str | None = None,
) -> ResourceListing:
    reference = parse_resource_uri(uri, allow_empty=True)
    limit = max(1, min(max_entries, _LIST_LIMIT))
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_list

        return await galaris_resource_list(
            ctx,
            reference,
            max_entries=limit,
            cursor=cursor,
        )
    if reference.scheme == "console":
        if cursor:
            raise NotImplementedError(
                f"{reference.scheme}:// does not expose paginated listing cursors."
            )
        transport, path = await _console_reference(ctx, reference)
        listing = await transport.file_list(path, recursive=recursive, limit=limit)
        entries: list[ResourceDescriptor] = []
        for entry in listing.entries:
            descriptor = _entry_descriptor(reference.scheme, entry)
            descriptor.uri = _console_uri(entry.path, collection=entry.is_dir)
            entries.append(descriptor)
        return ResourceListing(
            uri=_console_uri(listing.path, collection=reference.is_collection),
            entries=entries,
            truncated=listing.truncated,
        )
    attachment_ids = _document_attachment_ids(reference)
    if attachment_ids is not None:
        from app.memory import list_document_attachment_file_resources

        document_id, attachment_id = attachment_ids
        if attachment_id is not None:
            raise NotADirectoryError(str(reference))
        data = await list_document_attachment_file_resources(
            document_id,
            agent_id=ctx.agent_id,
        )
        offset = max(0, int(cursor or "0"))
        attachments = cast(list[dict[str, object]], data["attachments"])
        page = attachments[offset : offset + limit]
        can_write = bool(data["can_write"])
        return ResourceListing(
            uri=_uri(
                "document",
                f"{document_id}/attachments",
                collection=True,
            ),
            entries=[
                ResourceDescriptor(
                    uri=_uri(
                        "document",
                        f"{document_id}/attachments/{attachment['id']}",
                    ),
                    name=str(attachment["name"]),
                    media_type=str(attachment["media_type"]),
                    size=_as_int(attachment["size_bytes"]),
                    modified_at=str(attachment["created_at"]),
                    capabilities=_attachment_capabilities(can_write),
                    metadata={
                        "document_id": str(document_id),
                        "attachment_id": str(attachment["id"]),
                        "memory_item_id": attachment.get("memory_item_id"),
                    },
                )
                for attachment in page
            ],
            truncated=offset + len(page) < len(attachments),
            next_cursor=(
                str(offset + len(page))
                if offset + len(page) < len(attachments)
                else None
            ),
        )
    if (
        reference.scheme in {"memory", "document"}
        and _document_attachment_ids(reference) is None
    ):
        from app.memory import search_file_resources

        data = await search_file_resources(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            expected_kind=cast(
                Literal["memory", "document"], reference.scheme
            ),
            query="",
            mode="name",
            limit=limit,
            offset=max(0, int(cursor or "0")),
        )
        entries = [
            ResourceDescriptor(
                uri=_uri(reference.scheme, str(item["id"])),
                name=str(item["filename"] or item["title"]),
                media_type=str(item["media_type"]),
                size=_as_int(item["size"]),
                modified_at=cast(str | None, item["updated_at"]),
                revision=_as_int(item["revision"]),
                checksum=str(item["checksum"]),
                capabilities=(
                    list(_DOCUMENT_CAPABILITIES)
                    if reference.scheme == "document" and bool(item["can_write"])
                    else list(_MEMORY_CAPABILITIES)
                ),
                metadata=cast(dict[str, Any], item["metadata"]),
            )
            for item in cast(list[dict[str, object]], data["hits"])
        ]
        return ResourceListing(
            uri=str(reference),
            entries=entries,
            truncated=bool(data["has_more"]),
            next_cursor=(
                str(data["next_offset"])
                if data["next_offset"] is not None
                else None
            ),
        )
    messenger_probe = ResourceUri(
        reference.scheme,
        f"{reference.locator.rstrip('/')}/placeholder".lstrip("/"),
    )
    transport, service, _remote, _target = await _connected_transport(
        ctx,
        messenger_probe,
    )
    if isinstance(transport, MessengerFileTransport):
        if cursor:
            raise NotImplementedError(
                f"{reference.scheme}:// Messenger resources do not expose paginated "
                "listing cursors."
            )
        segments = reference.segments
        if len(segments) != 1:
            raise ResourceUriError(
                f"List {reference.scheme}://<room>/ to enumerate attachments."
            )
        resources = await transport.list_attachment_resources(
            segments[0], limit=limit + 1
        )
        room_locator = resources[0].room_locator if resources else segments[0]
        return ResourceListing(
            uri=_uri(reference.scheme, room_locator, collection=True),
            entries=[
                ResourceDescriptor(
                    uri=_uri(
                        reference.scheme,
                        f"{resource.room_locator}/{resource.attachment.id}",
                    ),
                    name=resource.attachment.name,
                    media_type=(
                        resource.attachment.mime_type or "application/octet-stream"
                    ),
                    size=resource.attachment.size_bytes,
                    capabilities=list(_MESSENGER_CAPABILITIES),
                )
                for resource in resources[:limit]
            ],
            truncated=len(resources) > limit,
        )
    if not isinstance(transport, ResourceListingTransport):
        raise NotImplementedError(f"{reference.scheme}:// does not support listing.")
    if cursor:
        raise NotImplementedError(
            f"{reference.scheme}:// does not expose paginated listing cursors."
        )
    listing = await transport.resource_list(
        reference.decoded_locator,
        recursive=recursive,
        limit=limit,
    )
    return ResourceListing(
        uri=str(reference),
        entries=[
            _entry_descriptor(
                reference.scheme,
                entry,
                capabilities=(
                    _MAIL_CAPABILITIES
                    if service == "mail"
                    else _TRANSPORT_CAPABILITIES
                ),
            )
            for entry in listing.entries
        ],
        truncated=listing.truncated,
    )


async def materialize_resource(
    ctx: ResourceContext,
    uri: object,
    destination: Path,
    *,
    max_bytes: int,
    timeout_seconds: float = 120,
) -> MaterializedResource:
    async with asyncio.timeout(timeout_seconds):
        return await _materialize_resource(ctx, uri, destination, max_bytes=max_bytes)


async def _materialize_resource(
    ctx: ResourceContext, uri: object, destination: Path, *, max_bytes: int,
) -> MaterializedResource:
    """Copy an authorized resource to a server-owned path with an explicit byte limit."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    reference = parse_resource_uri(uri)
    descriptor = await resource_info(ctx, reference)
    if descriptor.is_collection:
        raise IsADirectoryError(str(reference))
    if descriptor.size is not None and descriptor.size > max_bytes:
        raise ValueError(f"Resource exceeds the {max_bytes}-byte materialization limit")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if reference.scheme == "galaris" and reference.decoded_locator.startswith("skill/"):
            from .galaris_provider import galaris_skill_file_bytes

            content = await galaris_skill_file_bytes(ctx, reference)
            if len(content) > max_bytes:
                raise ValueError(
                    f"Resource exceeds the {max_bytes}-byte materialization limit"
                )
            destination.write_bytes(content)
            size = len(content)
        elif (attachment_ids := _document_attachment_ids(reference)) is not None:
            document_id, attachment_id = attachment_ids
            if attachment_id is None:
                raise IsADirectoryError(str(reference))
            from app.memory import read_document_attachment_file_resource

            _metadata, content = await read_document_attachment_file_resource(
                document_id,
                attachment_id,
                agent_id=ctx.agent_id,
            )
            if len(content) > max_bytes:
                raise ValueError(
                    f"Resource exceeds the {max_bytes}-byte materialization limit"
                )
            destination.write_bytes(content)
            size = len(content)
        elif reference.scheme in {"memory", "document", "galaris"}:
            offset = 0
            size = 0
            with destination.open("wb") as output:
                while True:
                    page = await resource_read(ctx, reference, offset=offset, max_chars=50_000)
                    if page.encoding == "base64":
                        if offset:
                            raise RuntimeError("Binary resource pagination is not supported.")
                        chunk = base64.b64decode(page.content, validate=True)
                    else:
                        chunk = page.content.encode("utf-8")
                    if len(chunk) > max_bytes - size:
                        raise ValueError(f"Resource exceeds the {max_bytes}-byte materialization limit")
                    output.write(chunk)
                    size += len(chunk)
                    if page.next_offset is None:
                        break
                    if page.next_offset <= offset:
                        raise RuntimeError("Resource pagination did not advance.")
                    offset = page.next_offset
        else:
            if reference.scheme == "console":
                rich_transport, remote = await _console_reference(ctx, reference)
                transport = cast(FileTransport, rich_transport)
                target = ""
            else:
                transport, _service, remote, target = await _connected_transport(
                    ctx, reference
                )
            size = await transport.download_to(remote, destination, target=target, max_bytes=max_bytes)
            actual_size = destination.stat().st_size
            if size != actual_size:
                size = actual_size
            if size > max_bytes:
                raise ValueError(
                    f"Resource exceeds the {max_bytes}-byte materialization limit"
                )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return MaterializedResource(
        uri=str(reference),
        name=descriptor.name or _resource_name(reference),
        media_type=descriptor.media_type,
        size=size,
    )


async def resource_read(
    ctx: ResourceContext,
    uri: object,
    *,
    offset: int = 0,
    max_chars: int = 20_000,
) -> ResourceRead:
    """Read UTF-8 text by page, or return a small binary resource as base64."""

    reference = parse_resource_uri(uri)
    start = max(0, offset)
    limit = max(1, min(max_chars, 2_000_000 if reference.scheme in {"memory", "document"} else _TEXT_READ_LIMIT))
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_read

        result = await galaris_resource_read(
            ctx,
            reference,
            offset=start,
            max_chars=limit,
        )
        return result
    attachment_ids = _document_attachment_ids(reference)
    if attachment_ids is not None:
        document_id, attachment_id = attachment_ids
        if attachment_id is None:
            raise IsADirectoryError(str(reference))
        from app.memory import read_document_attachment_file_resource

        metadata, content = await read_document_attachment_file_resource(
            document_id,
            attachment_id,
            agent_id=ctx.agent_id,
        )
        return _resource_read_from_bytes(
            reference,
            content,
            media_type=str(metadata["media_type"]),
            start=start,
            limit=limit,
        )
    if reference.scheme in {"memory", "document"}:
        from app.memory import read_file_resource_text

        data = await read_file_resource_text(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            expected_kind=cast(Literal["memory", "document"], reference.scheme),
            offset=start,
            max_chars=limit,
        )
        values = dict(
            uri=str(reference), content=str(data.get("content") or ""),
            media_type=str(data.get("media_type") or "text/plain"),
            start=_as_int(data.get("start")), end=_as_int(data.get("end")),
            total=_as_int(data.get("total")), next_offset=_as_optional_int(data.get("next_offset")),
            revision=_as_optional_int(data.get("revision")),
        )
        if data.get("media_type") == "text/html":
            return EditorialResourceRead.model_validate({**values, "content_profile": data.get("content_profile", "rich-text"), "blocks": data.get("blocks", [])})
        return ResourceRead.model_validate(values)

    affine_media_type: str | None = None
    if reference.scheme == "console":
        rich_transport, remote = await _console_reference(ctx, reference)
        transport = cast(FileTransport, rich_transport)
        target = ""
        result_uri = _console_uri(remote)
    else:
        transport, _service, remote, target = await _connected_transport(ctx, reference)
        result_uri = str(reference)
        if _service == "affine":
            affine_media_type = (await resource_info(ctx, reference)).media_type
    fd, temporary_name = tempfile.mkstemp(prefix="galaris_resource_read_")
    os.close(fd)
    temporary = Path(temporary_name)
    text: str | None = None
    try:
        await transport.download_to(remote, temporary, target=target)
        size = temporary.stat().st_size
        sample = temporary.read_bytes()[:8192]
        guessed_media_type = affine_media_type or mimetypes.guess_type(_resource_name(reference))[0]
        explicitly_textual = bool(
            guessed_media_type
            and (
                guessed_media_type.startswith("text/")
                or guessed_media_type
                in {"application/json", "application/xml", "application/javascript"}
                or guessed_media_type.endswith(("+json", "+xml"))
            )
        )
        is_binary = bool(guessed_media_type and not explicitly_textual) or b"\x00" in sample
        if not is_binary:
            try:
                text = temporary.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                is_binary = True
        media_type = guessed_media_type or (
            "application/octet-stream" if is_binary else "text/plain"
        )
        if is_binary:
            if size > _BINARY_READ_LIMIT:
                raise ResourceValidationError(
                    f"Binary resource is {size} bytes; file_read can return base64 only "
                    f"up to {_BINARY_READ_LIMIT} bytes. Pass its URI to a specialized "
                    "tool, or copy it to console:// when console software must handle it."
                )
            raw = temporary.read_bytes()
            return ResourceRead(
                uri=result_uri,
                content=base64.b64encode(raw).decode("ascii"),
                encoding="base64",
                media_type=media_type,
                start=0,
                end=len(raw),
                total=len(raw),
            )
    finally:
        temporary.unlink(missing_ok=True)
    if text is None:
        raise RuntimeError("Resource content detection did not produce readable text.")
    start = min(start, len(text))
    end = min(len(text), start + limit)
    return ResourceRead(
        uri=result_uri,
        content=text[start:end],
        media_type=media_type,
        start=start,
        end=end,
        total=len(text),
        next_offset=end if end < len(text) else None,
    )


async def resource_write_text(
    ctx: ResourceContext,
    uri: object,
    content: str,
    *,
    overwrite: bool = False,
) -> ResourceMutation:
    if len(content) > _TEXT_WRITE_LIMIT:
        raise ValueError(f"Text content exceeds {_TEXT_WRITE_LIMIT} characters.")
    reference = parse_resource_uri(uri)
    if reference.scheme == "console":
        transport, path = await _console_reference(ctx, reference)
        result = await transport.file_write_text(path, content, overwrite=overwrite)
        return ResourceMutation(
            uri=_console_uri(result.path),
            operation="write",
            state=result.state,
            size=result.size,
        )
    if reference.scheme == "document":
        if _document_attachment_ids(reference) is not None:
            raise PermissionError(
                "Document attachments are immutable; create a new attachment instead."
            )
        from app.memory import describe_file_resource, write_document_resource_text

        if not overwrite:
            raise FileExistsError(
                "document:// resources already exist; replacement must be explicit."
            )

        current = await describe_file_resource(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            expected_kind="document",
        )
        data = await write_document_resource_text(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            content=content,
            expected_revision=_as_optional_int(current.get("revision")),
        )
        return ResourceMutation(
            uri=str(reference),
            operation="write",
            state=str(data.get("state") or "written"),
            size=_as_optional_int(data.get("size")),
            revision=_as_optional_int(data.get("revision")),
        )
    if reference.scheme == "memory":
        raise PermissionError("memory:// resources are read-only through file tools.")
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_write

        if not reference.decoded_locator.startswith("skill/"):
            raise PermissionError(
                "galaris:// resources are read-only through file tools."
            )
        if not overwrite:
            raise FileExistsError(
                "galaris:// skill files already exist; replacement must be explicit."
            )
        return await galaris_resource_write(ctx, reference, content.encode("utf-8"))
    transport, service, _remote, _target = await _connected_transport(ctx, reference)
    if reference.scheme in {"http", "https"}:
        raise PermissionError(f"{reference.scheme}:// resources are read-only.")
    destination = normalize_destination_reference(
        service,
        reference.decoded_locator,
        fallback_filename=_resource_name(reference, "document.txt"),
    )
    if not overwrite:
        if isinstance(transport, ResourceMetadataTransport):
            try:
                await transport.resource_info(
                    reference.decoded_locator, include_sha256=False
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(str(reference))
    fd, temporary_name = tempfile.mkstemp(prefix="galaris_resource_write_")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        location = await transport.upload_from(
            temporary,
            destination.filename,
            target=destination.target,
        )
    finally:
        temporary.unlink(missing_ok=True)
    locator = _canonical_created_locator(
        reference.scheme,
        service,
        location,
        target=destination.target,
        filename=destination.filename,
    )
    return ResourceMutation(
        uri=_uri(reference.scheme, locator),
        operation="write",
        state="written",
        size=len(content.encode("utf-8")),
    )


async def resource_create(
    ctx: ResourceContext,
    path: object,
    content: bytes = b"",
    *,
    name: str = "",
    document_type: Literal["html", "dataset"] | None = None,
    max_bytes: int = _FILE_WRITE_LIMIT,
) -> ResourceMutation:
    """Create a new resource and return the provider's complete canonical URI."""

    limit = min(max(0, max_bytes), 100_000_000)
    if len(content) > limit:
        raise ValueError(f"File content exceeds {limit} bytes.")
    reference = parse_resource_uri(path, allow_empty=True)
    if document_type is not None and (reference.scheme != "document" or reference.locator):
        raise ValueError("document_type is only accepted when creating at document://.")
    clean_name = name.strip()
    if reference.scheme == "document":
        attachment_ids = _document_attachment_ids(reference)
        if attachment_ids is not None:
            document_id, attachment_id = attachment_ids
            if attachment_id is not None:
                raise ResourceUriError(
                    "Document attachment identifiers are assigned by the server; "
                    "create below document://<uuid>/attachments/."
                )
            if not clean_name:
                raise ResourceUriError(
                    "file_create requires name for a document attachment."
                )
            from app.memory import create_document_attachment_file_resource

            data = await create_document_attachment_file_resource(
                document_id,
                agent_id=ctx.agent_id,
                name=clean_name,
                content=content,
            )
            return ResourceMutation(
                uri=_uri(
                    "document",
                    f"{document_id}/attachments/{data['id']}",
                ),
                operation="create",
                state="created",
                size=_as_optional_int(data.get("size_bytes")),
            )
        if reference.locator:
            raise ResourceUriError(
                "file_create accepts document:// without an identifier; the server assigns it."
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("document:// resources contain UTF-8 text only.") from exc
        from app.memory import create_document_file_resource

        data = await create_document_file_resource(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            title=clean_name or "Document",
            content=text,
            document_type=document_type or "html",
        )
        return ResourceMutation(
            uri=_uri("document", str(data["id"])),
            operation="create",
            state="created",
            size=_as_optional_int(data.get("size")),
            revision=_as_optional_int(data.get("revision")),
        )
    if reference.scheme == "galaris":
        if reference.is_collection:
            if not clean_name:
                raise ResourceUriError(
                    "file_create requires name when path identifies a skill collection."
                )
            locator = "/".join(
                part for part in (reference.decoded_locator.rstrip("/"), clean_name) if part
            )
            reference = parse_resource_uri(f"galaris://{locator}")
        elif clean_name:
            raise ResourceUriError(
                "name is only accepted when path identifies a collection."
            )
        from .galaris_provider import galaris_resource_create

        return await galaris_resource_create(ctx, reference, content)
    if reference.scheme in {"memory", "http", "https"}:
        raise PermissionError(f"{reference.scheme}:// does not support file creation.")
    if reference.is_collection:
        if not clean_name:
            raise ResourceUriError(
                "file_create requires name when path identifies a collection."
            )
        locator = "/".join(
            part for part in (reference.decoded_locator.rstrip("/"), clean_name) if part
        )
        reference = parse_resource_uri(f"{reference.scheme}://{locator}")
    elif clean_name:
        raise ResourceUriError(
            "name is only accepted when path identifies a collection or document://."
        )

    if reference.scheme == "console":
        transport, destination_filename = await _console_reference(ctx, reference)
        try:
            await transport.file_info(destination_filename, include_sha256=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(str(reference))
        destination_transport = cast(FileTransport, transport)
        destination_target = ""
        service = ""
    else:
        destination_transport, service, _remote, _target = await _connected_transport(
            ctx, reference
        )
        destination = normalize_destination_reference(
            service,
            reference.decoded_locator,
            fallback_filename=_resource_name(reference, "resource.bin"),
        )
        if isinstance(destination_transport, ResourceMetadataTransport):
            try:
                await destination_transport.resource_info(
                    reference.decoded_locator,
                    include_sha256=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(str(reference))
        destination_filename = destination.filename
        destination_target = destination.target

    fd, temporary_name = tempfile.mkstemp(prefix="galaris_resource_create_")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        location = await destination_transport.upload_from(
            temporary,
            destination_filename,
            target=destination_target,
        )
    finally:
        temporary.unlink(missing_ok=True)
    if reference.scheme == "console":
        created_uri = _console_uri(location)
    else:
        created_uri = _uri(
            reference.scheme,
            _canonical_created_locator(
                reference.scheme,
                service,
                location,
                target=destination_target,
                filename=destination_filename,
            ),
        )
    return ResourceMutation(
        uri=created_uri,
        operation="create",
        state="created",
        size=len(content),
    )


async def resource_write(
    ctx: ResourceContext,
    uri: object,
    content: bytes,
    *,
    expected_revision: int | None = None,
) -> ResourceMutation:
    """Replace one existing complete resource from bounded bytes."""

    if len(content) > _FILE_WRITE_LIMIT:
        raise ValueError(f"File content exceeds {_FILE_WRITE_LIMIT} bytes.")
    reference = parse_resource_uri(uri)
    if reference.is_collection:
        raise ResourceUriError("file_write requires an exact destination file URI.")
    if reference.scheme == "document":
        if _document_attachment_ids(reference) is not None:
            raise PermissionError(
                "Document attachments are immutable; create a new attachment instead."
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResourceValidationError(
                "document:// stores UTF-8 text only; write binary content to console:// "
                "or a connected file provider."
            ) from exc
        from app.memory import write_document_resource_text

        data = await write_document_resource_text(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            content=text,
            expected_revision=expected_revision,
        )
        return ResourceMutation(
            uri=str(reference),
            operation="write",
            state=str(data.get("state") or "written"),
            size=_as_optional_int(data.get("size")),
            revision=_as_optional_int(data.get("revision")),
        )
    if reference.scheme == "memory":
        raise PermissionError(
            "memory:// resources are governed memories and cannot be replaced through "
            "generic file tools."
        )
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_write

        return await galaris_resource_write(
            ctx,
            reference,
            content,
            expected_revision=expected_revision,
        )
    if reference.scheme in {"http", "https"}:
        raise PermissionError(f"{reference.scheme}:// resources are read-only.")

    if reference.scheme == "console":
        transport, path = await _console_reference(ctx, reference)
        info = await transport.file_info(path, include_sha256=False)
        if info.is_dir:
            raise IsADirectoryError(str(reference))
        destination_transport = cast(FileTransport, transport)
        destination_filename = path
        destination_target = ""
        service = ""
    else:
        destination_transport, service, _remote, _target = await _connected_transport(
            ctx,
            reference,
        )
        destination = normalize_destination_reference(
            service,
            reference.decoded_locator,
            fallback_filename=_resource_name(reference, "resource.bin"),
        )
        if isinstance(destination_transport, MessengerFileTransport):
            raise NotImplementedError(
                f"{reference.scheme}:// attachments are immutable; use file_create to "
                "create a new attachment."
            )
        if not isinstance(destination_transport, ResourceMetadataTransport):
            raise NotImplementedError(
                f"{reference.scheme}:// cannot verify that a file exists before replacing it."
            )
        info = await destination_transport.resource_info(
            reference.decoded_locator,
            include_sha256=False,
        )
        if info.is_dir:
            raise IsADirectoryError(str(reference))
        destination_filename = destination.filename
        destination_target = destination.target

    fd, temporary_name = tempfile.mkstemp(prefix="galaris_resource_write_binary_")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        location = await destination_transport.upload_from(
            temporary,
            destination_filename,
            target=destination_target,
        )
    finally:
        temporary.unlink(missing_ok=True)

    if reference.scheme == "console":
        created_uri = _console_uri(location)
    else:
        locator = _canonical_created_locator(
            reference.scheme,
            service,
            location,
            target=destination_target,
            filename=destination_filename,
        )
        created_uri = _uri(reference.scheme, locator)
    return ResourceMutation(
        uri=created_uri,
        operation="write",
        state="written",
        size=len(content),
    )


async def resource_append(
    ctx: ResourceContext,
    uri: object,
    content: str,
    *,
    expected_revision: int | None = None,
) -> ResourceMutation:
    if len(content) > _TEXT_WRITE_LIMIT:
        raise ResourceValidationError(f"Text content exceeds {_TEXT_WRITE_LIMIT} characters.")
    reference = parse_resource_uri(uri)
    if reference.scheme == "console":
        transport, path = await _console_reference(ctx, reference)
        result = await transport.file_append_text(path, content)
        return ResourceMutation(
            uri=_console_uri(result.path),
            operation="append",
            state=result.state,
            size=result.size,
        )
    if reference.scheme == "document":
        if _document_attachment_ids(reference) is not None:
            raise PermissionError(
                "Document attachments are immutable; create a new attachment instead."
            )
        if expected_revision is None:
            raise ResourceValidationError("expected_revision is required for document appends; call file_read first.")
        from app.memory import append_document_resource_text

        data = await append_document_resource_text(
            UUID(reference.locator),
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            content=content,
            expected_revision=expected_revision,
        )
        return ResourceMutation(
            uri=str(reference),
            operation="append",
            state=str(data["state"]),
            size=_as_int(data["size_bytes"]),
            revision=_as_int(data["revision"]),
        )
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_append

        return await galaris_resource_append(ctx, reference, content)
    raise NotImplementedError(f"{reference.scheme}:// does not support text append.")


async def _read_complete_text(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> str:
    """Read a complete bounded text resource for an explicit cross-provider copy."""

    text, _revision = await _read_complete_text_and_revision(ctx, reference)
    return text


async def _read_complete_text_and_revision(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> tuple[str, int | None]:
    """Read complete bounded text and retain its first observed revision."""

    chunks: list[str] = []
    offset = 0
    revision: int | None = None
    while True:
        part = await resource_read(
            ctx,
            reference,
            offset=offset,
            max_chars=2_000_000 if reference.scheme in {"document", "memory"} else _TEXT_READ_LIMIT,
        )
        if part.encoding != "utf-8":
            raise ResourceValidationError("This operation supports UTF-8 text resources only.")
        if revision is None:
            revision = part.revision
        elif part.revision is not None and part.revision != revision:
            raise ResourceRevisionConflict("The resource changed while it was being read; read it again before retrying the edit.")
        chunks.append(part.content)
        if part.next_offset is None:
            return "".join(chunks), revision
        offset = part.next_offset
        if offset > _TEXT_WRITE_LIMIT:
            raise ValueError(
                "Text resource is too large for an implicit document-to-file copy."
            )


async def _read_complete_bytes(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> bytes:
    """Read one bounded resource as bytes for a generic native-provider copy."""

    attachment_ids = _document_attachment_ids(reference)
    if attachment_ids is not None:
        document_id, attachment_id = attachment_ids
        if attachment_id is None:
            raise IsADirectoryError(str(reference))
        from app.memory import read_document_attachment_file_resource

        _metadata, content = await read_document_attachment_file_resource(
            document_id,
            attachment_id,
            agent_id=ctx.agent_id,
        )
        if len(content) > _FILE_WRITE_LIMIT:
            raise ValueError(
                f"Resource exceeds the {_FILE_WRITE_LIMIT}-byte generic copy limit."
            )
        return content
    if reference.scheme == "galaris" and reference.decoded_locator.startswith("skill/"):
        from .galaris_provider import galaris_skill_file_bytes

        content = await galaris_skill_file_bytes(ctx, reference)
        if len(content) > _FILE_WRITE_LIMIT:
            raise ValueError(
                f"Resource exceeds the {_FILE_WRITE_LIMIT}-byte generic copy limit."
            )
        return content
    chunks: list[bytes] = []
    offset = 0
    while True:
        part = await resource_read(
            ctx,
            reference,
            offset=offset,
            max_chars=_TEXT_READ_LIMIT,
        )
        if part.encoding == "base64":
            if offset:
                raise RuntimeError("Binary resource pagination is not supported.")
            chunks.append(base64.b64decode(part.content, validate=True))
        else:
            chunks.append(part.content.encode("utf-8"))
        total = sum(len(chunk) for chunk in chunks)
        if total > _FILE_WRITE_LIMIT:
            raise ValueError(
                f"Resource exceeds the {_FILE_WRITE_LIMIT}-byte generic copy limit."
            )
        if part.next_offset is None:
            return b"".join(chunks)
        offset = part.next_offset


async def _materialize_complete_bytes(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> bytes:
    """Materialize one bounded copy source without the small-binary read limit."""

    fd, temporary_name = tempfile.mkstemp(prefix="galaris_resource_copy_")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        await materialize_resource(
            ctx,
            reference,
            temporary,
            max_bytes=_FILE_WRITE_LIMIT,
        )
        return temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)


async def resource_edit(
    ctx: ResourceContext,
    uri: object,
    *,
    start_line: int,
    end_line: int,
    content: str,
    expected_revision: int | None = None,
) -> ResourceMutation:
    """Replace a 1-based inclusive line range in one UTF-8 text resource."""

    if start_line < 1 or end_line < start_line:
        raise ResourceValidationError("start_line and end_line must define a 1-based inclusive range.")
    if len(content) > _TEXT_WRITE_LIMIT:
        raise ResourceValidationError(f"Text content exceeds {_TEXT_WRITE_LIMIT} characters.")
    reference = parse_resource_uri(uri)
    if reference.scheme == "document" and expected_revision is None:
        raise ResourceValidationError("Document edits require expected_revision from file_read.")
    text, observed_revision = await _read_complete_text_and_revision(ctx, reference)
    descriptor = await resource_info(ctx, reference) if reference.scheme == "document" else None
    if descriptor is not None and descriptor.media_type == "text/html":
        from core.util import html_blocks, normalize_html
        lines = html_blocks(text)
        content = normalize_html(content, profile="document")
    else:
        lines = text.splitlines(keepends=True)
    if end_line > len(lines):
        raise ResourceValidationError(
            f"Line range {start_line}-{end_line} exceeds the resource's {len(lines)} lines/blocks; "
            "use the complete blocks returned by file_read for HTML documents."
        )
    if (
        reference.scheme == "document"
        and expected_revision is not None
        and observed_revision != expected_revision
    ):
        raise ResourceRevisionConflict(
            f"Document revision conflict: expected {expected_revision}, "
            f"current revision is {observed_revision}; call file_read before retrying."
        )
    replacement = content
    replaced_block = "".join(lines[start_line - 1 : end_line])
    if replacement and replaced_block.endswith(("\n", "\r")) and not replacement.endswith(
        ("\n", "\r")
    ):
        replacement += "\r\n" if replaced_block.endswith("\r\n") else "\n"
    updated = "".join(lines[: start_line - 1]) + replacement + "".join(lines[end_line:])
    mutation = await resource_write(
        ctx,
        reference,
        updated.encode("utf-8"),
        expected_revision=(
            expected_revision if expected_revision is not None else observed_revision
        ),
    )
    return mutation.model_copy(
        update={"operation": "edit", "state": "edited"}
    )


async def resource_copy(
    ctx: ResourceContext,
    source: object,
    destination: object,
    *,
    overwrite: bool = False,
) -> ResourceTransfer:
    source_ref = parse_resource_uri(source)
    destination_ref = parse_resource_uri(destination, allow_empty=True)
    destination_ref = await _resolve_transfer_destination(
        ctx,
        source_ref,
        destination_ref,
    )
    destination_attachment_ids = _document_attachment_ids(destination_ref)
    if destination_attachment_ids is not None:
        _document_id, attachment_id = destination_attachment_ids
        if attachment_id is not None:
            raise PermissionError(
                "Document attachments are immutable; copy into the attachments collection."
            )
        data = await _materialize_complete_bytes(ctx, source_ref)
        source_name = (await resource_info(ctx, source_ref)).name
        mutation = await resource_create(
            ctx,
            destination_ref,
            data,
            name=source_name,
        )
        return ResourceTransfer(
            source_uri=str(source_ref),
            uri=mutation.uri,
            size=mutation.size or len(data),
        )
    if destination_ref.scheme == "galaris":
        data = await _read_complete_bytes(ctx, source_ref)
        target = destination_ref
        if target.is_collection:
            source_name = PurePosixPath(
                (await resource_info(ctx, source_ref)).name
            ).name
            target = parse_resource_uri(
                f"galaris://{target.decoded_locator.rstrip('/')}/{source_name}"
            )
        mutation = (
            await resource_write(ctx, target, data)
            if overwrite
            else await resource_create(ctx, target, data)
        )
        return ResourceTransfer(
            source_uri=str(source_ref),
            uri=mutation.uri,
            size=mutation.size or len(data),
        )
    if destination_ref.scheme == "document":
        from core.util import convert_to_html
        source_descriptor = await resource_info(ctx, source_ref)
        target_descriptor = None if destination_ref.is_collection else await resource_info(ctx, destination_ref)
        dataset = (target_descriptor or source_descriptor).media_type == "application/json"
        text = await _read_complete_text(ctx, source_ref)
        if not dataset:
            text = convert_to_html(text, source_descriptor.media_type, profile="document")
        if destination_ref.is_collection:
            from app.memory import create_document_file_resource

            title = (await resource_info(ctx, source_ref)).name
            data = await create_document_file_resource(
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                title=title,
                content=text,
                document_type="dataset" if dataset else "html",
            )
            return ResourceTransfer(
                source_uri=str(source_ref),
                uri=_uri("document", str(data["id"])),
                size=_as_int(data["size"]),
            )
        mutation = await resource_write_text(
            ctx,
            destination_ref,
            text,
            overwrite=overwrite,
        )
        return ResourceTransfer(
            source_uri=str(source_ref), uri=mutation.uri, size=mutation.size or 0
        )
    source_attachment_ids = _document_attachment_ids(source_ref)
    if source_attachment_ids is not None:
        _document_id, attachment_id = source_attachment_ids
        if attachment_id is None:
            raise IsADirectoryError(str(source_ref))
        data = await _read_complete_bytes(ctx, source_ref)
        target = destination_ref
        if target.is_collection:
            source_name = (await resource_info(ctx, source_ref)).name
            target = parse_resource_uri(
                f"{target.scheme}://{target.decoded_locator}{source_name}"
            )
        mutation = (
            await resource_write(ctx, target, data)
            if overwrite
            else await resource_create(ctx, target, data)
        )
        return ResourceTransfer(
            source_uri=str(source_ref),
            uri=mutation.uri,
            size=mutation.size or len(data),
        )
    if source_ref.scheme == "galaris" and source_ref.decoded_locator.startswith("skill/"):
        data = await _read_complete_bytes(ctx, source_ref)
        target = destination_ref
        if target.is_collection:
            source_name = PurePosixPath(
                (await resource_info(ctx, source_ref)).name
            ).name
            target = parse_resource_uri(
                f"{target.scheme}://{target.decoded_locator.rstrip('/')}/{source_name}"
            )
        mutation = (
            await resource_write(ctx, target, data)
            if overwrite
            else await resource_create(ctx, target, data)
        )
        return ResourceTransfer(
            source_uri=str(source_ref),
            uri=mutation.uri,
            size=mutation.size or len(data),
        )
    if source_ref.scheme in {"memory", "document", "galaris"}:
        data = await _read_complete_bytes(ctx, source_ref)
        name = (await resource_info(ctx, source_ref)).name
        target = destination_ref
        if target.is_collection:
            target = parse_resource_uri(
                f"{target.scheme}://{target.decoded_locator}{name}", allow_empty=False
            )
        mutation = (
            await resource_write(ctx, target, data)
            if overwrite
            else await resource_create(ctx, target, data)
        )
        return ResourceTransfer(
            source_uri=str(source_ref), uri=mutation.uri, size=mutation.size or 0
        )
    if destination_ref.scheme == "memory":
        raise NotImplementedError(
            "memory:// resources are durable memories and require Memory domain tools."
        )
    if destination_ref.scheme in {"http", "https"}:
        raise PermissionError(f"{destination_ref.scheme}:// resources are read-only.")
    if source_ref.scheme == "console":
        source_transport, source_path = await _console_reference(ctx, source_ref)
        source_file_transport = cast(FileTransport, source_transport)
        source_remote, source_target = source_path, ""
        source_uri = _console_uri(source_path)
    else:
        source_file_transport, _source_service, source_remote, source_target = (
            await _connected_transport(ctx, source_ref)
        )
        source_uri = str(source_ref)
    source_name = reference_filename(source_remote, _resource_name(source_ref))
    if destination_ref.is_collection:
        source_descriptor = await resource_info(ctx, source_ref)
        source_name = reference_filename(source_descriptor.name, source_name)
    if destination_ref.scheme == "console":
        destination_transport, destination_path = await _console_reference(ctx, destination_ref)
        if destination_ref.is_collection:
            collection_path = "" if destination_path == "." else destination_path.rstrip("/")
            destination_path = "/".join(
                part for part in (collection_path, source_name) if part
            )
        if not overwrite:
            try:
                await destination_transport.file_info(
                    destination_path, include_sha256=False
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(str(destination_ref))
        location, size = await transfer(
            source_file_transport,
            source_remote,
            cast(FileTransport, destination_transport),
            source_target=source_target,
            filename=destination_path,
        )
        return ResourceTransfer(
            source_uri=source_uri,
            uri=_console_uri(location),
            size=size,
        )
    destination_transport, destination_service = (
        await _connected_destination_transport(
            ctx,
            destination_ref,
            fallback_locator=f"placeholder/{source_name}",
        )
    )
    destination_spec = normalize_destination_reference(
        destination_service,
        destination_ref.decoded_locator,
        fallback_filename=source_name,
    )
    if destination_ref.is_collection and destination_ref.decoded_locator:
        destination_spec = normalize_destination_reference(
            destination_service,
            f"{destination_ref.decoded_locator.rstrip('/')}/{source_name}",
            fallback_filename=source_name,
        )
    if not overwrite:
        if isinstance(destination_transport, ResourceMetadataTransport):
            candidate = "/".join(
                part
                for part in (destination_spec.target, destination_spec.filename)
                if part
            )
            try:
                await destination_transport.resource_info(
                    candidate, include_sha256=False
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(str(destination_ref))
    location, size = await transfer(
        source_file_transport,
        source_remote,
        destination_transport,
        source_target=source_target,
        dest_target=destination_spec.target,
        filename=destination_spec.filename,
    )
    locator = _canonical_created_locator(
        destination_ref.scheme,
        destination_service,
        location,
        target=destination_spec.target,
        filename=destination_spec.filename,
    )
    return ResourceTransfer(
        source_uri=source_uri,
        uri=_uri(destination_ref.scheme, locator),
        size=size,
    )


async def resource_delete(ctx: ResourceContext, uri: object) -> ResourceMutation:
    reference = parse_resource_uri(uri)
    if reference.scheme == "console":
        transport, path = await _console_reference(ctx, reference)
        result = await transport.file_delete(path)
        return ResourceMutation(
            uri=_console_uri(result.path),
            operation="delete",
            state=result.state,
            size=result.size,
        )
    if reference.scheme == "galaris":
        if reference.decoded_locator.startswith("skill/"):
            from .galaris_provider import galaris_resource_delete

            return await galaris_resource_delete(ctx, reference)
        raise PermissionError(
            "galaris:// resources are read-only business snapshots. Deleting this URI would "
            "not delete its Task, Process, Goal, cycle, or conversation; use the owning "
            "domain tool when that operation exists."
        )
    attachment_ids = _document_attachment_ids(reference)
    if attachment_ids is not None:
        document_id, attachment_id = attachment_ids
        if attachment_id is None:
            raise PermissionError("A document attachment collection cannot be deleted.")
        from app.memory import delete_document_attachment_file_resource

        await delete_document_attachment_file_resource(
            document_id,
            attachment_id,
            agent_id=ctx.agent_id,
        )
        return ResourceMutation(
            uri=str(reference),
            operation="delete",
            state="deleted",
        )
    if reference.scheme in {"memory", "document"}:
        raise PermissionError(
            f"{reference.scheme}:// resources cannot be deleted through generic file tools; "
            "use the owning Memory or document operation."
        )
    if reference.scheme in {"http", "https"}:
        raise PermissionError(f"{reference.scheme}:// resources are read-only.")
    transport, _service, _remote, _target = await _connected_transport(ctx, reference)
    if isinstance(transport, MessengerFileTransport):
        raise PermissionError(
            f"{reference.scheme}:// Messenger resources cannot be deleted through "
            "generic file tools."
        )
    if not isinstance(transport, ResourceDeletionTransport):
        raise NotImplementedError(f"{reference.scheme}:// does not support deletion.")
    result = await transport.resource_delete(reference.decoded_locator)
    return ResourceMutation(
        uri=str(reference), operation="delete", state=result.state, size=result.size
    )


async def resource_move(
    ctx: ResourceContext,
    source: object,
    destination: object,
    *,
    overwrite: bool = False,
) -> ResourceTransfer:
    source_ref = parse_resource_uri(source)
    destination_ref = parse_resource_uri(destination, allow_empty=True)
    if source_ref.scheme == "galaris" or destination_ref.scheme == "galaris":
        if (
            source_ref.scheme == "galaris"
            and destination_ref.scheme == "galaris"
            and source_ref.decoded_locator.startswith("skill/")
            and destination_ref.decoded_locator.startswith("skill/")
        ):
            from .galaris_provider import galaris_resource_move

            destination_ref = await _resolve_transfer_destination(
                ctx,
                source_ref,
                destination_ref,
            )
            mutation = await galaris_resource_move(
                ctx,
                source_ref,
                destination_ref,
                overwrite=overwrite,
            )
            return ResourceTransfer(
                source_uri=str(source_ref),
                uri=mutation.uri,
                size=mutation.size or 0,
                moved=True,
            )
        raise PermissionError(
            "galaris:// resources cannot be moved; copy a readable resource to another scheme."
        )
    if source_ref.scheme in {"memory", "document", "http", "https"}:
        raise PermissionError(
            f"{source_ref.scheme}:// resources cannot be moved because generic file tools "
            "cannot delete the source; use file_copy instead."
        )
    destination_ref = await _resolve_transfer_destination(
        ctx,
        source_ref,
        destination_ref,
    )
    if source_ref.scheme == destination_ref.scheme == "console":
        transport, source_path = await _console_reference(ctx, source_ref)
        _same, destination_path = await _console_reference(ctx, destination_ref)
        if destination_ref.is_collection:
            collection_path = (
                "" if destination_path == "." else destination_path.rstrip("/")
            )
            destination_path = "/".join(
                part
                for part in (collection_path, PurePosixPath(source_path).name)
                if part
            )
        if not overwrite:
            try:
                await transport.file_info(destination_path, include_sha256=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(str(destination_ref))
        result = await transport.file_move(source_path, destination_path)
        return ResourceTransfer(
            source_uri=_console_uri(source_path),
            uri=_console_uri(result.path),
            size=result.size,
            moved=True,
        )
    if source_ref.scheme == destination_ref.scheme and source_ref.scheme not in {
        "memory",
        "document",
    }:
        transport, _service, _remote, _target = await _connected_transport(ctx, source_ref)
        if isinstance(transport, ResourceRelocationTransport):
            destination_locator = destination_ref.decoded_locator
            if destination_ref.is_collection:
                destination_locator = "/".join(
                    part
                    for part in (
                        destination_locator.rstrip("/"),
                        _resource_name(source_ref),
                    )
                    if part
                )
            result = await transport.resource_move(
                source_ref.decoded_locator,
                destination_locator,
                overwrite=overwrite,
            )
            return ResourceTransfer(
                source_uri=str(source_ref),
                uri=_uri(destination_ref.scheme, result.path),
                size=result.size,
                moved=True,
            )
    if source_ref.scheme != "console":
        source_transport, _service, _remote, _target = await _connected_transport(
            ctx, source_ref
        )
        if isinstance(source_transport, MessengerFileTransport) or not isinstance(
            source_transport, ResourceDeletionTransport
        ):
            raise PermissionError(
                f"{source_ref.scheme}:// resources cannot be moved because the source "
                "provider does not support deletion; use file_copy instead."
            )
    copied = await resource_copy(ctx, source_ref, destination_ref, overwrite=overwrite)
    try:
        await resource_delete(ctx, source_ref)
    except Exception as exc:
        raise RuntimeError(
            f"Resource copied to {copied.uri}, but source deletion failed; "
            "the operation is a copy, not a completed move."
        ) from exc
    copied.moved = True
    return copied


def _name_matches(descriptor: ResourceDescriptor, query: str) -> bool:
    folded = query.casefold()
    return folded in descriptor.name.casefold() or folded in descriptor.uri.casefold()


async def resource_search(
    ctx: ResourceContext,
    uri: object,
    query: str,
    *,
    mode: Literal["name", "text", "semantic"] = "name",
    recursive: bool = True,
    max_results: int | None = None,
    cursor: str | None = None,
) -> ResourceSearchResult:
    reference = parse_resource_uri(uri, allow_empty=True)
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("A non-empty file search query is required.")
    limit = 50 if max_results is None else max(1, min(max_results, 500))
    offset = max(0, int(cursor or "0"))
    if reference.scheme == "galaris":
        from .galaris_provider import galaris_resource_search

        return await galaris_resource_search(
            ctx,
            reference,
            normalized_query,
            mode=mode,
            max_results=limit,
            cursor=cursor,
        )
    if (
        reference.scheme in {"memory", "document"}
        and _document_attachment_ids(reference) is None
    ):
        from app.memory import search_file_resources

        data = await search_file_resources(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            expected_kind=cast(Literal["memory", "document"], reference.scheme),
            query=normalized_query,
            mode=mode,
            limit=(max_results if reference.scheme == "memory" else limit),
            offset=offset,
        )
        hits = [
            ResourceSearchHit(
                resource=ResourceDescriptor(
                    uri=str(item["uri"]),
                    name=str(item["filename"] or item["title"]),
                    media_type=str(item["media_type"]),
                    size=_as_int(item["size"]),
                    modified_at=cast(str | None, item["updated_at"]),
                    revision=_as_int(item["revision"]),
                    checksum=str(item["checksum"]),
                    capabilities=(
                        list(_DOCUMENT_CAPABILITIES)
                        if item["node_kind"] == "document" and bool(item["can_write"])
                        else list(_MEMORY_CAPABILITIES)
                    ),
                    metadata=cast(dict[str, Any], item["metadata"]),
                ),
                score=_as_float(item["score"]),
                excerpt=str(item["excerpt"]),
                retrieval_sources=cast(list[str], item.get("retrieval_sources", [])),
                source_refs=cast(list[str], item.get("source_refs", [])),
                passages=cast(list[dict[str, Any]], item.get("passages", [])),
            )
            for item in cast(list[dict[str, object]], data["hits"])
        ]
        return ResourceSearchResult(
            uri=str(reference),
            query=normalized_query,
            mode=mode,
            hits=hits,
            retrieval_mode=cast(Literal["lexical", "hybrid"] | None, data.get("retrieval_mode")),
            degraded=bool(data.get("degraded", False)),
            degradation_reason=cast(str | None, data.get("degradation_reason")),
            ranking_version=cast(str | None, data.get("ranking_version")),
            relevance_status=cast(Literal["matched", "no_sufficient_evidence"] | None, data.get("relevance_status")),
            candidate_window_exhausted=bool(data.get("candidate_window_exhausted", False)),
            index_coverage=cast(dict[str, Any] | None, data.get("index_coverage")),
            truncated=bool(data["has_more"]),
            next_cursor=(
                str(data["next_offset"]) if data["next_offset"] is not None else None
            ),
        )
    if mode == "semantic":
        raise NotImplementedError(
            f"{reference.scheme}:// does not expose semantic file search."
        )
    listing = await resource_list(
        ctx,
        reference,
        recursive=recursive,
        max_entries=_SEARCH_SCAN_LIMIT,
    )
    hits: list[ResourceSearchHit] = []
    for descriptor in listing.entries:
        excerpt = ""
        matched = _name_matches(descriptor, normalized_query)
        if mode == "text" and not descriptor.is_collection:
            try:
                text = await resource_read(
                    ctx, descriptor.uri, max_chars=_TEXT_READ_LIMIT
                )
            except (UnicodeDecodeError, ValueError, RuntimeError, NotImplementedError):
                continue
            if text.encoding != "utf-8":
                continue
            folded = text.content.casefold()
            position = folded.find(normalized_query.casefold())
            matched = position >= 0
            if matched:
                start = max(0, position - 120)
                excerpt = text.content[start : position + len(normalized_query) + 240]
        if matched:
            hits.append(ResourceSearchHit(resource=descriptor, excerpt=excerpt))
    selected = hits[offset : offset + limit]
    has_more = offset + limit < len(hits) or listing.truncated
    return ResourceSearchResult(
        uri=listing.uri,
        query=normalized_query,
        mode=mode,
        hits=selected,
        truncated=has_more,
        next_cursor=str(offset + limit) if has_more else None,
    )


__all__ = [
    "_json_model",
    "list_schemes",
    "resource_append",
    "resource_copy",
    "resource_create",
    "resource_delete",
    "resource_info",
    "resource_list",
    "resource_move",
    "resource_read",
    "resource_edit",
    "resource_search",
    "resource_write",
]
