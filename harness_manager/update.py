"""Update only distributed source files, using an authenticated Galaris manifest."""
from __future__ import annotations

import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

from cryptography.fernet import Fernet
from dotenv import load_dotenv

FILES = frozenset({"main.py", "update.py", "Makefile", "pyproject.toml", "uv.lock", "README.md", ".env.example"})
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
SERVICE = "galaris-harness-manager.service"


class UpdateError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    # Never forward the manager credential to another URL, even on the same host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def version(value: object) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", value):
        raise UpdateError("Invalid release version")
    return tuple(map(int, value.split(".")))


def installed_version(root: Path) -> str:
    value = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    version(value)
    return value


def fetch(url: str, cipher: Fernet, limit: int) -> bytes:
    request = Request(url, headers={"X-Harness-Token": cipher.encrypt(b"galaris-harness-update").decode()})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Download exceeds the release size limit")
    return data


def download(base_url: str, cipher: Fernet) -> tuple[str, bytes]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UpdateError("Set GALARIS_UPDATE_URL to the HTTP(S) update endpoint shown by Galaris")
    base_url = base_url.rstrip("/")
    # The signature binds the version, size and checksum to the shared manager key.
    manifest = json.loads(cipher.decrypt(fetch(f"{base_url}/manifest", cipher, 16384), ttl=300))
    if not isinstance(manifest, dict):
        raise UpdateError("Invalid release manifest")
    release_version = manifest.get("version")
    version(release_version)
    digest = manifest.get("sha256")
    size = manifest.get("size")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise UpdateError("Invalid release checksum")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise UpdateError("Invalid release size")
    content = fetch(f"{base_url}/archive/{digest}.zip", cipher, size)
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        raise UpdateError("Release checksum mismatch; no files were changed")
    return release_version, content


def unpack(content: bytes, expected_version: str, destination: Path) -> None:
    with ZipFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        expected = {f"harness_manager/{name}" for name in FILES}
        if len(infos) != len(expected) or {info.filename for info in infos} != expected:
            raise UpdateError("Archive must contain exactly the manager source files, without .env or extra paths")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
            raise UpdateError("Unpacked release is too large")
        for info in infos:
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise UpdateError("Archive contains a non-regular file")
            target = destination / Path(info.filename).name
            target.write_bytes(archive.read(info))
            target.chmod(0o644)
    if installed_version(destination) != expected_version:
        raise UpdateError("Archive version does not match its signed manifest")
    for name in ("main.py", "update.py"):
        compile((destination / name).read_bytes(), name, "exec")


def command(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    return subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, check=check, timeout=300)


def running_mode(root: Path) -> str | None:
    if shutil.which("systemctl"):
        active = command(root, "systemctl", "--user", "is-active", SERVICE, check=False)
        if active.returncode == 0:
            directory = command(root, "systemctl", "--user", "show", SERVICE, "--property=WorkingDirectory", "--value").stdout.strip()
            if Path(directory).resolve() != root.resolve():
                raise UpdateError("The running manager service belongs to a different installation")
            return "systemd"
    pid_file = root / ".local/api.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        if pid <= 1:
            raise UpdateError("Invalid manager PID")
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        if str(root / ".local/venv/bin/uvicorn") not in cmdline or "main:app" not in cmdline:
            raise UpdateError("PID file does not belong to this manager")
        return "background"
    return None


def stop(root: Path, mode: str | None) -> None:
    if mode == "systemd":
        command(root, "systemctl", "--user", "stop", SERVICE)
    elif mode == "background":
        command(root, "make", "stop")


def start(root: Path, mode: str | None) -> None:
    if mode == "systemd":
        command(root, "systemctl", "--user", "start", SERVICE)
    elif mode == "background":
        command(root, "make", "start")


def verify_running(root: Path, expected_version: str, cipher: Fernet) -> None:
    host = os.environ.get("API_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1" if host == "0.0.0.0" else "::1"
    if ":" in host:
        host = f"[{host}]"
    url = f"http://{host}:{int(os.environ.get('API_PORT', '8485'))}/"
    for _ in range(30):
        request = Request(url, headers={"X-Harness-Token": cipher.encrypt(b"auth").decode()})
        try:
            with build_opener(NoRedirect()).open(request, timeout=1) as response:
                contract = json.loads(response.read(16384))
            if contract.get("service") == "bridge.harness" and contract.get("version") == expected_version:
                return
        except (URLError, TimeoutError, ValueError):
            pass
        time.sleep(1)
    raise UpdateError("The restarted manager did not announce the expected version")


def replace_files(source: Path, root: Path) -> None:
    for name in sorted(FILES):
        target = root / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise UpdateError("A distributed filename is occupied by a non-regular local file")
        descriptor, filename = tempfile.mkstemp(prefix=".update-", dir=root)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write((source / name).read_bytes())
            temporary.chmod(0o644)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def apply(root: Path, staged: Path, target_version: str, cipher: Fernet) -> Path:
    mode = running_mode(root)
    old_version = installed_version(root)
    backup = Path(tempfile.mkdtemp(prefix=f"backup-{old_version}-", dir=root / ".local"))
    existing: set[str] = set()
    for name in FILES:
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UpdateError("Refusing to replace a symlink or directory")
        if path.exists():
            shutil.copy2(path, backup / name)
            existing.add(name)
    stop(root, mode)
    try:
        replace_files(staged, root)
        command(root, "make", "install")
        start(root, mode)
        if mode:
            verify_running(root, target_version, cipher)
    except Exception as failure:
        try:
            stop(root, mode)
            for name in FILES:
                if name in existing:
                    shutil.copy2(backup / name, root / name)
                else:
                    (root / name).unlink(missing_ok=True)
            command(root, "make", "install")
            start(root, mode)
            if mode:
                verify_running(root, old_version, cipher)
        except Exception as rollback_failure:
            raise UpdateError(f"Update and rollback failed. Recover source files from {backup}; configuration and instances were preserved") from rollback_failure
        raise UpdateError(f"Update failed; previous version restored. Backup: {backup}") from failure
    return backup


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    local = root / ".local"
    if local.is_symlink():
        raise UpdateError(".local must not be a symlink")
    local.mkdir(mode=0o700, exist_ok=True)
    with (local / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError("Another manager update is running") from None
        cipher = Fernet(os.environ.get("HARNESS_MANAGER_SECRET", "").encode())
        url = os.environ.get("UPDATE_URL") or os.environ.get("GALARIS_UPDATE_URL", "")
        target_version, content = download(url, cipher)
        current = installed_version(root)
        if version(target_version) == version(current):
            print(f"Harness Manager {current} is already installed.")
            return 0
        if version(target_version) < version(current):
            raise UpdateError(f"Galaris offers {target_version}, older than installed {current}; refusing downgrade")
        with tempfile.TemporaryDirectory(prefix="update-", dir=local) as temporary:
            staged = Path(temporary)
            unpack(content, target_version, staged)
            backup = apply(root, staged, target_version, cipher)
        print(f"Harness Manager updated from {current} to {target_version}. Backup: {backup}")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # HTTP errors may include URLs; subprocess output can contain local details.
        # Only our bounded, credential-free operator messages are displayed.
        message = str(error) if isinstance(error, UpdateError) else f"Update failed ({type(error).__name__}); check the update URL, shared key, network and local tools"
        print(message, file=sys.stderr)
        sys.exit(1)
