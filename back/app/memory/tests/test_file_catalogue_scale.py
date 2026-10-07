"""Synthetic scale qualification of real private catalogue search and observation."""

import hashlib
import json
from time import perf_counter
from math import ceil
from statistics import median
from uuid import uuid4
from pathlib import Path
import pytest
from sqlalchemy import insert, event, text

from app.file_share import resource_service
from app.file_share import catalogue, resource_observation
from app.file_share.models import FileCatalogEntry
from app.memory import service
from app.memory.models import MemoryItem, MemoryURL
from app.memory.schemas import MemorySearchRequest
from app.memory.storage import get_storage
from .test_file_catalogue import console_catalogue as console_catalogue


def latencies(samples):
    ordered = sorted(samples)
    return {'p50_ms': round(median(ordered) * 1000, 2),
            'p95_ms': round(ordered[ceil(len(ordered) * .95) - 1] * 1000, 2)}


@pytest.mark.asyncio
async def test_private_catalogue_search_at_1000_10000_100000_entries(console_catalogue, db):
    ctx, transport, connection, peer = console_catalogue
    scope = await catalogue.observation_scope(ctx, 'console://')
    assert scope is not None
    body = b'<p>Synthetic catalogue fixture.</p>'
    blob = await get_storage('native').create(body)
    previous = 0
    results = []
    for total in (1000, 10000, 100000):
        for offset in range(previous, total, 500):
            memories, resources, urls = [], [], []
            for index in range(offset, min(offset + 500, total)):
                item_id, identity, url_id = uuid4(), uuid4(), uuid4()
                uri = f'console://synthetic-{index}.txt'
                title = f'Synthetic catalogue entry {index}'
                if index == total - 1:
                    title = f'Syntheticneedle{total}'
                    await transport.file_write_text(f'synthetic-{index}.txt', 'Synthetic fixture', overwrite=False)
                memories.append(dict(id=item_id, owner_agent_id=ctx.agent_id, title=title,
                    resource_id=blob, provider_code='native', node_kind='file',
                    content_type='text', media_type='text/html', content_profile_version=1,
                    source_managed=True, deletion_protected=True, managed_source_kind='file_catalogue',
                    managed_source_ref=str(identity), content_hash=hashlib.sha256(body).hexdigest(),
                    size_bytes=len(body), search_text=title,
                    metadata={'catalogue_ref': str(identity), 'catalogue_editable': True}))
                urls.append(dict(id=url_id, memory_node_id=item_id, url=uri))
                resources.append(dict(id=identity, agent_id=ctx.agent_id, connection_id=connection.id,
                    binding_stamp=scope.stamp, runtime=scope.runtime, uri=uri, uri_key=hashlib.sha256(uri.encode()).hexdigest(),
                    descriptor={'uri': uri, 'name': title, 'is_collection': False},
                    memory_url_id=url_id, operation_started_at=scope.started_at, last_seen_at=scope.started_at))
            await db.execute(insert(MemoryItem.__table__), memories)
            await db.execute(insert(MemoryURL.__table__), urls)
            await db.execute(insert(FileCatalogEntry.__table__), resources)
        await db.commit()
        await db.execute(text('ANALYZE memory_items'))
        await db.execute(text('ANALYZE file_catalog_entries'))
        samples = []
        for _ in range(10):
            start = perf_counter()
            result = await service.search_items(MemorySearchRequest(agent_id=ctx.agent_id, query=f'Syntheticneedle{total}'))
            samples.append(perf_counter() - start)
            assert len(result.hits) == 1
        assert not (await service.search_items(MemorySearchRequest(agent_id=peer.id, query=f'Syntheticneedle{total}'))).hits
        results.append({'entries': total, 'search_with_synthetic_source_check': latencies(samples)})
        previous = total
    observations = {}
    statements = []
    sql_connection = await db.connection()
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if 'SELECT' in statement.upper():
            statements.append((statement, parameters))
    event.listen(sql_connection.sync_connection.engine, 'before_cursor_execute', capture)
    try:
        await service.search_items(MemorySearchRequest(agent_id=ctx.agent_id, query='Syntheticneedle100000'))
    finally:
        event.remove(sql_connection.sync_connection.engine, 'before_cursor_execute', capture)
    plans = [(await sql_connection.exec_driver_sql(
        'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement, parameters,
    )).scalar_one() for statement, parameters in statements if 'memory_items' in statement]
    destination = Path(__file__).resolve().parents[4] / 'artifacts/file-catalogue-search-plans.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plans, indent=2))
    def nodes(plan):
        yield plan
        for child in plan.get('Plans', []):
            yield from nodes(child)
    # Binding validation must scale with connections, not files. This checks
    # executed PostgreSQL work rather than freezing an SQL spelling or index.
    for explanation in plans:
        for plan in explanation:
            for node in nodes(plan['Plan']):
                if node.get('Relation Name') == 'connection_params':
                    assert node['Actual Loops'] <= 10
    for enabled in (False, True):
        samples = []
        for index in range(20):
            start = perf_counter()
            if enabled:
                await resource_service.resource_write_text(ctx, f'console://observed-{index}.txt', 'Synthetic observation')
            else:
                with resource_observation.suspend_observations():
                    await resource_service.resource_write_text(ctx, f'console://baseline-{index}.txt', 'Synthetic observation')
            samples.append(perf_counter() - start)
        observations['indexed' if enabled else 'baseline'] = latencies(samples)
    indexes = {name: await db.scalar(text('SELECT pg_relation_size(:name)').bindparams(name=name))
               for name in ('ix_memory_items_search_vector_gin', 'ix_memory_items_title_trgm',
                            'ix_memory_items_search_text_trgm', 'ix_file_catalog_tombstone_binding')}
    print('FILE_INDEX_QUALIFICATION=' + json.dumps({'search': results, 'observation': observations,
                                                 'index_bytes': indexes}))
