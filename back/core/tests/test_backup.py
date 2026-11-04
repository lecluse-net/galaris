"""Synthetic archives and real PostgreSQL replacement, without application data."""

import io
import json
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from core import backup


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "restore", "swap", "after_commit", "cleanup"])
async def test_database_and_data_restore_preserves_excluded_files_and_recovers_failures(
    committed_database, tmp_path, monkeypatch, failure, capsys,
):
    database = committed_database.kw["bind"].url.database
    monkeypatch.setenv("POSTGRES_DB", database)
    data = tmp_path / "data"
    data.mkdir()
    (data / "files").mkdir()
    (data / "files" / "rsync-only.bin").write_bytes(b"separate file store")
    (data / "skills").mkdir()
    (data / "skills" / ".private").write_bytes(b"synthetic private skill")
    (data / "skills" / ".private").chmod(0o600)
    (data / "nested" / "files").mkdir(parents=True)
    (data / "nested" / "files" / "included").write_text("keep nested files directory")
    (data / "link").symlink_to("skills/.private")
    configuration = tmp_path / "installation.env"
    configuration.write_text("ENCRYPTION_MASTER_KEY=synthetic\n")
    archive = tmp_path / "backup.tar.gz"
    backup._sql("CREATE TABLE public.backup_probe (id integer PRIMARY KEY, content text)", database=database)
    backup._sql("INSERT INTO public.backup_probe VALUES (1, 'original')", database=database)
    backup.save(archive, data, configuration)
    assert archive.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive) as outer:
        manifest = json.load(outer.extractfile("manifest.json"))
        assert manifest["excluded"] == ["/data/files"]
        with tarfile.open(fileobj=outer.extractfile("data.tar")) as inner:
            assert not any(name == "files" or name.startswith("files/") for name in inner.getnames())
            assert "nested/files/included" in inner.getnames()
    backup._sql("UPDATE public.backup_probe SET content='current'", database=database)
    backup._sql("CREATE TABLE public.backup_later (id integer)", database=database)
    (data / "skills" / ".private").write_bytes(b"current skill")
    (data / "later").write_text("current only")
    (data / "files" / "rsync-only.bin").write_bytes(b"rsync tree stays current")
    pg = backup._pg
    sql = backup._sql

    def fail_restore(program, *arguments, **kwargs):
        if failure in {"restore", "cleanup"} and program == "pg_restore" and "--single-transaction" in arguments:
            raise backup.BackupError("Synthetic restore failure")
        return pg(program, *arguments, **kwargs)

    interrupted = False

    def fail_swap(statement, **kwargs):
        nonlocal interrupted
        if failure == "swap" and statement.startswith("BEGIN; ALTER DATABASE"):
            raise backup.BackupError("Synthetic database swap failure")
        if failure == "after_commit" and not interrupted and statement.startswith("BEGIN; ALTER DATABASE"):
            interrupted = True
            sql(statement, **kwargs)
            raise backup.BackupError("Synthetic connection failure after commit")
        if failure == "cleanup" and statement.startswith("DROP DATABASE"):
            raise backup.BackupError("Synthetic cleanup failure")
        return sql(statement, **kwargs)

    monkeypatch.setattr(backup, "_pg", fail_restore)
    monkeypatch.setattr(backup, "_sql", fail_swap)
    current_secrets = {"ENCRYPTION_MASTER_KEY": "synthetic-current-runtime-key"}
    if failure:
        with pytest.raises(backup.BackupError, match="Synthetic"):
            backup.restore(archive, data, configuration, recovery_secrets=current_secrets)
    else:
        recovery = backup.restore(archive, data, configuration, recovery_secrets=current_secrets)
        assert recovery.is_file()
    expected = "current" if failure else "original"
    assert backup._sql("SELECT content FROM public.backup_probe", database=database).strip() == expected
    assert (data / "skills" / ".private").read_bytes() == (b"current skill" if failure else b"synthetic private skill")
    assert (data / "later").exists() == bool(failure)
    assert (data / "files" / "rsync-only.bin").read_bytes() == b"rsync tree stays current"
    assert (data / "link").is_symlink()
    assert (data / "skills" / ".private").stat().st_mode & 0o777 == 0o600
    assert bool(backup._sql("SELECT to_regclass('public.backup_later') IS NOT NULL", database=database).strip() == "t") == bool(failure)
    assert list(tmp_path.glob("before-restore-*.tar.gz"))
    with tarfile.open(next(tmp_path.glob("before-restore-*.tar.gz"))) as recovery_archive:
        # The old state's recovery key must not become the target archive's key.
        assert json.load(recovery_archive.extractfile("secrets.json")) == current_secrets
    assert not list(data.glob(".galaris-restore-*"))
    if failure == "cleanup":
        assert "cleanup failed" in capsys.readouterr().err


@pytest.mark.parametrize("members", [
    [("../escape", "file", "")],
    [("files/rsync-only", "file", "")],
    [("link", "symlink", "/tmp"), ("link/escape", "file", "")],
    [("hard", "hardlink", "../../escape")],
])
def test_unsafe_data_archive_never_writes_outside_staging(tmp_path, members):
    source = tmp_path / "unsafe.tar"
    with tarfile.open(source, "w") as archive:
        for name, kind, target in members:
            member = tarfile.TarInfo(name)
            if kind != "file":
                member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                member.linkname = target
            archive.addfile(member, io.BytesIO(b""))
    with pytest.raises(backup.BackupError, match="archive"):
        backup._extract_data(source, tmp_path / "staging")
    assert not (tmp_path / "staging").exists()


def test_invalid_archive_is_rejected_before_database_access(tmp_path, monkeypatch):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("../escape")
        output.addfile(member, io.BytesIO(b""))
    called = []
    monkeypatch.setattr(backup, "_pg", lambda *args, **kwargs: called.append(args))
    with pytest.raises(backup.BackupError, match="members"):
        backup.verify(archive, tmp_path / "staging")
    assert called == []


def test_backup_error_redacts_connection_secrets(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "synthetic-password")
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", "synthetic-key")
    assert backup._redact("failure synthetic-password synthetic-key") == "failure *** ***"


def test_successful_postgresql_command_retains_redacted_warnings(monkeypatch, capsys):
    monkeypatch.setenv("POSTGRES_PASSWORD", "synthetic-password")
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="complete", stderr="Synthetic warning synthetic-password",
    ))
    assert backup._pg("pg_dump") == "complete"
    warning = capsys.readouterr().err
    assert "Synthetic warning" in warning and "exit 0" in warning
    assert "synthetic-password" not in warning
