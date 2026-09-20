#!/usr/bin/env python3
"""Root-owned allowlisted manager for the embedded SSH executor."""

from __future__ import annotations

import asyncio
import fcntl
from functools import wraps
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

DATA_ROOT = Path("/data/ssh-executor")
STATE_ROOT = DATA_ROOT / "state"
REGISTRY_PATH = STATE_ROOT / "users.json"
AUTHORIZED_KEYS = STATE_ROOT / "authorized_keys"
HOST_KEY = STATE_ROOT / "host_keys" / "ssh_host_ed25519_key"
CONTROL_SOCKET = DATA_ROOT / "run" / "control.sock"
HOME_ROOT = DATA_ROOT / "home"
UID_START = 20000
# Reserved supplementary group shared only with the backend, never agent accounts.
CONTROL_GID = 19999
_registry_lock = threading.RLock()
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
VERSION = "1.0.0"
STARTED_AT = time.time()


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=60)


def registry_transaction(function):
    """Serialize account intent across worker threads and maintenance processes."""
    @wraps(function)
    def guarded(*args, **kwargs):
        with _registry_lock:
            STATE_ROOT.mkdir(parents=True, exist_ok=True)
            with (STATE_ROOT / "users.lock").open("a") as lock_file:
                os.chmod(lock_file.name, 0o600)
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    return function(*args, **kwargs)
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
    return guarded


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"next_uid": UID_START, "users": {}}
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {"next_uid": UID_START, "users": {}}


def _save_registry(registry: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".users-", dir=STATE_ROOT)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(registry, output, indent=2, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(REGISTRY_PATH)
        directory_fd = os.open(STATE_ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_code(code: str) -> str:
    if not USERNAME_RE.fullmatch(code):
        raise ValueError(
            "Agent code is not a valid Debian login; expected "
            "[a-z_][a-z0-9_-]{0,31} without transformation"
        )
    return code


def _account_exists(code: str) -> bool:
    return _run("getent", "passwd", code, check=False).returncode == 0


def _group_exists(code: str) -> bool:
    return _run("getent", "group", code, check=False).returncode == 0


def _write_authorized_key(code: str, public_key: str, enabled: bool) -> None:
    AUTHORIZED_KEYS.mkdir(parents=True, exist_ok=True)
    path = AUTHORIZED_KEYS / code
    content = public_key.strip() + "\n" if enabled else ""
    path.write_text(content, encoding="ascii")
    os.chown(path, 0, 0)
    # Public keys are not secrets. sshd reads this absolute path after dropping
    # privileges, while root ownership prevents the agent from changing it.
    os.chmod(path, 0o644)


def _ensure_account(code: str, uid: int, enabled: bool) -> None:
    if not _group_exists(code):
        _run("groupadd", "--gid", str(uid), code)
    if not _account_exists(code):
        _run(
            "useradd",
            "--uid", str(uid),
            "--gid", str(uid),
            "--home-dir", str(HOME_ROOT / code),
            "--create-home",
            "--shell", "/bin/bash" if enabled else "/usr/sbin/nologin",
            code,
        )
    home = HOME_ROOT / code
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(home, uid, uid)
    os.chmod(home, 0o700)
    _run("usermod", "--shell", "/bin/bash" if enabled else "/usr/sbin/nologin", code)
    # Debian creates password-locked accounts, and sshd rejects those before
    # public-key authentication. An empty password is safe here because every
    # password authentication method is disabled in sshd_config.
    if enabled:
        _run("passwd", "--delete", code)
    else:
        _run("passwd", "--lock", code)


def _ensure_host_key() -> None:
    HOST_KEY.parent.mkdir(parents=True, exist_ok=True)
    if not HOST_KEY.exists():
        _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(HOST_KEY))
    os.chmod(HOST_KEY, 0o600)


def _host_public_key() -> str:
    return HOST_KEY.with_suffix(".pub").read_text(encoding="ascii").strip()


@registry_transaction
def reconcile() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    AUTHORIZED_KEYS.mkdir(parents=True, exist_ok=True)
    HOME_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_host_key()
    registry = _load_registry()
    for code, raw in dict(registry.get("users") or {}).items():
        entry = dict(raw)
        _ensure_account(code, int(entry["uid"]), bool(entry.get("enabled", True)))
        _write_authorized_key(code, str(entry["public_key"]), bool(entry.get("enabled", True)))


@registry_transaction
def ensure_user(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = int(payload["agent_id"])
    code = _validate_code(str(payload["agent_code"]))
    public_key = str(payload["public_key"]).strip()
    if not public_key.startswith(("ssh-ed25519 ", "ecdsa-", "ssh-rsa ")):
        raise ValueError("Unsupported or invalid SSH public key")
    registry = _load_registry()
    users = dict(registry.get("users") or {})
    entry = dict(users.get(code) or {})
    if entry and int(entry.get("agent_id", -1)) != agent_id:
        raise ValueError("Agent code is already assigned to another agent id")
    if not entry:
        if _account_exists(code) or _group_exists(code):
            raise ValueError("Unregistered system account or group cannot be adopted")
        uid = int(registry.get("next_uid", UID_START))
        registry["next_uid"] = uid + 1
        entry = {"uid": uid, "created_at": time.time()}
    entry.update({
        "agent_id": agent_id,
        "code": code,
        "public_key": public_key,
        "enabled": True,
        "updated_at": time.time(),
    })
    users[code] = entry
    registry["users"] = users
    # Persist intent first: reconcile or a retry finishes a partially applied operation.
    _save_registry(registry)
    _ensure_account(code, int(entry["uid"]), True)
    _write_authorized_key(code, public_key, True)
    return {"agent_id": agent_id, "code": code, "uid": entry["uid"], "enabled": True}


def _entry_by_agent(registry: dict[str, Any], agent_id: int) -> tuple[str, dict[str, Any]]:
    for code, raw in dict(registry.get("users") or {}).items():
        entry = dict(raw)
        if int(entry.get("agent_id", -1)) == agent_id:
            return code, entry
    raise ValueError(f"No executor user for agent {agent_id}")


@registry_transaction
def _set_enabled(payload: dict[str, Any], enabled: bool) -> dict[str, Any]:
    registry = _load_registry()
    code, entry = _entry_by_agent(registry, int(payload["agent_id"]))
    entry["enabled"] = enabled
    entry["updated_at"] = time.time()
    registry["users"][code] = entry
    _save_registry(registry)
    _ensure_account(code, int(entry["uid"]), enabled)
    _write_authorized_key(code, str(entry["public_key"]), enabled)
    return {"agent_id": entry["agent_id"], "code": code, "enabled": enabled}


@registry_transaction
def rotate_key(payload: dict[str, Any]) -> dict[str, Any]:
    registry = _load_registry()
    code, entry = _entry_by_agent(registry, int(payload["agent_id"]))
    public_key = str(payload["public_key"]).strip()
    if not public_key.startswith(("ssh-ed25519 ", "ecdsa-", "ssh-rsa ")):
        raise ValueError("Unsupported or invalid SSH public key")
    entry["public_key"] = public_key
    entry["updated_at"] = time.time()
    registry["users"][code] = entry
    _save_registry(registry)
    _write_authorized_key(code, public_key, bool(entry.get("enabled", True)))
    return {"agent_id": entry["agent_id"], "code": code, "rotated": True}


def _disk_usage(path: Path) -> int:
    result = _run("du", "-sb", str(path), check=False)
    if result.returncode != 0 or not result.stdout:
        return 0
    return int(result.stdout.split()[0])


def list_users(_payload: dict[str, Any]) -> dict[str, Any]:
    registry = _load_registry()
    users = []
    for code, raw in sorted(dict(registry.get("users") or {}).items()):
        entry = dict(raw)
        users.append({
            "agent_id": entry["agent_id"],
            "code": code,
            "uid": entry["uid"],
            "enabled": bool(entry.get("enabled", True)),
            "home": str(HOME_ROOT / code),
            "usage_bytes": _disk_usage(HOME_ROOT / code),
            "updated_at": entry.get("updated_at"),
        })
    return {"users": users}


def _sessions() -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    registry = _load_registry()
    for code, raw in dict(registry.get("users") or {}).items():
        entry = dict(raw)
        root = HOME_ROOT / code / ".galaris" / "sessions"
        if not root.is_dir():
            continue
        for metadata_path in root.glob("*/metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                pid = int(metadata.get("pid") or 0)
                state = metadata.get("state")
                running = state == "prepared" or (
                    state not in {"completed", "failed", "cancelled"}
                    and pid > 0 and Path(f"/proc/{pid}").exists()
                    and not (metadata_path.parent / "exit_code").exists()
                )
                sessions.append({
                    "agent_id": entry["agent_id"],
                    "code": code,
                    "run_id": metadata["run_id"],
                    "pid": pid,
                    "running": running,
                    "command": str(metadata.get("command") or "")[:300],
                    "cwd": metadata.get("cwd_relative", "."),
                    "started_at": metadata.get("started_at"),
                    "task_id": metadata.get("task_id"),
                })
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
    return sessions


def list_sessions(_payload: dict[str, Any]) -> dict[str, Any]:
    return {"sessions": _sessions()}


def stop_session(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(UUID(str(payload["run_id"])))
    for session in _sessions():
        if session["run_id"] == run_id:
            # Receipt files belong to the agent. Never signal their supplied PID as
            # root: let the packaged helper verify identity with that Unix user's rights.
            response = _run("runuser", "-u", str(session["code"]), "--",
                            "/usr/local/bin/galaris-exec", "stop", "--run-id", run_id)
            result = json.loads(response.stdout)
            return {"run_id": run_id, "stopped": result.get("status") in {"completed", "failed", "cancelled"},
                    "status": result.get("status")}
    raise ValueError("Session not found")


def cleanup_partials(payload: dict[str, Any]) -> dict[str, Any]:
    minimum_age = max(300, int(payload.get("minimum_age_s", 86400)))
    cutoff = time.time() - minimum_age
    removed = 0
    bytes_removed = 0
    for path in HOME_ROOT.glob("**/.*.galaris-part-*"):
        try:
            stat = path.stat()
            if path.is_file() and stat.st_mtime < cutoff:
                bytes_removed += stat.st_size
                path.unlink()
                removed += 1
        except OSError:
            continue
    return {"removed": removed, "bytes_removed": bytes_removed}


def cleanup_caches(payload: dict[str, Any]) -> dict[str, Any]:
    registry = _load_registry()
    code, _entry = _entry_by_agent(registry, int(payload["agent_id"]))
    cache = HOME_ROOT / code / ".cache"
    before = _disk_usage(cache) if cache.exists() else 0
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(mode=0o700, exist_ok=True)
    owner = _run("getent", "passwd", code).stdout.split(":")
    os.chown(cache, int(owner[2]), int(owner[3]))
    return {"agent_id": payload["agent_id"], "bytes_removed": before}


def health(_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "ssh_host_key": _host_public_key(),
        "uptime_s": int(time.time() - STARTED_AT),
    }


def _cgroup_value(path: str) -> int | None:
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
        return None if raw == "max" else int(raw)
    except (OSError, ValueError):
        return None


def _resource_status() -> dict[str, Any]:
    cpu_usage_usec = None
    try:
        for line in Path("/sys/fs/cgroup/cpu.stat").read_text(encoding="ascii").splitlines():
            key, value = line.split(maxsplit=1)
            if key == "usage_usec":
                cpu_usage_usec = int(value)
                break
    except (OSError, ValueError):
        pass
    try:
        process_count = sum(1 for item in Path("/proc").iterdir() if item.name.isdigit())
    except OSError:
        process_count = 0
    return {
        "memory_current": _cgroup_value("/sys/fs/cgroup/memory.current"),
        "memory_limit": _cgroup_value("/sys/fs/cgroup/memory.max"),
        "pids_current": _cgroup_value("/sys/fs/cgroup/pids.current") or process_count,
        "pids_limit": _cgroup_value("/sys/fs/cgroup/pids.max"),
        "cpu_usage_usec": cpu_usage_usec,
    }


def status(_payload: dict[str, Any]) -> dict[str, Any]:
    disk = shutil.disk_usage(HOME_ROOT)
    users = list_users({})["users"]
    sessions = _sessions()
    return {
        **health({}),
        "ssh": "running" if Path("/run/sshd.pid").exists() else "starting",
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "load_average": list(os.getloadavg()),
        "users": users,
        "active_users": sum(1 for user in users if user["enabled"]),
        "disabled_users": sum(1 for user in users if not user["enabled"]),
        "sessions": sessions,
        "active_sessions": sum(1 for item in sessions if item["running"]),
        "resources": _resource_status(),
    }


OPERATIONS = {
    "health": health,
    "status": status,
    "list_users": list_users,
    "ensure_user": ensure_user,
    "rotate_key": rotate_key,
    "enable_user": lambda payload: _set_enabled(payload, True),
    "disable_user": lambda payload: _set_enabled(payload, False),
    "user_usage": lambda payload: {
        "usage_bytes": _disk_usage(HOME_ROOT / _entry_by_agent(_load_registry(), int(payload["agent_id"]))[0])
    },
    "list_sessions": list_sessions,
    "stop_session": stop_session,
    "cleanup_partials": cleanup_partials,
    "cleanup_caches": cleanup_caches,
}


def prepare_control_directory() -> None:
    """Remove legacy world access before publishing the management socket."""
    CONTROL_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    os.chown(CONTROL_SOCKET.parent, 0, CONTROL_GID)
    os.chmod(CONTROL_SOCKET.parent, 0o770)


def authorize_control_peer(writer: asyncio.StreamWriter) -> None:
    # Filesystem permissions enforce the backend's supplementary management group.
    # This second barrier rejects all allocated agent UIDs even if permissions drift.
    peer = writer.get_extra_info("socket")
    if peer is None:
        raise PermissionError("Missing Unix peer credentials")
    _pid, uid, _gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid < 0 or uid >= UID_START:
        raise PermissionError("Executor accounts cannot use the management socket")


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    started = time.perf_counter()
    operation = "unknown"
    try:
        authorize_control_peer(writer)
        raw = await asyncio.wait_for(reader.readline(), timeout=15)
        request = json.loads(raw)
        operation = str(request.get("operation") or "")
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        if operation == "recycle":
            result = {"recycling": True}
            asyncio.get_running_loop().call_later(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM))
        elif operation in OPERATIONS:
            result = await asyncio.to_thread(OPERATIONS[operation], payload)
        else:
            raise ValueError("Unsupported executor operation")
        response = {"id": request.get("id"), "ok": True, "result": result}
    except Exception as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    audit = {
        "event": "manager_operation",
        "operation": operation,
        "ok": bool(response.get("ok")),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    print(json.dumps(audit, separators=(",", ":")), flush=True)
    writer.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def serve() -> int:
    prepare_control_directory()
    await asyncio.to_thread(reconcile)
    CONTROL_SOCKET.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(_handle, path=CONTROL_SOCKET)
    os.chown(CONTROL_SOCKET, 0, CONTROL_GID)
    os.chmod(CONTROL_SOCKET, 0o660)
    sshd = await asyncio.create_subprocess_exec(
        "/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    ssh_wait = asyncio.create_task(sshd.wait())
    stop_wait = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        {ssh_wait, stop_wait},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    server.close()
    await server.wait_closed()
    if sshd.returncode is None:
        sshd.terminate()
        try:
            await asyncio.wait_for(sshd.wait(), timeout=10)
        except TimeoutError:
            sshd.kill()
            await sshd.wait()
    CONTROL_SOCKET.unlink(missing_ok=True)
    return sshd.returncode or 0


async def healthcheck() -> int:
    try:
        reader, writer = await asyncio.open_unix_connection(CONTROL_SOCKET)
        writer.write(b'{"id":"healthcheck","operation":"health","payload":{}}\n')
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), timeout=3))
        writer.close()
        await writer.wait_closed()
        return 0 if response.get("ok") else 1
    except Exception:
        return 1


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if operation == "serve":
        return asyncio.run(serve())
    if operation == "healthcheck":
        return asyncio.run(healthcheck())
    if operation == "reconcile":
        reconcile()
        return 0
    raise SystemExit(f"Unknown operation: {operation}")


if __name__ == "__main__":
    raise SystemExit(main())
