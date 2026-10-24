"""Persist link card text; thumbnails remain disposable shared previews."""

import asyncio
from html import escape
from io import BytesIO
from uuid import UUID

from core.user import HumanActor

from core.preview import preview_web_link, thumbnails
from core.util import normalize_html

from . import resource_service as service
from .schemas import DocumentLinkCard


async def create_link_card(document_id: UUID, url: str, *, actor_agent_id: int | HumanActor) -> DocumentLinkCard:
    item, access = await service.get_item_metadata(document_id, agent_id=actor_agent_id)
    if not access.can_write or item.content_profile != "document":
        raise service.DocumentPermissionError("Document edit access required")
    metadata = await preview_web_link(url, agent_id=actor_agent_id)
    await _cache_thumbnail(url, metadata.image)
    href = escape(url, quote=True)
    html = (
        '<blockquote class="galaris-link-card galaris-web-card">'
        + f'<p><a href="{href}"><strong>{escape(metadata.title)}</strong></a></p>'
        + (f'<p>{escape(metadata.description)}</p>' if metadata.description else "")
        + f'<p><a href="{href}">{escape(metadata.site_name)}</a></p></blockquote>'
    )
    return DocumentLinkCard(html=normalize_html(html, profile="document"))


async def _cache_thumbnail(url: str, image: bytes | None) -> bytes | None:
    if not image:
        return None
    content = await asyncio.to_thread(thumbnails.from_image, BytesIO(image))
    if content:
        try:
            await asyncio.to_thread(thumbnails.write, thumbnails.cache_path(url), content)
        except OSError:
            # A full/read-only cache must not prevent a useful card or preview.
            pass
    return content


async def link_thumbnail(url: str, *, actor: int | HumanActor) -> bytes | None:
    """Read or regenerate a public HTTPS preview, without creating a resource."""
    async with thumbnails.generation(url):
        cached = await asyncio.to_thread(thumbnails.read, thumbnails.cache_path(url))
        if cached:
            return cached
        metadata = await preview_web_link(url, agent_id=actor)
        return await _cache_thumbnail(url, metadata.image)
