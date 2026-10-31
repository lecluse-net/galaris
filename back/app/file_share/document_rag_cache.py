"""Optional source-owned RAG projection; canonical resource ACLs remain authoritative."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select

from core.database import get_db
from core.storage import FileAlias, StoredFile, read_file_derivative, publish_file_derivative
from .resource_contracts import ResourceContext
from .resource_service import resource_info
from .resource_uri import parse_resource_uri

_NAMESPACE = 'document-rag'


@dataclass(frozen=True)
class DocumentResourceRagCache:
    ctx: ResourceContext
    uri: str
    file_id: UUID
    source_sha256: str

    async def load(self, fingerprint: str) -> dict[str, JsonValue] | None:
        await resource_info(self.ctx, self.uri)
        return await read_file_derivative(self.file_id, _NAMESPACE, fingerprint)

    async def save(self, fingerprint: str, payload: dict[str, JsonValue]) -> None:
        await resource_info(self.ctx, self.uri)
        # A disposable projection must never commit pending business changes in
        # its caller. Managed source registration precedes retrieval and is durable.
        await publish_file_derivative(self.file_id, _NAMESPACE, fingerprint, payload,
                                      source_sha256=self.source_sha256)


async def document_rag_cache(ctx: ResourceContext, uri: str, source_sha256: str | None = None) -> DocumentResourceRagCache | None:
    await resource_info(ctx, uri)
    reference = parse_resource_uri(uri)
    db = get_db()
    identifier = UUID(reference.locator) if reference.scheme == 'file' else await db.scalar(
        select(FileAlias.file_id).where(FileAlias.uri == str(reference)))
    if identifier is None:
        return None  # Remote/inline sources keep their index only for this request.
    record = await db.get(StoredFile, identifier)
    if record is None or (source_sha256 is not None and record.sha256 != source_sha256):
        raise FileNotFoundError('Document source changed or was deleted')
    return DocumentResourceRagCache(ctx, uri, identifier, record.sha256)
