"""Native MCP functions for the isolated interactive browser."""

from __future__ import annotations

import base64
import json
import re
from typing import Annotated, Any, Literal

from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from loguru import logger
from mcp.types import TextContent
from pydantic import Field

from app.file_share import (
    ResourceContext,
    preferred_local_resource_uri,
    resource_create,
    resource_write,
)
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import render_prompt, t
from core.params import runtime_settings

from .schemas import BrowserContent, BrowserOutput, BrowserScreenshot, ImageFormat
from .service import BrowserExecutorError, browser_executor, resolve_default_output

RequestedOutput = Literal["default", "content", "screenshot"]
ViewportWidth = Annotated[int, Field(ge=320, le=3_840)]
ViewportHeight = Annotated[int, Field(ge=240, le=2_160)]


async def _message(ctx: McpToolContext, key: str, **values: Any) -> str:
    language = await context_language(ctx)
    return render_prompt(t(f"browser.{key}", language), **values)


async def _safe_error(ctx: McpToolContext, exc: BrowserExecutorError) -> str:
    known = {
        "invalid_url",
        "invalid_viewport",
        "session_not_found",
        "capacity_reached",
        "unavailable",
    }
    key = exc.code if exc.code in known else "failed"
    return await _message(ctx, f"errors.{key}", code=exc.code)


async def _resolve_output(ctx: McpToolContext, output: RequestedOutput) -> BrowserOutput:
    if output == "content" or output == "screenshot":
        return output
    return await resolve_default_output(ctx.agent_id)


def _track_owner_cleanup(ctx: McpToolContext) -> None:
    run_resource = ctx.resource("run")
    add_cleanup = getattr(run_resource, "add_cleanup", None)
    if not callable(add_cleanup):
        return

    async def close_owner() -> None:
        await browser_executor.close_owner(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
        )

    add_cleanup(
        f"browser-owner:{ctx.agent_id}:{ctx.task_id}",
        close_owner,
    )


def _content_text(result: BrowserContent) -> str:
    header = {
        "session_id": result.session_id,
        "url": result.url,
        "title": result.title,
        "revision": result.revision,
        "slice": {
            "start": result.start,
            "end": result.end,
            "total": result.total,
            "truncated": result.truncated,
            "next_offset": result.next_offset,
        },
    }
    return f"{json.dumps(header, ensure_ascii=False)}\n\n{result.content}"


async def _write_part(ctx: McpToolContext, destination: str, data: bytes) -> str:
    resource_ctx = ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        console_resource=ctx.resource("console"),
        language=await context_language(ctx),
    )
    uri = preferred_local_resource_uri(resource_ctx, destination)
    try:
        result = await resource_create(resource_ctx, uri, data)
    except FileExistsError:
        result = await resource_write(resource_ctx, uri, data)
    return result.uri


async def _screenshot_result(
    ctx: McpToolContext,
    result: BrowserScreenshot,
) -> ToolResult:
    safe_session = re.sub(r"[^a-zA-Z0-9-]", "", result.session_id) or "session"
    console_available = ctx.resource("console") is not None
    blocks: list[Any] = []
    files: list[dict[str, object]] = []
    for part in result.parts:
        try:
            data = base64.b64decode(part.data, validate=True)
        except ValueError as exc:
            raise BrowserExecutorError("invalid_response") from exc
        extension = "png" if part.mime_type == "image/png" else "jpg"
        destination = (
            f"browser/{safe_session}/capture-r{result.revision}"
            f"-part-{part.index + 1:03d}.{extension}"
        )
        file: dict[str, object] = {
            "index": part.index,
            "path": None,
            "y": part.y,
            "width": part.width,
            "height": part.height,
            "bytes": len(data),
            "mime_type": part.mime_type,
        }
        if console_available:
            try:
                file["path"] = await _write_part(ctx, destination, data)
            except Exception as exc:
                logger.warning(
                    "Browser screenshot persistence failed (error_type={})",
                    type(exc).__name__,
                )
        files.append(file)
        blocks.append(
            Image(
                data=data,
                format="png" if extension == "png" else "jpeg",
            ).to_image_content()
        )
    manifest = {
        "session_id": result.session_id,
        "url": result.url,
        "title": result.title,
        "revision": result.revision,
        "page_width": result.page_width,
        "page_height": result.page_height,
        "captured_height": result.captured_height,
        "truncated": result.truncated,
        "parts": files,
    }
    blocks.insert(
        0,
        TextContent(
            type="text",
            text=json.dumps(manifest, ensure_ascii=False),
        ),
    )
    return ToolResult(content=blocks, structured_content=manifest)


async def _present(
    ctx: McpToolContext,
    result: BrowserContent | BrowserScreenshot,
) -> str | ToolResult:
    if isinstance(result, BrowserScreenshot):
        return await _screenshot_result(ctx, result)
    return _content_text(result)


async def _action(
    ctx: McpToolContext,
    session_id: str,
    action: Literal["navigate", "click", "type", "press", "scroll", "back"],
    output: RequestedOutput,
    **values: Any,
) -> str | ToolResult:
    try:
        _track_owner_cleanup(ctx)
        resolved = await _resolve_output(ctx, output)
        result = await browser_executor.action(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            session_id=session_id,
            action=action,
            output=resolved,
            **values,
        )
        return await _present(ctx, result)
    except BrowserExecutorError as exc:
        return await _safe_error(ctx, exc)
    except Exception as exc:
        logger.exception(
            "Browser MCP action failed (action={}, error_type={})",
            action,
            type(exc).__name__,
        )
        return await _message(ctx, "errors.failed", code="internal_error")


@mcp_tool(
    "browser",
    name="browser_open",
    description=(
        "Open any reachable HTTP(S) page, including local and private-network URLs, in a new "
        "isolated session. Returns the accessible page "
        "content by default, including stable element refs such as e12. Optional viewport "
        "dimensions in CSS pixels select a responsive desktop or mobile layout."
    ),
)
async def browser_open(
    ctx: McpToolContext,
    url: str,
    output: RequestedOutput = "default",
    viewport_width: ViewportWidth | None = None,
    viewport_height: ViewportHeight | None = None,
) -> str | ToolResult:
    try:
        _track_owner_cleanup(ctx)
        result = await browser_executor.open(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            url=url,
            output=await _resolve_output(ctx, output),
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        return await _present(ctx, result)
    except BrowserExecutorError as exc:
        return await _safe_error(ctx, exc)
    except Exception as exc:
        logger.exception("Browser MCP open failed (error_type={})", type(exc).__name__)
        return await _message(ctx, "errors.failed", code="internal_error")


@mcp_tool(
    "browser",
    name="browser_navigate",
    description=(
        "Navigate an existing browser session to another reachable HTTP(S) URL, including "
        "local and private-network destinations."
    ),
)
async def browser_navigate(
    ctx: McpToolContext,
    session_id: str,
    url: str,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(ctx, session_id, "navigate", output, url=url)


@mcp_tool(
    "browser",
    name="browser_content",
    description=(
        "Read accessible page content and element refs. Use offset to continue a truncated page."
    ),
)
async def browser_content(
    ctx: McpToolContext,
    session_id: str,
    offset: int = 0,
    max_chars: int = 20_000,
) -> str:
    try:
        _track_owner_cleanup(ctx)
        result = await browser_executor.action(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            session_id=session_id,
            action="content",
            output="content",
            offset=max(0, offset),
            max_chars=min(runtime_settings.BROWSER_CONTENT_MAX_CHARS, max(1_000, max_chars)),
        )
        if not isinstance(result, BrowserContent):
            raise BrowserExecutorError("invalid_response")
        return _content_text(result)
    except BrowserExecutorError as exc:
        return await _safe_error(ctx, exc)
    except Exception as exc:
        logger.exception("Browser MCP content failed (error_type={})", type(exc).__name__)
        return await _message(ctx, "errors.failed", code="internal_error")


@mcp_tool(
    "browser",
    name="browser_screenshot",
    description=(
        "Capture the current page of an existing browser session; this tool does not open a URL. "
        "Reliable sequence: call browser_open with output='content', keep its exact session_id, "
        "navigate or interact in that same task, then use browser_content to verify the final "
        "URL and visible state before calling this tool. Pass that unchanged session_id promptly, "
        "because idle sessions expire. If session_not_found is returned, open the page again and "
        "use the new session_id instead of retrying the stale one. The capture waits for the "
        "document, loads lazy content, and returns the complete page in bounded vertical image "
        "parts. Use 1440x900 for desktop or 390x844 for mobile; viewport height does not crop the "
        "full page. Prefer jpeg for ordinary pages and png when exact UI text or fine details "
        "matter. Captured image blocks are returned independently of local file storage. Each "
        "manifest part has path=null unless it was additionally saved under the local file "
        "scheme of an attached console."
    ),
)
async def browser_screenshot(
    ctx: McpToolContext,
    session_id: str,
    image_format: ImageFormat = "jpeg",
    viewport_width: ViewportWidth | None = None,
    viewport_height: ViewportHeight | None = None,
) -> str | ToolResult:
    try:
        _track_owner_cleanup(ctx)
        result = await browser_executor.action(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            session_id=session_id,
            action="screenshot",
            output="screenshot",
            image_format=image_format,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        if not isinstance(result, BrowserScreenshot):
            raise BrowserExecutorError("invalid_response")
        return await _screenshot_result(ctx, result)
    except BrowserExecutorError as exc:
        return await _safe_error(ctx, exc)
    except Exception as exc:
        logger.exception("Browser MCP screenshot failed (error_type={})", type(exc).__name__)
        return await _message(ctx, "errors.failed", code="internal_error")


@mcp_tool(
    "browser",
    name="browser_click",
    description="Click an element using a ref returned by browser content, for example e12.",
)
async def browser_click(
    ctx: McpToolContext,
    session_id: str,
    ref: str,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(ctx, session_id, "click", output, ref=ref)


@mcp_tool(
    "browser",
    name="browser_type",
    description="Replace the value of a referenced input and optionally submit it.",
)
async def browser_type(
    ctx: McpToolContext,
    session_id: str,
    ref: str,
    text: str,
    submit: bool = False,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(
        ctx,
        session_id,
        "type",
        output,
        ref=ref,
        text=text,
        submit=submit,
    )


@mcp_tool(
    "browser",
    name="browser_press",
    description="Press a keyboard key or shortcut in the active page, such as Enter or Control+L.",
)
async def browser_press(
    ctx: McpToolContext,
    session_id: str,
    key: str,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(ctx, session_id, "press", output, key=key)


@mcp_tool(
    "browser",
    name="browser_scroll",
    description="Scroll the page vertically by a signed pixel amount.",
)
async def browser_scroll(
    ctx: McpToolContext,
    session_id: str,
    delta_y: int,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(ctx, session_id, "scroll", output, delta_y=delta_y)


@mcp_tool(
    "browser",
    name="browser_back",
    description="Navigate the browser session back one history entry.",
)
async def browser_back(
    ctx: McpToolContext,
    session_id: str,
    output: RequestedOutput = "default",
) -> str | ToolResult:
    return await _action(ctx, session_id, "back", output)


@mcp_tool(
    "browser",
    name="browser_close",
    description="Close a browser session and release its isolated resources.",
)
async def browser_close(ctx: McpToolContext, session_id: str) -> str:
    try:
        result = await browser_executor.close(
            agent_id=ctx.agent_id,
            task_id=ctx.task_id,
            session_id=session_id,
        )
        return await _message(ctx, "closed", session_id=result.session_id)
    except BrowserExecutorError as exc:
        return await _safe_error(ctx, exc)
    except Exception as exc:
        logger.exception("Browser MCP close failed (error_type={})", type(exc).__name__)
        return await _message(ctx, "errors.failed", code="internal_error")
