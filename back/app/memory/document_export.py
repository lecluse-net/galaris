"""Export an authorized document snapshot without changing its saved revision."""

from uuid import UUID
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import quote

from core.user import HumanActor

from core.preview import render_html_pdf

from . import service
from .document_attachment_service import attachments_from_item, read_document_attachment


async def export_document_bundle(document_id: UUID, html: str, *, actor_agent_id: int | HumanActor) -> bytes:
    """Export a static snapshot and immutable attachments with portable local links."""
    item, _, _, _, _ = await service.get_item(document_id, agent_id=actor_agent_id)
    if item.document_type != "html" or item.content_profile != "document":
        raise ValueError("A document is required")
    if len(html.encode()) > 12_000_000:
        raise ValueError("The document snapshot exceeds the 12 MB limit")
    active_ids = {value.id for value in attachments_from_item(item)}
    attachments = [value for value in attachments_from_item(item, include_retained=True)
                   if value.id in active_ids or f"document://{document_id}/attachments/{value.id}" in html]
    total = len(html.encode()) + sum(value.size_bytes for value in attachments)
    if total > 64_000_000:
        raise ValueError("The document bundle exceeds the 64 MB limit")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for attachment in attachments:
            name = f"attachments/{attachment.id}-{Path(attachment.name.replace(chr(92), '/')).name}"
            _, content = await read_document_attachment(document_id, attachment.id, actor_agent_id=actor_agent_id)
            uri = f"document://{document_id}/attachments/{attachment.id}"
            html = html.replace(escape(uri, quote=True), escape(quote(name), quote=True))
            archive.writestr(name, content)
        archive.writestr("document.html", html)
    return output.getvalue()


async def export_document_pdf(
    document_id: UUID, html: str, *, managed_agent_ids: frozenset[int] | None, actor: int | HumanActor | None = None,
) -> bytes:
    if actor is not None:
        item, *_ = await service.get_item(document_id, agent_id=actor)
    else:
        item, readable, _writable = await service.managed_document_agent_ids(
            document_id, managed_agent_ids=managed_agent_ids,
        )
        if not readable:
            raise service.MemoryPermissionError("Document read access denied")
    if item.document_type != "html" or item.content_profile != "document":
        raise ValueError("PDF export requires a document content profile")
    return await render_html_pdf(html)
