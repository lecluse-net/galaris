"""Offline database/data archives; invoked only by the maintenance launcher.

This module uses the standard library and PostgreSQL clients so it can also run
with the installed image before that image contains the backup command itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback
from typing import cast
from uuid import uuid4


class BackupError(RuntimeError):
    """An archive or maintenance operation could not be verified."""


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _redact(message: str) -> str:
    for key in ("POSTGRES_PASSWORD", "ENCRYPTION_MASTER_KEY", "AUTH_SECRET_KEY"):
        secret = os.environ.get(key, "")
        if secret:
            message = message.replace(secret, "***")
    return message[-8000:]


def _pg(program: str, *arguments: str, database: str | None = None) -> str:
    environment = os.environ.copy()
    for suffix, default in (("HOST", "postgres"), ("PORT", "5432"),
                            ("USER", "galaris"), ("PASSWORD", "")):
        environment[f"PG{suffix}"] = os.environ.get(f"POSTGRES_{suffix}", default)
    environment["PGCONNECT_TIMEOUT"] = "10"
    result = subprocess.run(
        [program, "--dbname", database or os.environ.get("POSTGRES_DB", "galaris"), *arguments],
        env=environment, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise BackupError(f"{program} failed (exit {result.returncode}): {_redact(result.stderr)}")
    if result.stderr:
        sys.stderr.write(f"{program} stderr (exit 0): {_redact(result.stderr)}\n")
    return result.stdout


def _sql(statement: str, *, database: str = "postgres") -> str:
    return _pg("psql", "-X", "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align",
               "--command", statement, database=database)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _data_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if member.name == "files" or member.name.startswith("files/"):
        return None
    return member


def save(
    archive: Path, data: Path, configuration: Path,
    *, recovery_secrets: dict[str, str] | None = None,
) -> None:
    """Publish an archive only after every payload and its manifest are complete."""
    if archive.exists() or archive.is_symlink():
        raise BackupError("Backup destination already exists")
    if data.is_symlink() or not data.is_dir():
        raise BackupError("Data root must be a real directory")
    if archive.resolve().is_relative_to(data.resolve()):
        raise BackupError("Backup archives must be stored outside /data")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".galaris-save-", dir=archive.parent) as temporary:
        workspace = Path(temporary)
        dump = workspace / "database.dump"
        _pg("pg_dump", "--format=custom", "--file", str(dump))
        _pg("pg_restore", "--list", str(dump))
        with tarfile.open(workspace / "data.tar", "w") as files:
            for child in sorted(data.iterdir()):
                files.add(child, arcname=child.name, recursive=True, filter=_data_filter)
        shutil.copyfile(configuration, workspace / "configuration.env")
        secrets = recovery_secrets if recovery_secrets is not None else {
            key: os.environ.get(key, "") for key in ("ENCRYPTION_MASTER_KEY", "AUTH_SECRET_KEY")
        }
        (workspace / "secrets.json").write_text(json.dumps(secrets))
        payloads = {name: _digest(workspace / name)
                    for name in ("database.dump", "data.tar", "configuration.env", "secrets.json")}
        manifest = {
            "format": "galaris-backup", "version": 1, "excluded": ["/data/files"],
            "image": os.environ.get("GALARIS_BACKUP_IMAGE", "unknown"),
            "postgres_version": _sql("SHOW server_version_num").strip(),
            "encryption_key_sha256": hashlib.sha256(
                secrets.get("ENCRYPTION_MASTER_KEY", "").encode()).hexdigest(),
            "sha256": payloads,
        }
        (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        candidate = workspace / "archive.tar.gz"
        with tarfile.open(candidate, "w:gz") as result:
            for name in (*payloads, "manifest.json"):
                result.add(workspace / name, arcname=name)
        os.chmod(candidate, 0o600)
        with candidate.open("rb") as complete:
            os.fsync(complete.fileno())
        # Atomic publication which cannot overwrite another backup.
        os.link(candidate, archive)
        os.chown(archive, int(os.environ.get("GALARIS_BACKUP_UID", os.getuid())),
                 int(os.environ.get("GALARIS_BACKUP_GID", os.getgid())))


def _unpack(archive: Path, workspace: Path) -> dict[str, object]:
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        names = [member.name for member in members]
        expected = {"database.dump", "data.tar", "configuration.env", "secrets.json", "manifest.json"}
        if set(names) != expected or len(names) != len(expected) or any(not member.isfile() for member in members):
            raise BackupError("Invalid archive members")
        source.extractall(workspace, filter="data")
    raw_manifest = cast(object, json.loads((workspace / "manifest.json").read_text()))
    if not isinstance(raw_manifest, dict):
        raise BackupError("Invalid backup manifest")
    manifest = cast(dict[str, object], raw_manifest)
    if (manifest.get("format") != "galaris-backup"
            or manifest.get("version") != 1 or manifest.get("excluded") != ["/data/files"]):
        raise BackupError("Unsupported backup manifest")
    raw_checksums = manifest.get("sha256")
    if not isinstance(raw_checksums, dict):
        raise BackupError("Incomplete backup checksums")
    checksums = cast(dict[str, object], raw_checksums)
    if set(checksums) != expected - {"manifest.json"}:
        raise BackupError("Incomplete backup checksums")
    for name in expected - {"manifest.json"}:
        if _digest(workspace / name) != checksums[name]:
            raise BackupError(f"Checksum mismatch: {name}")
    return manifest


def _extract_data(source: Path, destination: Path) -> None:
    """Preserve symlinks as leaves, never extract through them or into files/."""
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.parts[0] == "files" or str(path) in by_name
                    or not (member.isdir() or member.isfile() or member.issym() or member.islnk())):
                raise BackupError("Unsafe data archive member")
            by_name[str(path)] = member
        for name, member in by_name.items():
            for parent in PurePosixPath(name).parents:
                ancestor = by_name.get(str(parent))
                if ancestor is not None and not ancestor.isdir():
                    raise BackupError("Data archive traverses a non-directory")
            if member.islnk():
                target = by_name.get(member.linkname)
                if target is None or not target.isfile():
                    raise BackupError("Unsafe data archive hardlink")
        destination.mkdir()
        # Every path and ancestor was validated above. Absolute symlinks may be
        # retained as leaves, including references into the separate rsync tree.
        archive.extractall(destination, filter="fully_trusted")


def verify(archive: Path, workspace: Path) -> dict[str, object]:
    manifest = _unpack(archive, workspace)
    key_hash = hashlib.sha256(os.environ.get("ENCRYPTION_MASTER_KEY", "").encode()).hexdigest()
    if manifest.get("encryption_key_sha256") != key_hash:
        raise BackupError("Encryption key differs: recover ENCRYPTION_MASTER_KEY from secrets.json before restoration")
    if int(str(manifest["postgres_version"])) // 10000 != int(_sql("SHOW server_version_num").strip()) // 10000:
        raise BackupError("Restoration requires the same PostgreSQL major version")
    _pg("pg_restore", "--list", str(workspace / "database.dump"))
    _extract_data(workspace / "data.tar", workspace / "data")
    return manifest


def restore(
    archive: Path, data: Path, configuration: Path,
    *, recovery_secrets: dict[str, str] | None = None,
) -> Path:
    """Stage a complete database before replacing the current DB and data tree."""
    original = os.environ.get("POSTGRES_DB", "galaris")
    if original in {"postgres", "template0", "template1"}:
        raise BackupError("Refusing to replace a PostgreSQL maintenance database")
    if data.is_symlink() or not data.is_dir():
        raise BackupError("Data root must be a real directory")
    identity = uuid4().hex
    staged = f"galaris_restore_{identity}"
    previous = f"galaris_previous_{identity}"
    recovery = archive.parent / f"before-restore-{identity}.tar.gz"
    with tempfile.TemporaryDirectory(prefix=".galaris-restore-", dir=archive.parent) as temporary:
        workspace = Path(temporary)
        verify(archive, workspace)
        # The safety copy precedes every database or filesystem mutation.
        save(recovery, data, configuration, recovery_secrets=recovery_secrets)
        sys.stderr.write(f"Recovery archive: {recovery}\n")
        _sql(f"CREATE DATABASE {_identifier(staged)} TEMPLATE template0")
        swap = data / f".galaris-restore-{identity}"
        moved_old: list[str] = []
        moved_new: list[str] = []
        database_swapped = False
        rollback_complete = False
        try:
            _pg("pg_restore", "--exit-on-error", "--no-owner", "--single-transaction",
                str(workspace / "database.dump"), database=staged)
            swap.mkdir(mode=0o700)
            (swap / "old").mkdir()
            _extract_data(workspace / "data.tar", swap / "new")
            for child in sorted(data.iterdir()):
                if child.name not in {"files", swap.name}:
                    child.rename(swap / "old" / child.name)
                    moved_old.append(child.name)
            for child in sorted((swap / "new").iterdir()):
                child.rename(data / child.name)
                moved_new.append(child.name)
            # Prevent other sessions from reconnecting while the names change.
            _sql(f"ALTER DATABASE {_identifier(original)} ALLOW_CONNECTIONS false")
            _sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                 f"WHERE datname={_literal(original)} AND pid<>pg_backend_pid()")
            _sql(f"BEGIN; ALTER DATABASE {_identifier(original)} RENAME TO {_identifier(previous)}; "
                 f"ALTER DATABASE {_identifier(staged)} RENAME TO {_identifier(original)}; COMMIT")
            database_swapped = True
        except BaseException:
            # Never replace the primary exception with cleanup evidence.
            try:
                # A connection can fail after COMMIT reached PostgreSQL. Inspect
                # the names before deciding whether the swap must be reversed.
                if _sql(f"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname={_literal(previous)})").strip() == "t":
                    _sql(f"BEGIN; ALTER DATABASE {_identifier(original)} RENAME TO {_identifier(staged)}; "
                         f"ALTER DATABASE {_identifier(previous)} RENAME TO {_identifier(original)}; COMMIT")
                for name in reversed(moved_new):
                    (data / name).rename(swap / "new" / name)
                for name in reversed(moved_old):
                    (swap / "old" / name).rename(data / name)
                _sql(f"ALTER DATABASE {_identifier(original)} ALLOW_CONNECTIONS true")
                rollback_complete = True
            except BaseException as cleanup:
                sys.stderr.write(f"Restoration rollback failed: {_redact(str(cleanup))}; recovery={recovery}\n")
            raise
        finally:
            try:
                if database_swapped or rollback_complete:
                    disposable = previous if database_swapped else staged
                    _sql(f"DROP DATABASE IF EXISTS {_identifier(disposable)}")
                if swap.exists() and (database_swapped or rollback_complete):
                    shutil.rmtree(swap)
            except BaseException as cleanup:
                sys.stderr.write(f"Restoration cleanup failed: {_redact(str(cleanup))}; recovery={recovery}\n")
                if database_swapped:
                    raise BackupError(f"Restoration completed but cleanup failed; recovery={recovery}") from cleanup
    return recovery


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("save", "verify", "restore"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument("--configuration", type=Path, default=Path("/installation.env"))
    arguments = parser.parse_args()
    os.umask(0o077)
    try:
        recovery_secrets: dict[str, str] | None = None
        installed_environment = Path("/installed-environment.json")
        if installed_environment.exists():
            recovery_secrets = {}
            entries = cast(list[str], json.loads(installed_environment.read_text()))
            for entry in entries:
                key, separator, value = entry.partition("=")
                if separator and key in {"ENCRYPTION_MASTER_KEY", "AUTH_SECRET_KEY"}:
                    recovery_secrets[key] = value
                if separator and (key.startswith("POSTGRES_") or (
                    arguments.operation == "save" and key in {"ENCRYPTION_MASTER_KEY", "AUTH_SECRET_KEY"}
                )):
                    os.environ[key] = value
        if arguments.operation == "save":
            save(arguments.archive, arguments.data, arguments.configuration)
        elif arguments.operation == "restore":
            restore(arguments.archive, arguments.data, arguments.configuration, recovery_secrets=recovery_secrets)
        else:
            with tempfile.TemporaryDirectory(prefix=".galaris-verify-", dir=arguments.archive.parent) as temporary:
                verify(arguments.archive, Path(temporary))
    except Exception as exc:
        locations = "; ".join(f"{frame.filename}:{frame.lineno} ({frame.name})"
                              for frame in traceback.extract_tb(exc.__traceback__))
        sys.stderr.write(f"Backup operation failed: {_redact(str(exc))}; locations={locations}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
