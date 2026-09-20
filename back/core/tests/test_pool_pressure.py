"""Exercise real pool queueing, timeout and cancellation without a production DB."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import TimeoutError as PoolTimeout
from core import settings
from core.database import pool


@pytest.mark.asyncio
async def test_pool_records_contention_timeout_and_cancellation(committed_database, monkeypatch):
    samples = []
    monkeypatch.setattr(pool, "_acquisition", SimpleNamespace(record=lambda seconds, labels: samples.append((seconds, labels["outcome"]))))
    engine = create_async_engine(settings.DATABASE_URL, poolclass=pool.ObservedAsyncPool,
                                 pool_size=1, max_overflow=0, pool_timeout=0.1)
    try:
        async with engine.connect():
            with pytest.raises(PoolTimeout):
                async with engine.connect():
                    pytest.fail("the single connection is already reserved")
            async def acquire():
                async with engine.connect():
                    pass
            cancelled = asyncio.create_task(acquire())
            await asyncio.sleep(0.02)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            waiting = asyncio.create_task(acquire())
            await asyncio.sleep(0.02)
            assert not waiting.done()
        await asyncio.wait_for(waiting, 2)
        assert engine.pool.checkedout() == 0
        assert [outcome for _, outcome in samples] == ["acquired", "timeout", "error", "acquired"]
        assert samples[1][0] >= 0.09
        assert samples[-1][0] >= 0.015
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_storage_metrics_describe_tables_without_exporting_payloads(db, monkeypatch):
    from core.database import storage
    sizes, estimates = {}, {}
    monkeypatch.setattr(storage, "_bytes", SimpleNamespace(set=lambda value, labels: sizes.update({labels['table']: value})))
    monkeypatch.setattr(storage, "_rows", SimpleNamespace(set=lambda value, labels: estimates.update({labels['table']: value})))
    await storage.record_storage_metrics()
    assert sizes['process_runs'] >= 0 and sizes['user_refresh_sessions'] >= 0
    assert sizes.keys() == estimates.keys()
    assert all(value >= 0 for value in estimates.values())
