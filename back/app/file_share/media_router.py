"""Authenticated progressive playback without a full-file staging step."""

from collections.abc import AsyncIterator
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from core.authorize import authorize, independent_auth
from core.settings import settings
from core.util import complete_await
from . import resource_service
from .browser import browser_context
from .browser_router import browser_access
from .media_access import COOKIE_NAME, MEDIA_SECONDS, issue_media_cookie, media_identity
from .browser_policy import BrowserResourceAssertion, BROWSER_PRIVILEGES

router = APIRouter()


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    if value is None:
        return 0, size
    match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", value)
    if not match or not any(match.groups()) or size == 0:
        raise HTTPException(416, "Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    start = int(first) if first else max(0, size - int(last))
    end = min(int(last), size - 1) if first and last else size - 1
    if start >= size or start > end or (not first and int(last) == 0):
        raise HTTPException(416, "Unsatisfiable byte range", headers={"Content-Range": f"bytes */{size}"})
    return start, end - start + 1


@router.post("/media")
@authorize(privileges=list(BROWSER_PRIVILEGES), assertion=BrowserResourceAssertion)
async def prepare_media(response: Response, agent_id: int, uri: str = Query(max_length=4096),
                        management: bool = False) -> dict[str, str | None]:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        info = await resource_service.resource_info(ctx, uri)
        if info.is_collection or not info.media_type.startswith("video/") or "read" not in info.capabilities:
            raise HTTPException(422, "Select a readable video")
        if info.size is None or not await resource_service.resource_supports_byte_ranges(ctx, uri):
            return {"url": None}
        identifier = uuid4()
        path = f"/api/file-share/browser/media/{identifier}"
        cookie = await issue_media_cookie(identifier, agent_id, info.uri, management)
        response.set_cookie(COOKIE_NAME, cookie, max_age=MEDIA_SECONDS, path=path,
            httponly=True, secure=settings.APP_HOST.lower().startswith("https://"), samesite="strict")
        response.headers["Cache-Control"] = "private, no-store"
        return {"url": path}


@router.api_route("/media/{identifier}", methods=["GET", "HEAD"])
@independent_auth(reason="Resource-scoped HttpOnly media cookie; live session, role, agent and provider ACL checks on every range")
async def read_media(identifier: UUID, request: Request) -> Response:
    async with media_identity(identifier, request.cookies.get(COOKIE_NAME)) as grant, browser_access(grant.agent_id):
        manager = browser_context(grant.agent_id, management=grant.management)
        ctx = await manager.__aenter__()
        chunks = None
        try:
            info = await resource_service.resource_info(ctx, grant.uri)
            if info.is_collection or info.size is None or not info.media_type.startswith("video/") or "read" not in info.capabilities:
                raise HTTPException(404, "Media unavailable")
            selected = request.headers.get("range")
            # If-Range uses the full representation when the version no longer matches.
            if request.headers.get("if-range") and request.headers["if-range"] != info.etag:
                selected = None
            offset, length = byte_range(selected, info.size)
            headers = {"Accept-Ranges": "bytes", "Content-Length": str(length),
                "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no"}
            if info.etag:
                headers["ETag"] = info.etag
            status = 206 if selected else 200
            if selected:
                headers["Content-Range"] = f"bytes {offset}-{offset + length - 1}/{info.size}"
            if request.method == "HEAD" or not length:
                await manager.__aexit__(None, None, None)
                return Response(status_code=status, media_type=info.media_type, headers=headers)
            chunks = resource_service.resource_byte_range(ctx, grant.uri, offset=offset, length=length)
            first = await anext(chunks)
        except BaseException:
            if chunks is not None:
                await chunks.aclose()
            await manager.__aexit__(None, None, None)
            raise

    closed = False

    async def cleanup() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            await chunks.aclose()
        finally:
            await manager.__aexit__(None, None, None)

    async def body() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in chunks:
                yield chunk
        finally:
            await complete_await(cleanup())

    return StreamingResponse(body(), status_code=status, media_type=info.media_type, headers=headers,
        background=BackgroundTask(cleanup))


@router.delete("/media/{identifier}", status_code=204)
@authorize(privileges="user")
async def release_media(identifier: UUID) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path=f"/api/file-share/browser/media/{identifier}")
    return response
