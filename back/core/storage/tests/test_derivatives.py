"""Derived text/vectors are disposable and can never outlive a retired source."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.storage import (StoredFileDerivative, file_path, register_file, retire_file_reference,
                          read_file_derivative, write_file_derivative)


@pytest.mark.asyncio
async def test_derivative_retirement_is_atomic_and_rollback_preserves_the_index(db):
    identity = uuid4()
    uri = f'chat://synthetic/{identity}'
    path = file_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'Synthetic original')
    record = await register_file(identity, name='Synthetic.txt', media_type='text/plain', alias=uri)
    digest = record.sha256
    key = 'a' * 64
    assert await write_file_derivative(identity, 'document-rag', key, {'chunks': ['Synthetic passage']}, source_sha256=digest)
    await db.commit()
    assert await read_file_derivative(identity, 'document-rag', key) == {'chunks': ['Synthetic passage']}
    assert await read_file_derivative(identity, 'document-rag', 'b' * 64) is None
    assert await retire_file_reference(uri) == [identity]
    assert await db.scalar(select(StoredFileDerivative.id)) is None
    await db.rollback()
    assert await read_file_derivative(identity, 'document-rag', key) is not None
    assert await retire_file_reference(uri) == [identity]
    await db.commit()
    assert await read_file_derivative(identity, 'document-rag', key) is None
    assert not await write_file_derivative(identity, 'document-rag', key, {'late': True}, source_sha256=digest)
    assert await db.scalar(select(StoredFileDerivative.id)) is None


@pytest.mark.asyncio
async def test_late_derivative_publication_waits_for_retirement_and_cannot_recreate_data(committed_database):
    identity = uuid4()
    uri = f'chat://synthetic/{identity}'
    path = file_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'Synthetic original')
    async with committed_database() as db:
        record = await register_file(identity, name='Synthetic.txt', media_type='text/plain', alias=uri, session=db)
        digest = record.sha256
        await db.commit()
    from core.database.database import db_session_ctx
    entered = asyncio.Event()

    async def publish():
        async with committed_database() as db:
            token = db_session_ctx.set(db)
            try:
                entered.set()
                saved = await write_file_derivative(identity, 'document-rag', 'a' * 64,
                                                    {'late': True}, source_sha256=digest)
                await db.commit()
                return saved
            finally:
                db_session_ctx.reset(token)

    async with committed_database() as deleting:
        assert await retire_file_reference(uri, session=deleting) == [identity]
        pending = asyncio.create_task(publish())
        try:
            await entered.wait()
            await deleting.commit()
            assert await asyncio.wait_for(pending, 5) is False
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    async with committed_database() as db:
        assert await db.scalar(select(StoredFileDerivative.id)) is None
