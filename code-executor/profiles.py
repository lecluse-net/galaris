"""Offline, archive-first maintenance of retained IDE profiles. Never touches Git."""

from contextlib import contextmanager
import argparse
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from uuid import UUID


@contextmanager
def state_lock(root: Path):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "maintenance.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Stop the editor runtime before maintaining its profiles") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def session_directory(root: Path, identifier: str) -> Path:
    identifier = str(UUID(identifier))
    directory = root / "sessions" / identifier
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("A session directory must not be a symbolic link")
    return directory


def retained_profiles(root: Path) -> list[dict[str, object]]:
    result = []
    for path in sorted((root / "sessions").glob("*/manifest.json")):
        directory = session_directory(root, path.parent.name)
        if path.is_symlink():
            raise ValueError("A profile manifest must not be a symbolic link")
        manifest = json.loads(path.read_text())
        size = sum(child.lstat().st_size for child in directory.rglob("*") if child.is_file() and not child.is_symlink())
        result.append({"session": directory.name, "uid": manifest["uid"], "mode": manifest["mode"], "bytes": size})
    return result


def archive_profile(root: Path, identifier: str, destination: Path, *, retire: bool = False) -> None:
    directory = session_directory(root, identifier)
    if (not directory.is_dir() or not (directory / "manifest.json").is_file()
            or (directory / "manifest.json").is_symlink() or (directory / "profile").is_symlink()):
        raise ValueError("Retained profile not found")
    destination = destination.absolute()
    if destination.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError("Store the archive outside the runtime state volume")
    # Refuse leftover IDE processes even if their supervisor was interrupted.
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            arguments = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise RuntimeError("Cannot verify stopped IDE processes; stop the runtime container first") from None
        if b"/profile/editor.sock" in arguments:
            raise RuntimeError("An IDE still uses retained profiles; stop it before archiving")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".code-profile-", delete=False) as output:
            temporary = Path(output.name)
            with tarfile.open(fileobj=output, mode="w:gz", dereference=False) as archive:
                # Unix sockets and devices are ephemeral and cannot be restored.
                archive.add(directory, arcname=directory.name,
                    filter=lambda member: member if member.isfile() or member.isdir() or member.issym() else None)
            output.flush()
            os.fsync(output.fileno())
        # Publish without overwriting a previous backup, before removing anything.
        os.link(temporary, destination)
        descriptor = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if retire:
            shutil.rmtree(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_profile(root: Path, source: Path) -> str:
    sessions = root / "sessions"
    sessions.mkdir(mode=0o711, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="restore-") as temporary:
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            if not members:
                raise ValueError("Empty profile archive")
            identifier = str(UUID(members[0].name.split("/")[0]))
            destination = session_directory(root, identifier)
            if destination.exists():
                raise ValueError("A profile already exists for this session")
            if any(member.name.split("/")[0] != identifier or ".." in PurePosixPath(member.name).parts
                    or PurePosixPath(member.name).is_absolute() for member in members):
                raise ValueError("An archive must contain exactly one session")
            try:
                group = archive.getmember(identifier + "/profile").gid
            except KeyError:
                raise ValueError("Missing profile directory in archive") from None
            archive.extractall(temporary, filter="data")
        extracted = Path(temporary) / identifier
        manifest = json.loads((extracted / "manifest.json").read_text())
        if manifest["session"] != identifier or not isinstance(manifest["uid"], int) or manifest["uid"] < 1000:
            raise ValueError("Invalid profile manifest")
        profile = extracted / "profile"
        if profile.is_symlink() or not profile.is_dir():
            raise ValueError("Invalid profile directory")
        for path in [profile, *profile.rglob("*")]:
            os.chown(path, manifest["uid"], group, follow_symlinks=False)
        profile.chmod(0o700)
        extracted.chmod(0o711)
        extracted.rename(destination)
    return identifier


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, default=Path(os.environ.get("CODE_STATE_ROOT", "/var/lib/galaris-code")))
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    for name in ("archive", "retire"):
        action = actions.add_parser(name)
        action.add_argument("session")
        action.add_argument("--output", type=Path, required=True)
    restore = actions.add_parser("restore")
    restore.add_argument("archive", type=Path)
    arguments = parser.parse_args()
    try:
        with state_lock(arguments.state_root):
            if arguments.action == "list":
                print(json.dumps(retained_profiles(arguments.state_root), indent=2))
            elif arguments.action == "restore":
                print(restore_profile(arguments.state_root, arguments.archive))
            else:
                archive_profile(arguments.state_root, arguments.session, arguments.output, retire=arguments.action == "retire")
                print(arguments.output)
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
