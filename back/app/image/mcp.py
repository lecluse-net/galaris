"""Image MCP tools exposed to Hermes and the internal harness.

File arguments are canonical resource URIs resolved by ``app.file_share``. Sources are copied to
short-lived server temporaries for the specialist model; generated results are written through the
same virtual file facade.
"""

from __future__ import annotations

import mimetypes
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from loguru import logger
from PIL import Image

from . import image_service
from .schemas import ImageDimension, ImageGenerationOptions
from app.llm import ImageDimensionsError
from app.tools import RecoverableToolError
from app.file_share import (
    ResourceContext,
    ResourceUri,
    materialize_resource,
    parse_resource_uri,
    preferred_local_resource_uri,
    resource_create,
    resource_write,
    record_resource_description,
)
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import render_prompt, t

_DEFAULT_MIME = "image/png"
_MAX_IMAGE_RESOURCE_BYTES = 32_000_000


async def _context_language(ctx: McpToolContext) -> str:
    return await context_language(ctx)


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"image.{key}", language), **values)


def _as_optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_attachment_refs(value: Any) -> list[str]:
    """Coerce the flexible MCP argument to raw non-empty path references."""

    if value is None:
        return []
    if isinstance(value, str):
        clean = value.strip()
        return [clean] if clean else []
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_as_optional_text(item) for item in items if _as_optional_text(item)]
    clean = str(value).strip()
    return [clean] if clean else []


async def _resource_context(ctx: McpToolContext, language: str) -> ResourceContext:
    return ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        console_resource=ctx.resource("console"),
        language=language,
    )


def _destination(
    resource_ctx: ResourceContext,
    value: str,
    default_name: str,
) -> tuple[ResourceUri, str]:
    reference = parse_resource_uri(
        value or preferred_local_resource_uri(resource_ctx, default_name),
        allow_empty=True,
    )
    return reference, default_name if reference.is_collection else ""


async def _store_image(
    resource_ctx: ResourceContext,
    destination: str,
    data: bytes,
    *,
    default_name: str,
) -> str:
    reference, name = _destination(resource_ctx, destination, default_name)
    try:
        mutation = await resource_create(resource_ctx, reference, data, name=name)
    except FileExistsError:
        if reference.is_collection:
            raise
        mutation = await resource_write(resource_ctx, reference, data)
    return mutation.uri


@mcp_tool(
    "image",
    name="image_generate",
    description=(
        "Generate, edit, or compose an image. attachments accepts canonical resource URIs "
        "from any file_schemes provider; Galaris transfers them transparently. destination "
        "accepts any writable resource URI; it may be omitted only when console:// is "
        "advertised by file_schemes. width and height are preferred pixel dimensions, "
        "not requirements. Always use best effort: choose a nearby native size, preferably "
        "above the target, otherwise the closest available below, including the model maximum "
        "for oversized requests. Unknown size capabilities use model defaults. No confirmation "
        "is needed for this adjustment. Report the actual returned dimensions. Never resize "
        "or crop afterward or substitute SVG/code artwork for a generated image."
    ),
)
async def generate_image(
    ctx: McpToolContext,
    prompt: str,
    attachments: Any = None,
    destination: Any = "",
    width: ImageDimension | None = None,
    height: ImageDimension | None = None,
) -> str:
    """Generate or edit an image through the virtual resource facade."""
    language = await _context_language(ctx)
    options = ImageGenerationOptions(width=width, height=height)
    try:
        resource_ctx = await _resource_context(ctx, language)
        sources: list[tuple[bytes, str]] = []
        with TemporaryDirectory(prefix="galaris_image_sources_") as directory:
            root = Path(directory)
            for index, reference in enumerate(_as_attachment_refs(attachments)):
                path = root / f"source-{index}"
                materialized = await materialize_resource(
                    resource_ctx,
                    reference,
                    path,
                    max_bytes=_MAX_IMAGE_RESOURCE_BYTES,
                )
                media_type = materialized.media_type
                if not media_type.startswith("image/"):
                    media_type = (
                        mimetypes.guess_type(materialized.name)[0]
                        or materialized.media_type
                    )
                if not media_type.startswith("image/"):
                    raise ValueError(
                        f"Image attachment has unsupported MIME type: "
                        f"{materialized.media_type}"
                    )
                sources.append((path.read_bytes(), media_type))
            img, mime = await image_service.generate_image_bytes(
                prompt,
                sources or None,
                width=options.width,
                height=options.height,
                language=language,
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
            )
        with Image.open(BytesIO(img)) as image:
            actual_width, actual_height = image.size
        ext = (mime.split("/")[-1] or "png")
        raw_destination = _as_optional_text(destination)
        location = await _store_image(
            resource_ctx,
            raw_destination,
            img,
            default_name=f"generated_image.{ext}",
        )
        return _message(
            language, "generated", size=len(img), location=location,
            width=actual_width, height=actual_height,
        )
    except ImageDimensionsError as exc:
        raise RecoverableToolError(_message(language, "generation_failed", error=str(exc))) from exc
    except Exception as exc:
        logger.exception("MCP generate_image failed")
        # Provider/transport exceptions may contain credentials or response bodies.
        raise RecoverableToolError(_message(
            language, "generation_failed", error=_message(language, "generation_unavailable"),
        )) from exc


@mcp_tool(
    "image",
    name="image_read",
    description=(
        "Describe or analyze an image from any canonical resource URI, including console://, "
        "HTTPS, Messenger attachments, Nextcloud, Mail, or another connected "
        "file_schemes provider. Galaris transfers it to a bounded temporary file transparently. "
        "Successful analysis is always saved in Memory: as the textual content of a document "
        "attachment's unique Memory item, or as a private resource description for other URIs. "
        "Saving failure makes this tool fail."
    ),
    effect_policy="non_idempotent",
)
async def describe_image(
    ctx: McpToolContext,
    file: str,
    prompt: str | None = None,
) -> str:
    """Describe or analyze an image from any authorized resource provider."""
    language = await _context_language(ctx)
    try:
        resource_ctx = await _resource_context(ctx, language)
        with TemporaryDirectory(prefix="galaris_image_read_") as directory:
            path = Path(directory) / "source"
            materialized = await materialize_resource(
                resource_ctx,
                file,
                path,
                max_bytes=_MAX_IMAGE_RESOURCE_BYTES,
            )
            media_type = materialized.media_type
            if not media_type.startswith("image/"):
                media_type = mimetypes.guess_type(materialized.name)[0] or media_type
            description = await image_service.describe_image(
                path.read_bytes(),
                media_type,
                instruction=prompt or "",
                language=language,
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
            )
            await record_resource_description(resource_ctx, materialized.uri, description)
            return description
    except Exception as exc:
        logger.exception("MCP describe_image failed")
        raise RecoverableToolError(_message(language, "description_failed", error=str(exc))) from exc
