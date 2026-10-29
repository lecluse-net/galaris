"""Synthetic old persisted resources; never an application creation entry point."""

from hashlib import sha256
from uuid import uuid4

from app.document import Document, DocumentRevision
from core.database import get_db
from core.storage import prepare_content


async def legacy_dataset(*, owner_agent_id: int, title: str, content: str,
    keywords: list[str] | None = None, task_id: object = None, document_type: str = "dataset") -> Document:
    pointer, inline = await prepare_content(content.encode())
    row = Document(id=uuid4(), owner_agent_id=owner_agent_id, title=title,
        provider_code="native", resource_id=pointer, content=inline,
        document_type="dataset", content_type="text", media_type="application/json",
        content_hash=sha256(content.encode()).hexdigest(), size_bytes=len(content.encode()),
        keywords=keywords or [], metadata_={})
    get_db().add(row)
    await get_db().flush()
    get_db().add(DocumentRevision(document_id=row.id, revision=1, provider_code="native",
        resource_id=pointer, content=inline, content_type="text", media_type="application/json",
        content_hash=row.content_hash, title=title, metadata_={},
        author_agent_id=owner_agent_id, document_content_version=True))
    await get_db().commit()
    from app.dataset import register_dataset
    from app.dataset.migration import adopt_legacy
    register_dataset()
    row = await adopt_legacy(row.id)
    await get_db().commit()
    return row
