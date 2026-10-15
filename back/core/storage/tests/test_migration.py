from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from core.settings import settings
from core.storage import DiskFileDriver, FileAlias, StoredFile, file_key, file_path, fingerprint
from core.storage import migration
from core.storage.migration import LegacyFile


@pytest.fixture
def legacy_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(type(settings), "GALARIS_MEMORY_ROOT", str(tmp_path / "memory"))
    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path / "chat"))


def legacy(kind: str, content: bytes, *, identifier=None) -> LegacyFile:
    identifier = identifier or uuid4()
    alias = f"document://{uuid4()}/attachments/{identifier}" if kind == "document" else f"chat://{uuid4()}/{identifier}"
    source = LegacyFile(kind, str(identifier), "Synthetic report.txt", "text/plain", (alias,))
    source.source.parent.mkdir(parents=True, exist_ok=True)
    source.source.write_bytes(content)
    return source


@pytest.mark.asyncio
async def test_verified_move_keeps_sources_until_registry_commit_and_resumes_cleanup(db, legacy_roots):
    sources = [legacy("document", b"document payload"), legacy("chat", b"chat payload")]
    originals = {source.uuid: fingerprint(source.source) for source in sources}
    assert not await migration.legacy_files_verified(db, sources)

    await migration.transfer_legacy_files(db, sources)
    await db.commit()
    assert all(source.source.exists() for source in sources)
    assert await migration.legacy_files_verified(db, sources)
    # Simulate interruption after the first unlink, then resume the whole action.
    sources[0].source.unlink()
    await migration.cleanup_legacy_files(db, sources)
    await migration.cleanup_legacy_files(db, sources)

    for source in sources:
        assert not source.source.exists()
        record = await db.get(StoredFile, source.uuid)
        assert record is not None
        assert fingerprint(file_path(record.id)) == originals[source.uuid]
        assert record.name == source.name
        assert await db.scalar(select(FileAlias.file_id).where(FileAlias.uri == source.aliases[0])) == record.id
    assert migration.manifest_path().is_file()


@pytest.mark.asyncio
async def test_crash_after_publish_before_database_registration_can_resume(db, legacy_roots, monkeypatch):
    source = legacy("chat", b"durable payload")
    register = migration.register_file

    async def crash(*args, **kwargs):
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(migration, "register_file", crash)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        await migration.transfer_legacy_files(db, [source])
    await db.rollback()
    assert source.source.exists()
    assert file_path(UUID(source.uuid)).read_bytes() == b"durable payload"
    monkeypatch.setattr(migration, "register_file", register)
    await migration.transfer_legacy_files(db, [source])
    await db.commit()
    await migration.cleanup_legacy_files(db, [source])
    assert not source.source.exists()


@pytest.mark.asyncio
async def test_missing_source_blocks_all_transfers(db, legacy_roots):
    sources = [legacy("document", b"preserved"), legacy("chat", b"missing")]
    sources[1].source.unlink()
    with pytest.raises(FileNotFoundError):
        await migration.transfer_legacy_files(db, sources)
    assert sources[0].source.read_bytes() == b"preserved"
    assert not migration.manifest_path().exists()
    assert not list(Path(settings.GALARIS_FILE_ROOT).glob("*/*/*"))


@pytest.mark.asyncio
async def test_uuid_collision_blocks_before_transfer(db, legacy_roots):
    identifier = uuid4()
    sources = [legacy("chat", b"one", identifier=identifier), legacy("document", b"two", identifier=identifier)]
    with pytest.raises(ValueError, match="collision"):
        await migration.transfer_legacy_files(db, sources)
    assert all(source.source.exists() for source in sources)
    assert not file_path(identifier).exists()


@pytest.mark.asyncio
async def test_corrupt_destination_prevents_any_cleanup(db, legacy_roots):
    from uuid import UUID

    sources = [legacy("chat", b"one"), legacy("document", b"two")]
    await migration.transfer_legacy_files(db, sources)
    await db.commit()
    file_path(UUID(sources[1].uuid)).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        await migration.cleanup_legacy_files(db, sources)
    assert all(source.source.exists() for source in sources)


def test_driver_refuses_overwrite_and_path_escapes(tmp_path):
    driver = DiskFileDriver(tmp_path / "target")
    identifier = uuid4()
    source = tmp_path / "source"
    source.write_bytes(b"first")
    size, digest = fingerprint(source)
    destination = driver.publish(source, file_key(identifier), size=size, sha256=digest)
    source.write_bytes(b"other")
    size, digest = fingerprint(source)
    with pytest.raises(ValueError, match="conflicts"):
        driver.publish(source, file_key(identifier), size=size, sha256=digest)
    assert destination.read_bytes() == b"first"
    with pytest.raises(ValueError):
        driver.path(f"../../{identifier}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (driver.root / "aa").symlink_to(outside, target_is_directory=True)
    escaped = UUID("aa112233-4455-4677-8899-aabbccddeeff")
    with pytest.raises(ValueError):
        driver.path(file_key(escaped))


@pytest.mark.asyncio
async def test_missing_or_replaced_volume_never_becomes_an_empty_fallback(db, tmp_path, monkeypatch):
    from core.storage.identity import ensure_disk_identity

    await ensure_disk_identity(db)
    await db.commit()
    marker = Path(settings.GALARIS_FILE_ROOT) / ".store-uuid"
    identity = marker.read_text()
    marker.unlink()
    with pytest.raises(ValueError, match="missing or replaced"):
        await ensure_disk_identity(db)
    assert not marker.exists()
    marker.write_text(str(uuid4()))
    with pytest.raises(ValueError, match="missing or replaced"):
        await ensure_disk_identity(db)
    marker.write_text(identity)
    await ensure_disk_identity(db)
