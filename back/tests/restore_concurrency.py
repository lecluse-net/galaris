"""Exercise the documented quiescence boundary with independent durable writers."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

import main  # noqa: F401 - load the same model registry as the application
from core.database import get_db_session
from core.settings import settings
from app.memory import document_service
from app.memory.models import MemoryItem
from app.memory.storage import get_storage

ROOT = Path('/restore')


async def write_worker(worker: int, agent_id: int) -> None:
    index = 0
    while not (ROOT / 'quiesce').exists():
        content = f'<p>concurrent durable document worker={worker} sequence={index}</p>'
        async with get_db_session():
            document = await document_service.create_document(
                owner_agent_id=agent_id, title=f'Restore concurrent {worker}/{index}',
                content=content, task_id=None,
            )
            identifier = str(document.id)
        # Immutable file/DB pair: quiescence must await the whole operation,
        # including the filesystem receipt after the database commit.
        await asyncio.sleep(0.01)
        (ROOT / 'concurrent' / f'{worker}-{index}.json').write_text(json.dumps({
            'id': identifier, 'sha256': hashlib.sha256(content.encode()).hexdigest(),
        }))
        index += 1
        if index == 10:
            (ROOT / f'writer-{worker}-ready').touch()
        await asyncio.sleep(0.01)


async def run(mode: str) -> None:
    if settings.APP_ENV != 'test' or settings.POSTGRES_HOST != 'db-test':
        raise RuntimeError('Concurrent restore probes require the isolated test database')
    if mode == 'write':
        (ROOT / 'concurrent').mkdir(exist_ok=True)
        agent_id = json.loads((ROOT / 'application.json').read_text())['agent_id']
        await asyncio.wait_for(asyncio.gather(*(write_worker(i, agent_id) for i in range(2))), 60)
        count = len(list((ROOT / 'concurrent').glob('*.json')))
        (ROOT / 'quiesced-count').write_text(str(count))
        print(f'QUIESCED_WRITES={count}')
    elif mode == 'verify':
        count = 0
        for path in sorted((ROOT / 'concurrent').glob('*.json')):
            receipt = json.loads(path.read_text())
            async with get_db_session() as db:
                item = await db.get(MemoryItem, UUID(receipt['id']))
                assert item is not None, 'A committed file has no restored database object'
                content = await get_storage(item.provider_code).read(item.resource_id)
                assert hashlib.sha256(content).hexdigest() == receipt['sha256']
            count += 1
        assert count == int((ROOT / 'quiesced-count').read_text()) and count >= 20
        print(f'RESTORED_WRITES={count}; LOST_COMMITTED_WRITES=0')
    else:
        raise ValueError('Expected write or verify')


if __name__ == '__main__':
    asyncio.run(run(sys.argv[1]))
