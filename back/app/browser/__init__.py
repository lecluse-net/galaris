"""Isolated browser capability exposed through native Galaris MCP tools."""

from core.user import HumanActor

from .service import (
    BrowserExecutorError,
    BrowserOutput,
    browser_executor,
    capture_html_page_thumbnail,
    capture_public_page_thumbnail,
    read_cached_thumbnail,
    read_cached_page_metadata,
    resolve_default_output,
    schedule_public_page_thumbnail,
)

from dataclasses import replace
from app.file_share import document_web_preview
from core.preview import WebLinkPreview, register_web_preview_provider


async def _document_preview(url: str, *, agent_id: int | HumanActor) -> WebLinkPreview:
    """Adapt the shared Chat capture to the persisted document preview port."""
    metadata = await document_web_preview(url)
    if metadata.page_url is None:
        return metadata
    page_metadata = await read_cached_page_metadata(reference=metadata.page_url)
    try:
        if page_metadata is None and not metadata.description:
            # Enrich caches created before descriptions were collected, once.
            thumbnail = await capture_public_page_thumbnail(agent_id=agent_id, url=metadata.page_url, refresh=True)
        else:
            thumbnail = await capture_public_page_thumbnail(agent_id=agent_id, url=metadata.page_url)
    except (BrowserExecutorError, OSError, TimeoutError):
        thumbnail = None
    page_metadata = await read_cached_page_metadata(reference=metadata.page_url)
    return replace(
        metadata,
        image=thumbnail[0] if thumbnail else metadata.image,
        title=page_metadata.title or metadata.title if page_metadata else metadata.title,
        description=metadata.description or page_metadata.description if page_metadata else metadata.description,
        site_name=page_metadata.site_name or metadata.site_name if page_metadata else metadata.site_name,
    )


register_web_preview_provider(_document_preview)

__all__ = [
    "BrowserExecutorError",
    "BrowserOutput",
    "browser_executor",
    "capture_html_page_thumbnail",
    "capture_public_page_thumbnail",
    "read_cached_thumbnail",
    "read_cached_page_metadata",
    "resolve_default_output",
    "schedule_public_page_thumbnail",
]
