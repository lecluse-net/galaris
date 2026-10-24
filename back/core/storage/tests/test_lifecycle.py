from uuid import uuid4
import asyncio

import pytest
from sqlalchemy import event, select, text

from core.storage import FileAlias, StoredFile, file_path, register_file, retire_file_references, purge_retired_file
from core.storage.lifecycle import resume_file_purges
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [10, 100, 1001])
async def test_bulk_reference_retirement_bounds_reads_and_preserves_shared_files(db, count):
    prefix = f"document://{uuid4()}/attachments/"
    identifiers = [uuid4() for _ in range(count)]
    for identifier in identifiers:
        path = file_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Synthetic immutable file")
        await register_file(identifier, name="Synthetic.txt", media_type="text/plain", alias=f"{prefix}{identifier}")
    shared = identifiers[0]
    await register_file(shared, name="Synthetic.txt", media_type="text/plain", alias=f"chat://synthetic/{shared}")
    await db.commit()
    db.expunge_all()
    async with measured_reads(db, f"retire-references-{count}") as reads:
        retired = await retire_file_references(prefix)
    assert retired == sorted(set(identifiers) - {shared})
    assert len(reads) <= (4 if count <= 100 else 10), "Retiring more references must not add per-file lookups"
    assert all(file_path(identifier).read_bytes() == b"Synthetic immutable file" for identifier in identifiers)
    assert await db.get(StoredFile, shared) is not None
    await db.rollback()
    assert set(await db.scalars(select(FileAlias.file_id).where(FileAlias.uri.startswith(prefix)))) == set(identifiers)
    assert len(list(await db.scalars(select(StoredFile).where(StoredFile.id.in_(identifiers))))) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_retirement", [False, True])
async def test_registration_waits_for_retirement_and_obeys_its_commit(committed_database, commit_retirement):
    identifier = uuid4()
    prefix = f"document://{uuid4()}/attachments/"
    path = file_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic concurrent file")
    async with committed_database() as setup:
        await register_file(identifier, name="Concurrent.txt", media_type="text/plain",
                            alias=f"{prefix}{identifier}", session=setup)
        await setup.commit()
    attempted = asyncio.Event()
    writer_pid = None

    async def add_alias():
        nonlocal writer_pid
        async with committed_database() as writer:
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            connection = await writer.connection()
            def capture(_connection, _cursor, _statement, _parameters, _context, _many):
                attempted.set()
            event.listen(connection.sync_connection, "before_cursor_execute", capture)
            try:
                await register_file(identifier, name="Concurrent.txt", media_type="text/plain",
                                    alias=f"chat://concurrent/{identifier}", session=writer)
                await writer.commit()
            finally:
                event.remove(connection.sync_connection, "before_cursor_execute", capture)

    async with committed_database() as retiring:
        assert await retire_file_references(prefix, session=retiring) == [identifier]
        pending = asyncio.create_task(add_alias())
        try:
            async with asyncio.timeout(5):
                await attempted.wait()
                async with committed_database() as observer:
                    while not await observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks "
                        "WHERE pid = :pid AND NOT granted)"), {"pid": writer_pid}):
                        await asyncio.sleep(0)
            assert not pending.done()
            if commit_retirement:
                await retiring.commit()
                with pytest.raises(ValueError, match="identity conflicts"):
                    await pending
            else:
                await retiring.rollback()
                await pending
        finally:
            await retiring.rollback()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with committed_database() as reader:
        record = await reader.scalar(select(StoredFile).where(StoredFile.id == identifier)
                                     .execution_options(include_historized=True))
        assert (record.deleted_at is not None) is commit_retirement
        aliases = list(await reader.scalars(select(FileAlias.uri).where(FileAlias.file_id == identifier)))
        assert (f"chat://concurrent/{identifier}" in aliases) is not commit_retirement
        assert path.read_bytes() == b"Synthetic concurrent file"


@pytest.mark.asyncio
async def test_shared_references_and_rollback_keep_bytes_and_committed_retirement_forbids_resurrection(db):
    identifier = uuid4()
    path = file_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic shared immutable file")
    first = f"document://{uuid4()}/attachments/"
    second = f"chat://{uuid4()}/"
    await register_file(identifier, name="Shared.txt", media_type="text/plain", alias=f"{first}{identifier}")
    await register_file(identifier, name="Shared.txt", media_type="text/plain", alias=f"{second}{identifier}")
    await db.commit()
    await retire_file_references(first)
    await db.commit()
    assert not await purge_retired_file(identifier)
    assert path.read_bytes() == b"Synthetic shared immutable file"
    await retire_file_references(second)
    assert path.is_file(), "Retirement must never unlink before the domain transaction commits"
    await db.rollback()
    assert await db.scalar(select(FileAlias.id).where(FileAlias.uri == f"{second}{identifier}")) is not None
    assert await db.get(StoredFile, identifier) is not None
    await retire_file_references(second)
    await db.commit()
    with pytest.raises(ValueError, match="identity conflicts"):
        await register_file(identifier, name="Reused.txt", media_type="text/plain", alias=f"{first}{identifier}")
    assert await purge_retired_file(identifier)
    await db.commit()
    assert not path.exists()
    assert not await purge_retired_file(identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize("after_unlink", [False, True])
async def test_purge_recovers_after_domain_commit_and_interrupted_filesystem_cleanup(db, monkeypatch, after_unlink):
    from core.storage import lifecycle

    identifier = uuid4()
    path = file_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic retired file")
    prefix = f"document://{uuid4()}/attachments/"
    await register_file(identifier, name="Retired.txt", media_type="text/plain", alias=f"{prefix}{identifier}")
    await retire_file_references(prefix)
    await db.commit()
    sync = lifecycle.sync_directory

    def fail_sync(*args):
        raise OSError("Synthetic failure after unlink")

    if after_unlink:
        monkeypatch.setattr(lifecycle, "sync_directory", fail_sync)
        with pytest.raises(OSError, match="after unlink"):
            await purge_retired_file(identifier)
        await db.rollback()
        assert not path.exists()
        monkeypatch.setattr(lifecycle, "sync_directory", sync)
    # The same reconciler runs on startup, even if no schema delta remains.
    await resume_file_purges(db)
    await db.commit()
    assert not path.exists()
    record = await db.scalar(select(StoredFile).where(StoredFile.id == identifier)
        .execution_options(include_historized=True))
    assert record.deleted_at is not None and record.purged_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["agent-file://synthetic/", "archive-file://synthetic/"])
async def test_owner_and_archive_references_prevent_document_cleanup(db, reference):
    identifier = uuid4()
    path = file_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic reserved bytes")
    prefix = f"document://{uuid4()}/attachments/"
    for alias in (f"{prefix}{identifier}", f"{reference}{identifier}"):
        await register_file(identifier, name="Reserved.txt", media_type="text/plain", alias=alias)
    await retire_file_references(prefix)
    await db.commit()
    await resume_file_purges(db)
    assert path.read_bytes() == b"Synthetic reserved bytes"
    assert await db.get(StoredFile, identifier) is not None
