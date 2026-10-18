"""Authenticated, agent-scoped HTTP projection of the file-share facade."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import httpx

from app.agent import current_management_scope, get_agent_record
from app.memory import MemoryNotFoundError, MemoryPermissionError
from core.authorize import Privileges, authorize
from core.util import source_code_response_headers
from .browser import browser_content, browser_context, browser_thumbnail
from .resource_contracts import ResourceDescriptor, ResourceListing, ResourceSchemeDescription, ResourceSearchResult
from .resource_service import list_schemes, resource_info, resource_list, resource_search

router = APIRouter(prefix="/browser")


@asynccontextmanager
async def browser_access(agent_id: int) -> AsyncGenerator[None]:
    if not (await current_management_scope()).allows(agent_id) or await get_agent_record(agent_id) is None:
        raise HTTPException(404, "Agent not found")
    try:
        async with asyncio.timeout(120):
            yield
    except (PermissionError, FileNotFoundError, MemoryNotFoundError, MemoryPermissionError) as exc:
        raise HTTPException(404, "Resource unavailable") from exc
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(422, "Unsupported resource operation or invalid reference") from exc
    except TimeoutError as exc:
        raise HTTPException(504, "Resource provider timed out") from exc
    except (OSError, httpx.HTTPError) as exc:
        raise HTTPException(502, "Resource provider unavailable") from exc


@router.get("/schemes", response_model=list[ResourceSchemeDescription])
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def schemes(agent_id: int) -> list[ResourceSchemeDescription]:
    async with browser_access(agent_id), browser_context(agent_id) as ctx:
        return await list_schemes(ctx)


@router.get("/entries", response_model=ResourceListing)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def entries(agent_id: int, uri: str = Query(max_length=4096),
    cursor: str | None = Query(default=None, max_length=8192),
    limit: int = Query(default=50, ge=1, le=500), management: bool = False) -> ResourceListing:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        return await resource_list(ctx, uri, max_entries=limit, cursor=cursor)


@router.get("/search", response_model=ResourceSearchResult)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def search(agent_id: int, uri: str = Query(max_length=4096),
    query: str = Query(min_length=1, max_length=500),
    cursor: str | None = Query(default=None, max_length=8192), management: bool = False) -> ResourceSearchResult:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        return await resource_search(ctx, uri, query, mode="name", recursive=True, max_results=50, cursor=cursor)


@router.get("/info", response_model=ResourceDescriptor)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def info(agent_id: int, uri: str = Query(max_length=4096), management: bool = False) -> ResourceDescriptor:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        return await resource_info(ctx, uri)


@router.get("/thumbnail", response_class=Response)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def thumbnail(agent_id: int, uri: str = Query(max_length=4096), management: bool = False) -> Response:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        image = await browser_thumbnail(ctx, uri)
        if image is None:
            raise HTTPException(404, "Thumbnail unavailable")
        return Response(image, media_type="image/webp", headers={"Cache-Control": "private, no-store"})


@router.get("/content", response_class=FileResponse)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def content(agent_id: int, uri: str = Query(max_length=4096), preview: bool = True, management: bool = False) -> FileResponse:
    async with browser_access(agent_id), browser_context(agent_id, management=management) as ctx:
        manager = browser_content(ctx, uri, preview=preview)
        source = await manager.__aenter__()
        try:
            return FileResponse(source.path, filename=source.name, media_type=source.media_type,
                background=BackgroundTask(manager.__aexit__, None, None, None),
                headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                    **source_code_response_headers(source.name, source.media_type)})
        except BaseException:
            await manager.__aexit__(None, None, None)
            raise
