"""Client and policy boundary for the isolated browser executor."""

from __future__ import annotations

from core.user import HumanActor

import asyncio
import base64
import binascii
from contextvars import Context
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx
from loguru import logger

from core.preview import thumbnails
from core.settings import settings
from core.secrets import browser_executor_token
from core.params import runtime_settings

from .schemas import (
    BrowserClosed,
    BrowserContent,
    BrowserOutput,
    BrowserOwner,
    BrowserOwnerClosed,
    BrowserPageMetadata,
    BrowserScreenshot,
    ImageFormat,
)

ExecutorResult = BrowserContent | BrowserScreenshot
_VIEWPORT_WIDTH_RANGE = (320, 3_840)
_VIEWPORT_HEIGHT_RANGE = (240, 2_160)
BrowserAction = Literal[
    "navigate",
    "content",
    "screenshot",
    "click",
    "type",
    "press",
    "scroll",
    "back",
]

# Public executor protocol codes, never arbitrary response text or signed URLs.
_ERROR_CODES = frozenset({
    "invalid_url", "invalid_viewport", "session_not_found", "capacity_reached",
    "unavailable", "executor_failed", "invalid_response", "blocked_url", "dns_failed",
    "invalid_ref", "invalid_action", "invalid_json", "invalid_key", "invalid_owner",
    "not_found", "payload_too_large", "text_too_long", "invalid_settings",
    "invalid_pdf_html", "pdf_too_large", "browser_failed", "internal_error", "unauthorized",
})


class BrowserExecutorError(RuntimeError):
    """Safe executor failure carrying only a stable machine-readable code."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        code = code if code in _ERROR_CODES else "executor_failed"
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _viewport_payload(
    viewport_width: int | None,
    viewport_height: int | None,
) -> dict[str, int]:
    dimensions = {
        "viewport_width": (viewport_width, _VIEWPORT_WIDTH_RANGE),
        "viewport_height": (viewport_height, _VIEWPORT_HEIGHT_RANGE),
    }
    payload: dict[str, int] = {}
    for name, (value, (minimum, maximum)) in dimensions.items():
        if value is None:
            continue
        if isinstance(value, bool) or not minimum <= value <= maximum:
            raise BrowserExecutorError("invalid_viewport")
        payload[name] = value
    return payload


def validate_http_url_shape(value: str) -> str:
    """Reject malformed URL shapes before crossing the container boundary.

    DNS resolution, redirects, and every browser subresource are handled again by
    the executor. Private, reserved, and local destinations are intentionally valid.
    """

    raw = value.strip()
    if not raw or len(raw) > 4_096:
        raise BrowserExecutorError("invalid_url")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise BrowserExecutorError("invalid_url") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise BrowserExecutorError("invalid_url")
    return raw


def _owner(agent_id: int | HumanActor, task_id: object | None) -> BrowserOwner:
    if isinstance(agent_id, HumanActor):
        return BrowserOwner(user_id=agent_id.user_id)
    return BrowserOwner(
        agent_id=agent_id,
        task_id=str(task_id) if task_id is not None else None,
    )


async def resolve_default_output(agent_id: int) -> BrowserOutput:
    """Resolve the per-agent connection preference, falling back to content."""

    from app.connection import connection_service
    from app.tools import tool_service

    for connection in await connection_service.get_connections_by_agent(agent_id):
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool is None or tool.code != "browser":
            continue
        _, params = await connection_service.get_params_as_dict(
            connection,
            decrypt_passwords=False,
        )
        value = str(params.get("default_output") or "content").strip().lower()
        return "screenshot" if value == "screenshot" else "content"
    return "content"


class BrowserExecutor:
    """Small authenticated HTTP client for the browser sidecar."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.BROWSER_EXECUTOR_URL).rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=(self._timeout if self._timeout is not None else runtime_settings.BROWSER_EXECUTOR_TIMEOUT_SECONDS),
                transport=self._transport,
                headers={
                    "X-Galaris-Browser-Token": self._token or browser_executor_token(),
                    "Accept": "application/json",
                },
            ) as client:
                response = await client.post(path, json={
                    **payload,
                    "settings": {
                        "session_ttl_seconds": runtime_settings.BROWSER_SESSION_TTL_SECONDS,
                        "max_sessions": runtime_settings.BROWSER_MAX_SESSIONS,
                        "content_max_chars": runtime_settings.BROWSER_CONTENT_MAX_CHARS,
                        "html_max_bytes": runtime_settings.BROWSER_HTML_MAX_BYTES,
                        "screenshot_tile_height": runtime_settings.BROWSER_SCREENSHOT_TILE_HEIGHT,
                        "screenshot_max_tiles": runtime_settings.BROWSER_SCREENSHOT_MAX_TILES,
                        "screenshot_max_total_bytes": runtime_settings.BROWSER_SCREENSHOT_MAX_TOTAL_BYTES,
                        "viewport_width": runtime_settings.BROWSER_VIEWPORT_WIDTH,
                        "viewport_height": runtime_settings.BROWSER_VIEWPORT_HEIGHT,
                    },
                })
        except httpx.HTTPError as exc:
            logger.warning(
                "Browser executor unavailable (error_type={})",
                type(exc).__name__,
            )
            raise BrowserExecutorError("unavailable") from exc
        if response.is_error:
            code = "executor_failed"
            try:
                body: object = response.json()
                error = cast(dict[str, object], body).get("error") if isinstance(body, dict) else None
                if isinstance(error, dict):
                    candidate = cast(dict[str, object], error).get("code")
                    if isinstance(candidate, str) and candidate in _ERROR_CODES:
                        code = candidate
            except ValueError:
                pass
            logger.warning(
                "Browser executor rejected operation (status={}, code={})",
                response.status_code,
                code,
            )
            raise BrowserExecutorError(code, response.status_code)
        try:
            body = response.json()
        except ValueError as exc:
            raise BrowserExecutorError("invalid_response") from exc
        if not isinstance(body, dict):
            raise BrowserExecutorError("invalid_response")
        return cast(dict[str, Any], body)

    async def open(
        self,
        *,
        agent_id: int | HumanActor,
        task_id: object | None,
        url: str,
        output: BrowserOutput,
        image_format: ImageFormat = "jpeg",
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> ExecutorResult:
        dimensions = {
            key: value
            for key, value in {
                "max_width": max_width,
                "max_height": max_height,
            }.items()
            if value is not None
        }
        body = await self._post(
            "/v1/open",
            {
                "owner": _owner(agent_id, task_id).model_dump(exclude={"user_id"} if isinstance(agent_id, int) else {"agent_id"}),
                "url": validate_http_url_shape(url),
                "output": output,
                "image_format": image_format,
                **_viewport_payload(viewport_width, viewport_height),
                **dimensions,
            },
        )
        return self._parse_result(body, output)

    async def action(
        self,
        *,
        agent_id: int | HumanActor,
        task_id: object | None,
        session_id: str,
        action: BrowserAction,
        output: BrowserOutput,
        image_format: ImageFormat = "jpeg",
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        **values: object,
    ) -> ExecutorResult:
        if action == "navigate":
            values["url"] = validate_http_url_shape(str(values.get("url") or ""))
        body = await self._post(
            "/v1/action",
            {
                "owner": _owner(agent_id, task_id).model_dump(exclude={"user_id"} if isinstance(agent_id, int) else {"agent_id"}),
                "session_id": session_id,
                "action": action,
                "output": output,
                "image_format": image_format,
                **_viewport_payload(viewport_width, viewport_height),
                **values,
            },
        )
        expected = "screenshot" if action == "screenshot" else output
        return self._parse_result(body, expected)

    async def render_html(
        self,
        *,
        agent_id: int | HumanActor,
        task_id: object | None,
        content: bytes,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> BrowserScreenshot:
        if not content or len(content) > runtime_settings.BROWSER_HTML_MAX_BYTES:
            raise BrowserExecutorError("payload_too_large", 413)
        body = await self._post(
            "/v1/render-html",
            {
                "owner": _owner(agent_id, task_id).model_dump(exclude={"user_id"} if isinstance(agent_id, int) else {"agent_id"}),
                "html_base64": base64.b64encode(content).decode("ascii"),
                **(
                    {"max_width": max_width}
                    if max_width is not None
                    else {}
                ),
                **(
                    {"max_height": max_height}
                    if max_height is not None
                    else {}
                ),
            },
        )
        try:
            return BrowserScreenshot.model_validate(body)
        except ValueError as exc:
            raise BrowserExecutorError("invalid_response") from exc

    async def close(
        self,
        *,
        agent_id: int | HumanActor,
        task_id: object | None,
        session_id: str,
    ) -> BrowserClosed:
        body = await self._post(
            "/v1/close",
            {
                "owner": _owner(agent_id, task_id).model_dump(exclude={"user_id"} if isinstance(agent_id, int) else {"agent_id"}),
                "session_id": session_id,
            },
        )
        return BrowserClosed.model_validate(body)

    async def close_owner(
        self,
        *,
        agent_id: int | HumanActor,
        task_id: object | None,
    ) -> BrowserOwnerClosed:
        """Release every browser session owned by one agent run."""

        body = await self._post(
            "/v1/close-owner",
            {"owner": _owner(agent_id, task_id).model_dump(exclude={"user_id"} if isinstance(agent_id, int) else {"agent_id"})},
        )
        return BrowserOwnerClosed.model_validate(body)

    @staticmethod
    def _parse_result(body: dict[str, Any], output: BrowserOutput) -> ExecutorResult:
        try:
            if output == "screenshot":
                return BrowserScreenshot.model_validate(body)
            return BrowserContent.model_validate(body)
        except ValueError as exc:
            raise BrowserExecutorError("invalid_response") from exc


browser_executor = BrowserExecutor()
_capture_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


async def capture_public_page_thumbnail(
    *,
    agent_id: int | HumanActor,
    url: str,
    refresh: bool = False,
) -> tuple[bytes, str] | None:
    """Capture a public page using the shared resource thumbnail cache."""
    return await _capture_thumbnail(agent_id=agent_id, reference=url, refresh=refresh)


async def capture_html_page_thumbnail(
    *,
    agent_id: int | HumanActor,
    reference: str,
    content: bytes,
) -> tuple[bytes, str] | None:
    """Render authorized private HTML using the same capture in every surface."""
    return await _capture_thumbnail(agent_id=agent_id, reference=reference, content=content)


async def _capture_thumbnail(
    *,
    agent_id: int | HumanActor,
    reference: str,
    content: bytes | None = None,
    refresh: bool = False,
) -> tuple[bytes, str] | None:
    # Documents and Chat can request the same capture concurrently. Keep one
    # lock per active URI, without retaining an unbounded registry after use.
    lock = _capture_locks.setdefault(reference, asyncio.Lock())
    async with lock:
        cache_path = thumbnails.cache_path(reference)
        cached = await asyncio.to_thread(thumbnails.read, cache_path)
        if cached is not None and not refresh:
            return cached, "image/png"
        if content is None:
            result = await browser_executor.open(
                agent_id=agent_id,
                task_id=None,
                url=reference,
                output="screenshot",
                image_format="jpeg",
                max_width=runtime_settings.BROWSER_VIEWPORT_WIDTH,
                max_height=runtime_settings.BROWSER_VIEWPORT_HEIGHT,
            )
        else:
            result = await browser_executor.render_html(
                agent_id=agent_id,
                task_id=None,
                content=content,
                max_width=runtime_settings.BROWSER_VIEWPORT_WIDTH,
                max_height=runtime_settings.BROWSER_VIEWPORT_HEIGHT,
            )
        return await _store_thumbnail_result(
            agent_id=agent_id, result=result, cache_path=cache_path,
        )


async def _store_thumbnail_result(
    *,
    agent_id: int | HumanActor,
    result: ExecutorResult,
    cache_path: Path,
) -> tuple[bytes, str] | None:
    try:
        if not isinstance(result, BrowserScreenshot) or not result.parts:
            return None
        part = min(result.parts, key=lambda candidate: candidate.index)
        try:
            content = base64.b64decode(part.data, validate=True)
        except (binascii.Error, ValueError):
            return None
        content = await asyncio.to_thread(thumbnails.from_image, BytesIO(content))
        if content is None or len(content) > thumbnails.MAX_BYTES:
            return None
        try:
            await asyncio.to_thread(thumbnails.write, cache_path, content)
            if 'description' in result.model_fields_set:
                metadata = BrowserPageMetadata(title=result.title, description=result.description, site_name=result.site_name)
                await asyncio.to_thread(thumbnails.write, cache_path.with_suffix('.json'), metadata.model_dump_json().encode())
        except OSError as exc:
            logger.warning(
                "Browser thumbnail cache write failed (error_type={})",
                type(exc).__name__,
            )
        return content, "image/png"
    finally:
        try:
            await browser_executor.close(
                agent_id=agent_id,
                task_id=None,
                session_id=result.session_id,
            )
        except BrowserExecutorError as exc:
            logger.warning(
                "Browser thumbnail session cleanup failed (code={})",
                exc.code,
            )


async def read_cached_thumbnail(
    *,
    reference: str,
) -> tuple[bytes, str] | None:
    """Read a generated PNG by its original URL or resource URI."""

    cache_path = thumbnails.cache_path(reference)
    content = await asyncio.to_thread(
        thumbnails.read,
        cache_path,
        thumbnails.MAX_BYTES,
    )
    return (content, "image/png") if content is not None else None


async def read_cached_page_metadata(*, reference: str) -> BrowserPageMetadata | None:
    """Read the title and description collected with the shared page capture."""
    content = await asyncio.to_thread(thumbnails.read, thumbnails.cache_path(reference).with_suffix('.json'), 16_384)
    if content is None:
        return None
    try:
        return BrowserPageMetadata.model_validate_json(content)
    except ValueError:
        return None


_thumbnail_tasks: dict[str, asyncio.Task[None]] = {}


async def _generate_public_page_thumbnail(
    *,
    agent_id: int | HumanActor,
    url: str,
) -> None:
    try:
        await capture_public_page_thumbnail(
            agent_id=agent_id,
            url=url,
        )
    except BrowserExecutorError as exc:
        logger.debug("Browser thumbnail generation failed (code={})", exc.code)
    except Exception as exc:
        logger.warning(
            "Browser thumbnail generation failed (error_type={})",
            type(exc).__name__,
        )


def schedule_public_page_thumbnail(
    *,
    agent_id: int | HumanActor,
    url: str,
) -> None:
    """Deduplicate one thumbnail capture without delaying the caller."""

    if url in _thumbnail_tasks:
        return
    task = asyncio.create_task(
        _generate_public_page_thumbnail(
            agent_id=agent_id,
            url=url,
        ),
        name="browser-page-thumbnail",
        context=Context(),
    )
    _thumbnail_tasks[url] = task

    def forget(completed: asyncio.Task[None]) -> None:
        if _thumbnail_tasks.get(url) is completed:
            _thumbnail_tasks.pop(url, None)

    task.add_done_callback(forget)
