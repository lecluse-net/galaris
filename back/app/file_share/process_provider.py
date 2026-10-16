"""Read-only processus://run/<uuid> snapshots, authorized by Process."""

import json
from pathlib import Path
from typing import Any, Never
from uuid import UUID

from core.util import complete_io

from .resource_contracts import MaterializedResource, ResourceContext, ResourceDescriptor, ResourceRead, ResourceSchemeDescription
from .resource_uri import ResourceUri, ResourceUriError


class ProcessRunProvider:
    def description(self) -> ResourceSchemeDescription:
        return ResourceSchemeDescription(scheme="processus", label="Process runs",
            example="processus://run/<uuid>", native=True, capabilities=["info", "read", "copy"])

    async def _snapshot(self, ctx: ResourceContext, uri: ResourceUri) -> tuple[str, dict[str, Any], str]:
        if uri.scheme != "processus" or uri.is_collection or len(uri.segments) != 2 or uri.segments[0] != "run":
            raise ResourceUriError("Expected processus://run/<uuid>")
        try:
            identity = UUID(uri.segments[1])
        except ValueError as error:
            raise ResourceUriError("A process run requires a valid UUID") from error
        from app.process import read_process_run_resource

        payload = await read_process_run_resource(identity, actor_agent_id=ctx.agent_id)
        canonical = f"processus://run/{identity}"
        return canonical, payload, json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    async def info(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceDescriptor:
        canonical, payload, content = await self._snapshot(ctx, uri)
        return ResourceDescriptor(uri=canonical, name=str(payload.get("label") or payload.get("process_label") or payload["id"]),
            media_type="application/json", size=len(content.encode("utf-8")), capabilities=["info", "read", "copy"])

    async def read(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceRead:
        canonical, _, content = await self._snapshot(ctx, uri)
        start = max(0, int(options.get("offset", 0)))
        limit = max(1, min(int(options.get("max_chars", 20_000)), 200_000))
        end = min(len(content), start + limit)
        start = min(start, end)
        return ResourceRead(uri=canonical, content=content[start:end], media_type="application/json",
            start=start, end=end, total=len(content), next_offset=end if end < len(content) else None)

    async def materialize(self, ctx: ResourceContext, uri: ResourceUri, destination: Path, **options: Any) -> MaterializedResource:
        canonical, payload, content = await self._snapshot(ctx, uri)
        data = content.encode("utf-8")
        maximum = int(options.get("max_bytes", 0))
        if maximum <= 0 or len(data) > maximum:
            raise ValueError("Process snapshot exceeds the materialization byte limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        await complete_io(destination.write_bytes, data)
        return MaterializedResource(uri=canonical, name=f"{payload['id']}.json", media_type="application/json", size=len(data))

    async def _unsupported(self, ctx: ResourceContext, uri: ResourceUri, *args: object, **options: Any) -> Never:
        raise PermissionError("Process run resources are read-only. Use the Process tools for discovery and controls.")

    list = _unsupported
    search = _unsupported
    create = _unsupported
    write = _unsupported
    append = _unsupported
    edit = _unsupported
    delete = _unsupported
