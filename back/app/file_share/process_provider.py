"""Process-owned snapshots, run JSON and attachment resources."""

import json
import base64
import shutil
from pathlib import Path
from typing import Any, Never, cast
from uuid import UUID

from core.util import complete_io

from .resource_contracts import MaterializedResource, ResourceContext, ResourceDescriptor, ResourceRead, ResourceMutation, ResourceListing, ResourceSearchResult, ResourceSearchHit
from .resource_uri import ResourceUri, ResourceUriError


class ProcessRunProvider:
    def _root(self, uri: ResourceUri) -> bool:
        return uri.scheme == "galaris" and uri.segments == ("processes", "runs") and uri.is_collection

    def _target(self, uri: ResourceUri) -> tuple[UUID, str]:
        if uri.scheme != "galaris" or len(uri.segments) < 3 or uri.segments[:2] != ("processes", "runs"):
            raise ResourceUriError("Expected galaris://processes/runs/<uuid>[/data|/attachments/]")
        identity = UUID(uri.segments[2])
        suffix = "/".join(uri.segments[3:])
        if suffix not in {"", "data", "attachments"} and not (len(uri.segments) == 5 and uri.segments[3] == "attachments"):
            raise ResourceUriError("Invalid process resource")
        if uri.is_collection != (suffix == "attachments"):
            raise ResourceUriError("Only the run attachments path is a collection")
        return identity, suffix

    async def _data(self, ctx: ResourceContext, uri: ResourceUri) -> dict[str, Any]:
        from app.process import read_run_data
        identity, _ = self._target(uri)
        return await read_run_data(identity, ctx.agent_id)

    async def _snapshot(self, ctx: ResourceContext, uri: ResourceUri) -> tuple[str, dict[str, Any], str]:
        if uri.scheme != "galaris" or uri.is_collection or len(uri.segments) != 3 or uri.segments[:2] != ("processes", "runs"):
            raise ResourceUriError("Expected galaris://processes/runs/<uuid>")
        try:
            identity = UUID(uri.segments[2])
        except ValueError as error:
            raise ResourceUriError("A process run requires a valid UUID") from error
        from app.process import read_process_run_resource

        payload = await read_process_run_resource(identity, actor_agent_id=ctx.agent_id, management_scope=ctx.management_scope)
        canonical = f"galaris://processes/runs/{identity}"
        return canonical, payload, json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    async def info(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceDescriptor:
        if self._root(uri):
            return ResourceDescriptor(uri=str(uri), name="Runs", is_collection=True, capabilities=["info", "list"])
        identity, suffix = self._target(uri)
        if suffix == "attachments":
            payload = await self._data(ctx, uri)
            return ResourceDescriptor(uri=str(uri), name="attachments", is_collection=True,
                capabilities=["info", "list", "copy", *(["create"] if payload["can_write"] else [])])
        if suffix.startswith("attachments/"):
            from app.process import run_file_path
            metadata, _ = await run_file_path(identity, UUID(uri.segments[4]), ctx.agent_id)
            payload = await self._data(ctx, uri)
            return ResourceDescriptor(**metadata,
                capabilities=["info", "read", "copy", *(["delete"] if payload["can_write"] else [])])
        if suffix == "data":
            payload = await self._data(ctx, uri)
            return ResourceDescriptor(uri=str(uri), name="data.json", media_type="application/json",
                size=len(json.dumps(payload["data"], ensure_ascii=False, indent=2).encode()), revision=payload["revision"],
                capabilities=["info", "read", "copy", *(["write", "edit"] if payload["can_write"] else [])])
        canonical, payload, content = await self._snapshot(ctx, uri)
        return ResourceDescriptor(uri=canonical, name=str(payload.get("label") or payload.get("process_label") or payload["id"]),
            media_type="application/json", size=len(content.encode("utf-8")), capabilities=["info", "read", "copy"])

    async def read(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceRead:
        identity, suffix = self._target(uri)
        revision: int | None = None
        media_type = "application/json"
        encoding = "utf-8"
        if suffix.startswith("attachments/"):
            from app.process import run_file_path
            metadata, path = await run_file_path(identity, UUID(uri.segments[4]), ctx.agent_id)
            if metadata["size"] > 1_048_576:
                raise ValueError("Use file_copy or a specialized reader for a large run attachment")
            raw = await complete_io(path.read_bytes)
            media_type = metadata["media_type"]
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(raw).decode("ascii"), "base64"
            canonical = str(uri)
        elif suffix == "data":
            payload = await self._data(ctx, uri)
            canonical, content, revision = str(uri), json.dumps(payload["data"], ensure_ascii=False, indent=2), payload["revision"]
        else:
            canonical, _, content = await self._snapshot(ctx, uri)
        start = max(0, int(options.get("offset", 0)))
        limit = max(1, min(int(options.get("max_chars", 20_000)), 200_000))
        end = min(len(content), start + limit)
        start = min(start, end)
        return ResourceRead(uri=canonical, content=content[start:end], media_type=media_type,
            encoding="base64" if encoding == "base64" else "utf-8", revision=revision,
            start=start, end=end, total=len(content), next_offset=end if end < len(content) else None)

    async def materialize(self, ctx: ResourceContext, uri: ResourceUri, destination: Path, **options: Any) -> MaterializedResource:
        identity, suffix = self._target(uri)
        if suffix.startswith("attachments/"):
            from app.process import run_file_path
            metadata, source = await run_file_path(identity, UUID(uri.segments[4]), ctx.agent_id)
            if int(options.get("max_bytes", 0)) <= 0 or metadata["size"] > int(options["max_bytes"]):
                raise ValueError("Run attachment exceeds the materialization byte limit")
            destination.parent.mkdir(parents=True, exist_ok=True)
            await complete_io(shutil.copyfile, source, destination)
            return MaterializedResource(uri=str(uri), name=metadata["name"], media_type=metadata["media_type"], size=metadata["size"])
        if suffix == "data":
            payload = await self._data(ctx, uri)
            canonical, content = str(uri), json.dumps(payload["data"], ensure_ascii=False, indent=2)
        else:
            canonical, payload, content = await self._snapshot(ctx, uri)
        data = content.encode("utf-8")
        maximum = int(options.get("max_bytes", 0))
        if maximum <= 0 or len(data) > maximum:
            raise ValueError("Process snapshot exceeds the materialization byte limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        await complete_io(destination.write_bytes, data)
        return MaterializedResource(uri=canonical, name=f"{payload['id']}.json", media_type="application/json", size=len(data))

    async def list(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceListing:
        if self._root(uri):
            from app.process import list_process_run_resources
            start, limit = max(0, int(options.get("cursor") or 0)), min(500, max(1, int(options.get("max_entries", 50))))
            rows = await list_process_run_resources(actor_agent_id=ctx.management_scope or ctx.agent_id, offset=start, limit=limit + 1)
            return ResourceListing(uri=str(uri), entries=[ResourceDescriptor(uri=row["uri"], name=row["name"],
                media_type="application/json", capabilities=["info", "read", "copy"], modified_at=row["created_at"]) for row in rows[:limit]],
                truncated=len(rows) > limit, next_cursor=str(start + limit) if len(rows) > limit else None)
        _, suffix = self._target(uri)
        if suffix != "attachments":
            raise NotADirectoryError(str(uri))
        files = (await self._data(ctx, uri))["files"]
        start, limit = int(options.get("cursor") or 0), min(500, max(1, int(options.get("max_entries", 50))))
        entries: list[ResourceDescriptor] = []
        for entry in files[start:start + limit]:
            from .resource_service import resource_info
            descriptor = await resource_info(ctx, entry["uri"])
            entries.append(descriptor)
        end = start + limit
        return ResourceListing(uri=str(uri), entries=entries, truncated=end < len(files), next_cursor=str(end) if end < len(files) else None)

    async def write(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation:
        identity, suffix = self._target(uri)
        if suffix != "data":
            return await self._unsupported(ctx, uri)
        from app.process import write_run_data
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Run JSON contains duplicate object keys")
                result[key] = value
            return result
        if len(content) > 2_000_000:
            raise ValueError("Run data exceeds its JSON limit")
        value: Any = json.loads(content, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError("Run data must be a JSON object")
        payload = await write_run_data(identity, ctx.agent_id, cast(dict[str, Any], value), expected_revision=options.get("expected_revision"))
        return ResourceMutation(uri=str(uri), operation="write", state="written", revision=payload["revision"], size=len(content))

    async def edit(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation:
        _, suffix = self._target(uri)
        if suffix != "data":
            return await self._unsupported(ctx, uri)
        payload = await self._data(ctx, uri)
        lines = json.dumps(payload["data"], ensure_ascii=False, indent=2).splitlines(keepends=True)
        first, last = int(options["start_line"]), int(options["end_line"])
        if first < 1 or last < first or last > len(lines):
            raise ValueError("Run data edit range is outside the current content")
        replacement = str(options["content"])
        if lines[last - 1].endswith("\n") and replacement and not replacement.endswith("\n"):
            replacement += "\n"
        content = "".join(lines[:first - 1]) + replacement + "".join(lines[last:])
        result = await self.write(ctx, uri, content.encode(), **{key: value for key, value in options.items() if key != "content"})
        return result.model_copy(update={"operation": "edit"})

    async def create(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation:
        identity, suffix = self._target(uri)
        if suffix != "attachments":
            raise PermissionError("Create files in the run attachments collection")
        from app.process import add_run_file
        result = await add_run_file(identity, ctx.agent_id, content, name=str(options.get("name") or "file"))
        return ResourceMutation(uri=result["uri"], operation="create", state="created", size=result["size"])

    async def delete(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation:
        identity, suffix = self._target(uri)
        if not suffix.startswith("attachments/"):
            return await self._unsupported(ctx, uri)
        from app.process import delete_run_file
        await delete_run_file(identity, UUID(uri.segments[4]), ctx.agent_id)
        return ResourceMutation(uri=str(uri), operation="delete", state="deleted")

    async def _unsupported(self, ctx: ResourceContext, uri: ResourceUri, *args: object, **options: Any) -> Never:
        raise PermissionError("Process run resources are read-only. Use the Process tools for discovery and controls.")

    async def search(self, ctx: ResourceContext, uri: ResourceUri, query: str, **options: Any) -> ResourceSearchResult:
        if not self._root(uri) or options.get("mode", "name") != "name":
            raise NotImplementedError("Run name search requires the runs collection")
        from app.process import list_process_run_resources
        start, limit = max(0, int(options.get("cursor") or 0)), min(500, max(1, int(options.get("max_results") or 50)))
        rows = await list_process_run_resources(actor_agent_id=ctx.management_scope or ctx.agent_id, query=query, offset=start, limit=limit + 1)
        return ResourceSearchResult(uri=str(uri), query=query, mode="name", hits=[ResourceSearchHit(resource=ResourceDescriptor(
            uri=row["uri"], name=row["name"], media_type="application/json", capabilities=["info", "read", "copy"])) for row in rows[:limit]],
            truncated=len(rows) > limit, next_cursor=str(start + limit) if len(rows) > limit else None)

    append = _unsupported
