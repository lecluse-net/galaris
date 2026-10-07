"""Synthetic file-provider boundary for assembled Memory preview journeys."""

from dataclasses import replace
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.connection import Connection
from app.file_share import FileCatalogueEnrichmentPort, resource_service
from app.file_share.models import FileCatalogEntry
from app.file_share.resource_contracts import ResourceContext
from app.file_share.tests.local_file_transport import TemporaryFileTransport
from app.tools import ToolModel
from app.memory import service, document_attachment_service, detect_memory_findings, maintenance
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.database import get_db


class BrowserFileTransport(TemporaryFileTransport):
    async def resource_info(self, path, *, include_sha256=False):
        if not path:
            return replace(self._entry(self.root_path(), include_sha256=include_sha256), path='')
        return await self.file_info(path, include_sha256=include_sha256)

    async def resource_list(self, path, *, recursive=False, limit=100):
        return await self.file_list(path, recursive=recursive, limit=limit)


async def seed_catalogue(agent_id: int, root: Path) -> dict[str, object]:
    db = get_db()
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'console'))
    assert tool is not None
    db.add(Connection(agent_id=agent_id, tool_id=tool.id, active=True))
    await db.commit()
    transport = BrowserFileTransport(root / str(agent_id))
    Image.new('RGB', (160, 100), 'turquoise').save(transport.resolve_path('first/synthetic.png'))
    transport.resolve_path('second/synthetic-copy.png').write_bytes(transport.resolve_path('first/synthetic.png').read_bytes())
    ctx = ResourceContext(agent_id=agent_id, runtime='internal')
    await resource_service.resource_list(ctx, 'console://first/')
    await resource_service.resource_list(ctx, 'console://second/')
    port = FileCatalogueEnrichmentPort()
    for source in await port.fingerprints():
        if source['agent_id'] != agent_id:
            continue
        digest = await port.fingerprint(source)
        assert digest is not None
        await port.identify(source['identity'], source['version'], digest)
    await db.commit()
    entries = list(await db.scalars(select(FileCatalogEntry).where(
        FileCatalogEntry.agent_id == agent_id, FileCatalogEntry.file_sha256.is_not(None),
    ).execution_options(populate_existing=True)))
    assert len(entries) == 2 and entries[0].memory_node_id is not None
    # Fingerprinting records identity; resolve the synthetic duplicate separately.
    for finding_id in await detect_memory_findings(entries[0].memory_node_id, manual=True):
        await maintenance.apply_finding(finding_id, canonical_item_id=None)
    for entry in entries:
        await db.refresh(entry)
    assert entries[0].memory_node_id == entries[1].memory_node_id
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=agent_id, title='Synthetic 3D document',
        node_kind='document', media_type='text/html', payload=MemoryPayload(text='<p>Synthetic geometry</p>'),
    ))
    attachment = await document_attachment_service.add_document_attachment_bytes(
        document.id, actor_agent_id=agent_id, name='triangle.obj', media_type='model/obj',
        content=b'v -1 -1 0\nv 1 -1 0\nv 0 1 0\nf 1 2 3\n',
    )
    return {'file_item_id': str(entries[0].memory_node_id), 'file_uris': [entry.uri for entry in entries],
            'model_document_id': str(document.id), 'model_attachment_id': str(attachment.id)}
