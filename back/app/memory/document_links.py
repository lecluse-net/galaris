"""Persist static link cards, with thumbnails owned by the document."""

from html import escape
from io import BytesIO
from uuid import UUID

from PIL import Image

from core.user import HumanActor

from core.preview import preview_web_link
from core.util import normalize_html

from . import document_attachment_service, service
from .schemas import DocumentLinkCard


async def create_link_card(document_id: UUID, url: str, *, actor_agent_id: int | HumanActor) -> DocumentLinkCard:
    item, _, access, _, _ = await service.get_item(document_id, agent_id=actor_agent_id)
    if not access.can_write or item.content_profile != "document":
        raise service.MemoryPermissionError("Document edit access required")
    metadata = await preview_web_link(url, agent_id=actor_agent_id)
    attachment = None
    if metadata.image:
        try:
            with Image.open(BytesIO(metadata.image)) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("Thumbnail exceeds pixel limit")
                image.thumbnail((640, 360))
                output = BytesIO()
                image.convert("RGB").save(output, format="JPEG", quality=85)
            attachment = await document_attachment_service.add_document_attachment_bytes(
                document_id, actor_agent_id=actor_agent_id, name="link-preview.jpg",
                media_type="image/jpeg", content=output.getvalue(),
            )
        except (OSError, ValueError, TimeoutError):
            # A page without a usable thumbnail remains a useful text card.
            pass
    href = escape(url, quote=True)
    image_html = (
        f'<figure class="image"><a href="{href}"><img src="document://{document_id}/attachments/{attachment.id}" '
        f'alt="{escape(metadata.title, quote=True)}" width="320"></a></figure>'
        if attachment else ""
    )
    html = (
        '<blockquote class="galaris-link-card">' + image_html
        + f'<p><a href="{href}"><strong>{escape(metadata.title)}</strong></a></p>'
        + (f'<p>{escape(metadata.description)}</p>' if metadata.description else "")
        + f'<p><a href="{href}">{escape(metadata.site_name)}</a></p></blockquote>'
    )
    return DocumentLinkCard(html=normalize_html(html, profile="document"), attachment=attachment)
