"""Native data:// provider; File Sharing retains the generic file surface."""

from bisect import bisect_right
from itertools import accumulate
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select

from core.database import get_db
from core.storage import registered_file_names
from core.util import complete_io
from app.file_share import (MaterializedResource, ResourceContext, ResourceDescriptor, ResourceUri, parse_resource_uri,
    ResourceListing, ResourceMutation, ResourceRead, ResourceSchemeDescription, ResourceSearchHit, ResourceSearchResult)

from . import service
from .access import accessible_clause
from .models import Dataset, DatasetAlias, DatasetAttachment


class DatasetResourceRead(ResourceRead):
    """Exact character page with one-based edit coordinates; no content decoration."""

    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    total_lines: int = Field(ge=1)
    start_line_complete: bool = False
    end_line_complete: bool = False


def root_id(uri: ResourceUri) -> UUID:
    if len(uri.segments) != 1 or uri.is_collection:
        raise ValueError("This operation requires data://<uuid>")
    return UUID(uri.segments[0])


async def resolve_alias(ctx: ResourceContext, reference: ResourceUri) -> ResourceUri:
    if reference.scheme != "document" or not reference.segments or reference.segments[0] == "folders":
        return reference
    try:
        db = get_db()
    except RuntimeError:
        # Standalone provider operations can run without a managed DB context.
        # Without evidence this remains a Document, never an inferred Dataset.
        return reference
    alias = await db.scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == UUID(reference.segments[0])))
    if alias is None:
        from app.document import legacy_dataset_exists, legacy_dataset_access
        identity = UUID(reference.segments[0])
        if not await legacy_dataset_exists(identity) or not await legacy_dataset_access(identity, ctx.agent_id):
            return reference
        from .migration import adopt_legacy
        await adopt_legacy(identity)
        alias = await get_db().scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == identity))
        assert alias is not None
    await service.record(alias.dataset_id, ctx.agent_id)
    suffix = "/".join(reference.segments[1:])
    return parse_resource_uri(f"data://{alias.dataset_id}" + ("/" + suffix + ("/" if reference.is_collection else "") if suffix else ""))


class DatasetProvider:
    def description(self) -> ResourceSchemeDescription:
        return ResourceSchemeDescription(scheme="data", label="Galaris Datasets", example="data://<uuid>", native=True,
            capabilities=["create", "info", "list", "search", "read", "write", "append", "edit", "copy", "delete", "rename"])

    async def info(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceDescriptor:
        if not uri.locator:
            return ResourceDescriptor(uri="data://", name="Datasets", is_collection=True,
                media_type="inode/directory", capabilities=["create", "info", "list", "search"])
        dataset = await service.record(UUID(uri.segments[0]), ctx.management_scope or ctx.agent_id)
        state = await service.describe(dataset, ctx.management_scope or ctx.agent_id, content=False)
        if len(uri.segments) > 1:
            if len(uri.segments) == 2:
                return ResourceDescriptor(uri=f"data://{dataset.id}/attachments/", name="attachments", is_collection=True,
                    media_type="inode/directory", capabilities=["info", "list", "search", *(["create"] if state["can_write"] else [])])
            attachment = await self._attachment(uri, ctx)
            names = await registered_file_names([attachment.file_id]) if attachment.file_id else {}
            name = names.get(attachment.file_id, attachment.name) if attachment.file_id else attachment.name
            rename_metadata = {"rename_uri": str(uri), "can_rename": bool(attachment.file_id and state["can_write"])}
            if not attachment.uri.startswith(("file://", f"document://{dataset.id}/attachments/")):
                from app.file_share import resource_info
                original = await resource_info(ctx, attachment.uri)
                return original.model_copy(update={"name": name, "metadata": {**original.metadata, **rename_metadata}})
            return ResourceDescriptor(uri=attachment.uri, name=name, media_type=attachment.media_type,
                size=attachment.size_bytes, checksum=attachment.sha256, capabilities=["info", "read", "copy"], metadata=rename_metadata)
        return ResourceDescriptor(uri=f"data://{dataset.id}", name=dataset.title, media_type="application/json",
            size=state["size"], revision=dataset.revision, lock_version=dataset.lock_version, checksum=state["checksum"],
            capabilities=["info", "read", "copy", *(["write", "append", "edit", "rename"] if state["can_write"] else []), *(["delete"] if state["can_delete"] else [])],
            metadata={"resource_type": "dataset", "document_type": "dataset",
                "lock_version": dataset.lock_version, "can_manage": state["can_manage"], "can_write": state["can_write"]})

    async def rename(self, ctx: ResourceContext, uri: ResourceUri, name: str,
                     *, expected_lock_version: int) -> ResourceMutation:
        dataset = await service.metadata(root_id(uri), ctx.management_scope or ctx.agent_id,
            expected_lock_version=expected_lock_version, values={"title": name})
        return ResourceMutation(uri=f"data://{dataset.id}", source_uri=str(uri), operation="rename",
            state="renamed", name=dataset.title, size=len(dataset.content.encode("utf-8")),
            revision=dataset.revision, lock_version=dataset.lock_version)

    async def _attachment(self, uri: ResourceUri, ctx: ResourceContext) -> DatasetAttachment:
        await service.record(UUID(uri.segments[0]), ctx.management_scope or ctx.agent_id)
        attachment = await get_db().scalar(select(DatasetAttachment).where(DatasetAttachment.dataset_id == UUID(uri.segments[0]), DatasetAttachment.id == UUID(uri.segments[2])))
        if attachment is None:
            raise service.DatasetNotFoundError("Dataset attachment not found")
        return attachment

    async def list(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceListing:
        limit = min(500, max(1, int(options.get("max_entries", 50))))
        cursor = options.get("cursor")
        query = select(Dataset).where(accessible_clause(ctx.management_scope or ctx.agent_id)).order_by(Dataset.id)
        if uri.locator:
            await service.record(UUID(uri.segments[0]), ctx.management_scope or ctx.agent_id)
            if len(uri.segments) != 2:
                raise NotADirectoryError(str(uri))
            statement = select(DatasetAttachment).where(DatasetAttachment.dataset_id == UUID(uri.segments[0]))
            if cursor:
                statement = statement.where(DatasetAttachment.id > UUID(cursor))
            attachments = list(await get_db().scalars(statement.order_by(DatasetAttachment.id).limit(limit + 1)))
            entries: list[ResourceDescriptor] = []
            for item in attachments[:limit]:
                try:
                    descriptor = await self.info(ctx, parse_resource_uri(f"data://{item.dataset_id}/attachments/{item.id}"))
                except (FileNotFoundError, PermissionError):
                    continue
                entries.append(descriptor)
            return ResourceListing(uri=str(uri), entries=entries, truncated=len(attachments) > limit,
                next_cursor=str(attachments[limit - 1].id) if len(attachments) > limit else None)
        if cursor:
            query = query.where(Dataset.id > UUID(cursor))
        rows = list(await get_db().scalars(query.limit(limit + 1)))
        entries = [await self.info(ctx, parse_resource_uri(f"data://{item.id}")) for item in rows[:limit]]
        return ResourceListing(uri="data://", entries=entries, truncated=len(rows) > limit,
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None)

    async def read(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceRead:
        if len(uri.segments) > 1:
            from app.file_share import resource_read
            attachment = await self._attachment(uri, ctx)
            if attachment.uri.startswith(f"document://{attachment.dataset_id}/attachments/"):
                from app.document import read_document_attachment_file_resource
                _, raw = await read_document_attachment_file_resource(attachment.dataset_id, attachment.id, agent_id=ctx.agent_id)
                text = raw.decode("utf-8")
                start = max(0, int(options.get("offset", 0)))
                end = min(len(text), start + min(service.MAX_BYTES, int(options.get("max_chars", 20000))))
                return ResourceRead(uri=str(uri), content=text[start:end], media_type=attachment.media_type,
                    start=start, end=end, total=len(text), next_offset=end if end < len(text) else None)
            return await resource_read(ctx, attachment.uri,
                offset=options.get("offset", 0), max_chars=options.get("max_chars", 20000))
        dataset = await service.record(root_id(uri), ctx.management_scope or ctx.agent_id)
        start, limit = min(len(dataset.content), max(0, int(options.get("offset", 0)))), min(service.MAX_BYTES, max(1, int(options.get("max_chars", 20000))))
        end = min(len(dataset.content), start + limit)
        # Match edit()'s splitlines semantics, including CRLF and Unicode separators.
        line_ends = list(accumulate(len(line) for line in dataset.content.splitlines(keepends=True)))
        first = bisect_right(line_ends, start)
        last = bisect_right(line_ends, end - 1)
        has_content = start < end
        return DatasetResourceRead(uri=f"data://{dataset.id}", content=dataset.content[start:end], media_type="application/json",
            start=start, end=end, total=len(dataset.content), next_offset=end if end < len(dataset.content) else None, revision=dataset.revision,
            start_line=first + 1 if has_content else None, end_line=last + 1 if has_content else None,
            total_lines=len(line_ends),
            start_line_complete=has_content and start == (line_ends[first - 1] if first else 0),
            end_line_complete=has_content and end == line_ends[last])

    async def create(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation:
        if uri.locator:
            if len(uri.segments) != 2:
                raise ValueError("Create a Dataset at data:// or a file in its attachments collection")
            from .attachments import add_bytes
            attachment = await add_bytes(UUID(uri.segments[0]), ctx.agent_id, content, name=str(options.get("name") or "file"))
            return ResourceMutation(uri=attachment.uri, operation="create", state="created", size=attachment.size_bytes)
        dataset = await service.create(ctx.agent_id, title=str(options.get("name") or "Dataset"), content=content.decode("utf-8"))
        await get_db().commit()
        return ResourceMutation(uri=f"data://{dataset.id}", operation="create", state="created", revision=1, size=len(content))

    async def write(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation:
        dataset = await service.replace(root_id(uri), ctx.agent_id, content=content.decode("utf-8"), expected_revision=options.get("expected_revision"))
        await get_db().commit()
        return ResourceMutation(uri=f"data://{dataset.id}", operation="write", state="written", revision=dataset.revision, size=len(content))

    async def append(self, ctx: ResourceContext, uri: ResourceUri, content: str, **options: Any) -> ResourceMutation:
        dataset = await service.record(root_id(uri), ctx.agent_id)
        result = await self.write(ctx, uri, (dataset.content + content).encode(), **options)
        return result.model_copy(update={"operation": "append"})

    async def edit(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation:
        dataset = await service.record(root_id(uri), ctx.agent_id)
        lines = dataset.content.splitlines(keepends=True)
        first, last = int(options["start_line"]), int(options["end_line"])
        if first < 1 or last < first or last > len(lines):
            raise ValueError("Dataset edit range is outside the current content")
        replacement = str(options["content"])
        original = "".join(lines[first - 1:last])
        if original.endswith(("\n", "\r")) and replacement and not replacement.endswith(("\n", "\r")):
            replacement += "\r\n" if original.endswith("\r\n") else "\r" if original.endswith("\r") else "\n"
        content = "".join(lines[:first - 1]) + replacement + "".join(lines[last:])
        result = await self.write(ctx, uri, content.encode(), **{key: value for key, value in options.items() if key != "content"})
        return result.model_copy(update={"operation": "edit"})

    async def delete(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation:
        dataset = await service.record(UUID(uri.segments[0]), ctx.agent_id, manage=True, lock=True)
        if len(uri.segments) == 3:
            attachment = await self._attachment(uri, ctx)
            attachment.soft_delete()
            from app.memory import forget_resource_memories
            await forget_resource_memories([str(uri)])
        elif len(uri.segments) == 1:
            await service.remove(dataset.id, ctx.agent_id, expected_lock_version=dataset.lock_version)
        else:
            raise ValueError("Delete an exact Dataset or attachment")
        await get_db().commit()
        return ResourceMutation(uri=str(uri), operation="delete", state="deleted")

    async def search(self, ctx: ResourceContext, uri: ResourceUri, query: str, **options: Any) -> ResourceSearchResult:
        if not query.strip():
            raise ValueError("A search query is required")
        if options.get("mode", "name") == "semantic":
            raise NotImplementedError("Datasets currently support name and text search")
        if len(uri.segments) <= 1:
            limit = min(500, max(1, int(options.get("max_results") or 50)))
            statement = select(Dataset).where(accessible_clause(ctx.management_scope or ctx.agent_id))
            if uri.locator:
                await service.record(root_id(uri), ctx.management_scope or ctx.agent_id)
                statement = statement.where(Dataset.id == root_id(uri))
            condition = Dataset.title.icontains(query, autoescape=True)
            if options.get("mode") == "text":
                condition = or_(condition, Dataset.content.icontains(query, autoescape=True))
            statement = statement.where(condition)
            if options.get("cursor"):
                statement = statement.where(Dataset.id > UUID(options["cursor"]))
            rows = list(await get_db().scalars(statement.order_by(Dataset.id).limit(limit + 1)))
            hits = [ResourceSearchHit(resource=await self.info(ctx, parse_resource_uri(f"data://{item.id}")),
                excerpt=item.content[:500] if options.get("mode") == "text" else item.title) for item in rows[:limit]]
            return ResourceSearchResult(uri=str(uri), query=query, mode=options.get("mode", "name"), hits=hits,
                truncated=len(rows) > limit, next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None)
        page = await self.list(ctx, uri, max_entries=options.get("max_results") or 50, cursor=options.get("cursor"))
        hits: list[ResourceSearchHit] = []
        for entry in page.entries:
            text = entry.name
            if options.get("mode") == "text" and entry.uri.startswith("data://"):
                text += "\n" + (await service.record(UUID(entry.uri.removeprefix("data://")), ctx.management_scope or ctx.agent_id)).content
            if query.casefold() in text.casefold():
                hits.append(ResourceSearchHit(resource=entry, excerpt=text[:500]))
        return ResourceSearchResult(uri=str(uri), query=query, mode=options.get("mode", "name"), hits=hits,
            truncated=page.truncated, next_cursor=page.next_cursor)

    async def materialize(self, ctx: ResourceContext, uri: ResourceUri, destination: Path, **options: Any) -> MaterializedResource:
        if len(uri.segments) > 1:
            from app.file_share import materialize_resource
            attachment = await self._attachment(uri, ctx)
            if attachment.uri.startswith(f"document://{attachment.dataset_id}/attachments/"):
                if attachment.size_bytes is None or attachment.size_bytes > int(options["max_bytes"]):
                    raise ValueError("Legacy attachment exceeds the materialization limit")
                from app.document import read_document_attachment_file_resource
                metadata, content = await read_document_attachment_file_resource(attachment.dataset_id, attachment.id, agent_id=ctx.agent_id)
                if len(content) > int(options["max_bytes"]):
                    raise ValueError("Legacy attachment exceeds the materialization limit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                await complete_io(destination.write_bytes, content)
                return MaterializedResource(uri=str(uri), name=str(metadata["name"]), media_type=attachment.media_type, size=len(content))
            return await materialize_resource(ctx, attachment.uri, destination, max_bytes=int(options["max_bytes"]))
        dataset = await service.record(root_id(uri), ctx.management_scope or ctx.agent_id)
        content = dataset.content.encode("utf-8")
        if len(content) > int(options["max_bytes"]):
            raise ValueError("Dataset exceeds materialization limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        await complete_io(destination.write_bytes, content)
        return MaterializedResource(uri=f"data://{dataset.id}", name=dataset.title, media_type="application/json", size=len(content))
