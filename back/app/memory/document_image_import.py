"""Import a pasted public image into the document's attachment store."""

from io import BytesIO
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from core.preview import read_web_image
from core.user import HumanActor

from . import document_attachment_service, service
from .schemas import DocumentAttachmentPublic


async def import_document_image(
    document_id: UUID, url: str, *, actor: int | HumanActor,
) -> DocumentAttachmentPublic:
    item, _, access, _, _ = await service.get_item(document_id, agent_id=actor)
    if not access.can_write or item.content_profile != "document" or item.document_type != "html":
        raise service.MemoryPermissionError("Document edit access required")
    content = await read_web_image(url)
    try:
        with Image.open(BytesIO(content)) as image:
            extension, media_type = {
                "PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
                "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif"),
            }.get(image.format or "", ("", ""))
            if not extension:
                raise ValueError("Unsupported pasted image format")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The pasted resource is not a raster image") from exc
    # The attachment service rechecks edit rights, raster validity, dimensions
    # and storage quotas before publishing the original bytes.
    return await document_attachment_service.add_document_attachment_bytes(
        document_id, actor_agent_id=actor, name=f"pasted-image.{extension}",
        media_type=media_type, content=content,
    )
