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
    assert len(entries) == 2 and entries[0].memory_item_id == entries[1].memory_item_id
    return {'file_item_id': str(entries[0].memory_item_id), 'file_uris': [entry.uri for entry in entries]}
