from uuid import uuid4

import pytest
from sqlalchemy import select

from core.storage import FileAlias, StoredFile, file_path, register_file, retire_file_references, purge_retired_file
from core.storage.lifecycle import resume_file_purges


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
