"""Materialize agent-readable files for one REST call and bind consent to their contents."""

import hashlib
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

from core.util import complete_io
from .contracts import ToolArgumentsRejectedError
from .mcp_loader import McpToolContext
from .rest_contracts import RestToolRequest, RestUpload

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


async def load_uploads(ctx: McpToolContext, request: RestToolRequest) -> tuple[RestUpload, ...]:
    if not request.files and request.file_uri is None:
        return ()
    from app.file_share import ResourceContext, materialize_resource

    actor = ResourceContext(
        agent_id=ctx.agent_id, runtime=ctx.runtime, task_id=ctx.task_id,
        console_resource=ctx.resource("console"), conversation_turn=ctx.resource("conversation_turn"),
    )
    parts = [(part.field, part.uri, part.filename, part.content_type) for part in request.files]
    if request.file_uri is not None:
        parts.append(("", request.file_uri, None, None))
    uploads: list[RestUpload] = []
    remaining = MAX_UPLOAD_BYTES
    with TemporaryDirectory(prefix="galaris-rest-upload-") as directory:
        for index, (field, uri, filename, content_type) in enumerate(parts):
            path = Path(directory) / str(index)
            try:
                file = await materialize_resource(actor, uri, path, max_bytes=max(1, remaining))
            except (OSError, ValueError) as exc:
                raise ToolArgumentsRejectedError(
                    "REST upload requires a readable file URI within the combined 32 MiB limit."
                ) from exc
            if path.stat().st_size > remaining:
                raise ToolArgumentsRejectedError("REST uploads exceed 32 MiB in total.")
            content = await complete_io(path.read_bytes)
            remaining -= len(content)
            name = filename or re.sub(r"[/\\\x00-\x1f\x7f]", "_", file.name)[:255] or "file"
            media = content_type or file.media_type
            if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+", media or ""):
                media = "application/octet-stream"
            uploads.append(RestUpload(field, name, media, content))
    return tuple(uploads)


async def upload_preflight(ctx: McpToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    uploads = await load_uploads(ctx, arguments["request"])
    if not uploads:
        return {}
    # The loader gives each REST invocation private resources. A resumed call reads
    # the source again, and only the bytes matching the approved snapshot can be sent.
    ctx.resources["rest_uploads"] = uploads
    return {"uploads": [{"filename": part.filename, "content_type": part.content_type,
                         "sha256": hashlib.sha256(part.content).hexdigest()} for part in uploads]}
