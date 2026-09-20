from fastapi import Body, FastAPI, HTTPException, Query, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from loguru import logger
from pathlib import Path
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, BinaryIO
from starlette.types import Scope, Receive, Send
from cryptography.fernet import Fernet, InvalidToken
import json
import subprocess
import shutil
import re
import os
import logging
import stat
import errno
import asyncio
import fcntl
import signal
import tempfile
import tomllib
from uuid import uuid4

class _SuppressLogsRoute(logging.Filter):
    """Hide successful log-polling requests from the Uvicorn access log."""
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            path = str(args[2])
            if args[1] == "GET" and path.startswith("/instances/") and path.endswith("/logs") and args[4] == 200:
                return False
        return True

logging.getLogger("uvicorn.access").addFilter(_SuppressLogsRoute())

load_dotenv()

# Never forward variables defined in the manager .env file to managed Docker
# Compose subprocesses. For example, API_PORT must not override an instance default.
def _read_manager_env_keys() -> frozenset[str]:
    env_path = Path(__file__).parent / ".env"
    if not env_path.is_file():
        return frozenset()
    keys: set[str] = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0].strip())
    return frozenset(keys)

_MANAGER_ENV_KEYS = _read_manager_env_keys()

_MANAGER_VERSION = tomllib.loads((Path(__file__).parent / "pyproject.toml").read_text())["project"]["version"]
_MANAGER_CAPABILITIES = ("compose-lifecycle", "file-share")


app = FastAPI(
    title="Galaris — Harness Manager",
    description="Manage containerized harness instances and their files",
    version=_MANAGER_VERSION,
)

ALLOWED_IP    = os.getenv("ALLOWED_IP") or None
_secret       = os.getenv("HARNESS_MANAGER_SECRET") or None
_base         = os.getenv("BASE_DIR", "")
BASE_DIR      = Path(_base).resolve() if _base else None
IGNORE_DIRS   = {d.strip() for d in os.getenv("IGNORE_DIRS", "").split(",") if d.strip()}
MAX_FILE_SIZE = round(float(os.getenv("MAX_FILE_SIZE_MB", str(1_000_000 / 1_048_576))) * 1_048_576)
MAX_RAW_FILE_SIZE = round(float(os.getenv("MAX_RAW_FILE_SIZE_MB", str(512_000_000 / 1_048_576))) * 1_048_576)
ALLOWED_ACTIONS = frozenset({"start", "stop", "restart", "update"})
_TOKEN_MAX_AGE = 60

# Start and restart targets build runtime images in every managed provider. A cold
# build may clone and compile an SDK before Compose can begin its health wait, so
# these actions need the same bound as an explicit update.
_COMMAND_TIMEOUTS: dict[str, int] = {
    "start":   1200,
    "stop":    30,
    "restart": 1200,
    "update":  1200,
}
_INSTANCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

if not _secret:
    raise RuntimeError("HARNESS_MANAGER_SECRET is missing from .env; startup aborted.")

_fernet = Fernet(_secret.encode())

logger.info("Harness manager started — BASE_DIR={}, IGNORE_DIRS={}", BASE_DIR, IGNORE_DIRS)


# ── Middleware auth ────────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    client_ip = request.client.host if request.client else "unknown"

    if ALLOWED_IP and client_ip not in ("127.0.0.1", "::1") and client_ip != ALLOWED_IP:
        logger.warning("Access denied by IP policy — {}", client_ip)
        return JSONResponse(status_code=403, content={"detail": f"IP {client_ip} is not allowed."})

    token = request.headers.get("x-harness-token", "")
    try:
        _fernet.decrypt(token.encode(), ttl=_TOKEN_MAX_AGE)
    except InvalidToken:
        logger.warning("Access denied because of an invalid token — IP={}", client_ip)
        return JSONResponse(status_code=403, content={"detail": "Token is invalid, expired, or missing."})

    # The streamed counter remains authoritative when Content-Length is absent.
    if request.method == "PUT":
        cl = request.headers.get("content-length")
        limit = MAX_RAW_FILE_SIZE if "/raw/" in request.url.path else MAX_FILE_SIZE
        if cl and (not cl.isdecimal() or int(cl) > limit):
            maximum_mb = limit / 1_000_000
            return JSONResponse(
                status_code=413,
                content={"detail": f"Content is too large (maximum {maximum_mb:g} MB)."},
            )

    return await call_next(request)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_base_dir() -> Path:
    if not BASE_DIR or not BASE_DIR.is_dir():
        raise HTTPException(500, "BASE_DIR is not configured or does not exist.")
    return BASE_DIR


def _validate_instance_name(name: str) -> None:
    if not _INSTANCE_NAME_RE.match(name):
        raise HTTPException(
            422,
            f"Invalid instance name: '{name}'. Allowed characters are a-z, 0-9, - and _; "
            "the name must start with a letter or digit.",
        )


def _check_safe_path(name: str, base: Path) -> Path:
    """Reject ignored directories and traversal without restricting the name format.

    Template directories intentionally support free-form names.
    """
    if name in IGNORE_DIRS:
        raise HTTPException(403, f"'{name}' is a protected directory.")
    resolved = (base / name).resolve()
    if not str(resolved).startswith(str(base) + os.sep):
        raise HTTPException(403, f"Invalid path: '{name}'.")
    return resolved


def _check_dir_name(name: str, base: Path) -> Path:
    """Validate an instance name and resolve it without checking existence."""
    _validate_instance_name(name)
    if (base / name).is_symlink():
        raise HTTPException(403, "An instance directory cannot be a symbolic link.")
    return _check_safe_path(name, base)


def _get_instance_dir(instance_id: str) -> Path:
    base = _require_base_dir()
    instance_dir = _check_dir_name(instance_id, base)
    if not instance_dir.is_dir():
        raise HTTPException(404, f"Instance '{instance_id}' was not found.")
    return instance_dir


@contextmanager
def _instance_lock(instance_id: str, *, exclusive: bool) -> Iterator[None]:
    """Cross-worker identity reservation; reject contention without blocking async IO."""
    _validate_instance_name(instance_id)
    directory = _require_base_dir() / ".galaris-locks"
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(instance_id, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "Insufficient storage; retry after freeing space.") from exc
        raise
    try:
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(409, "Instance has an operation in progress; retry after it finishes.") from exc
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _file_parent(instance_id: str, filepath: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
    with _instance_lock(instance_id, exclusive=False):
        with _file_parent_unlocked(instance_id, filepath, create=create) as parent:
            yield parent


@contextmanager
def _file_parent_unlocked(instance_id: str, filepath: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
    """Anchor every path component to a descriptor; never follow runtime links."""
    _validate_instance_name(instance_id)
    base = _require_base_dir()
    if instance_id in IGNORE_DIRS:
        raise HTTPException(403, "Protected instance directory.")
    parts = filepath.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(403, "Invalid relative file path.")
    directory = None
    try:
        directory = os.open(base / instance_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory, parts[-1]
    except FileNotFoundError as exc:
        raise HTTPException(404, "File or instance was not found.") from exc
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "Insufficient storage; retry after freeing space.") from exc
        if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
            raise HTTPException(403, "File path contains a link or is not accessible.") from exc
        raise
    finally:
        if directory is not None:
            os.close(directory)


def _open_regular_file(instance_id: str, filepath: str) -> BinaryIO:
    with _file_parent(instance_id, filepath) as (parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise HTTPException(400, "Only regular files can be downloaded.")
        return os.fdopen(descriptor, "rb")


@contextmanager
def _atomic_file(instance_id: str, filepath: str, mode: int | None = None) -> Iterator[BinaryIO]:
    with _file_parent(instance_id, filepath, create=True) as (parent, name):
        temporary = f".{name}.{uuid4().hex}.galaris-write"
        if mode is None:
            try:
                previous = os.stat(name, dir_fd=parent, follow_symlinks=False)
                mode = stat.S_IMODE(previous.st_mode) if stat.S_ISREG(previous.st_mode) else 0o644
            except FileNotFoundError:
                mode = 0o644
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), mode)
                yield output
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


class _OpenedFileResponse(StreamingResponse):
    def __init__(self, source: BinaryIO, filename: str) -> None:
        self.source = source
        size = os.fstat(source.fileno()).st_size

        def chunks() -> Iterator[bytes]:
            with source:
                remaining = size
                while remaining:
                    chunk = source.read(min(remaining, 256 * 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        # Do not interpolate runtime-controlled names into HTTP headers.
        from urllib.parse import quote
        super().__init__(chunks(), media_type="application/octet-stream", headers={
            "Content-Length": str(size),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        })

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.source.close()


def _encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()




def _decrypt(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        raise HTTPException(400, "Encrypted content is invalid or has been altered.")


_COMPOSE_VARS = frozenset({
    "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROJECT_DIR", "COMPOSE_PROFILES",
})

def _subprocess_env(instance_dir: Path) -> dict[str, str]:
    """Build the environment for Make and Docker Compose subprocesses.

    Manager variables such as API_PORT and API_HOST are excluded so they cannot
    override ${VAR:-default} substitutions in instance Compose files.
    """
    excluded = _MANAGER_ENV_KEYS | _COMPOSE_VARS
    env = {k: v for k, v in os.environ.items() if k not in excluded}
    env["PWD"] = str(instance_dir)
    return env


def _run_command(command: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    """Bound both descendants' lifetime and captured command output."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=_subprocess_env(cwd),
            stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                # The parent may have exited while a descendant ignored SIGTERM.
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
            raise
        streams: list[str] = []
        for output in (stdout, stderr):
            output.seek(max(0, output.tell() - 1024 * 1024))
            streams.append(output.read(1024 * 1024).decode("utf-8", errors="replace"))
        result = subprocess.CompletedProcess(command, process.returncode, *streams)
        result.check_returncode()
        return result


def _run_make(instance_dir: Path, command: str) -> str:
    timeout = _COMMAND_TIMEOUTS.get(command, 60)
    try:
        result = _run_command(
            ["make", command],
            cwd=instance_dir,
            timeout=timeout,
        )
        # Return both streams because Docker Compose writes most pull progress to stderr.
        parts = [p for p in (result.stdout.strip(), result.stderr.strip()) if p]
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"'make {command}' exceeded its {timeout}-second timeout.")
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, (e.stderr or e.stdout).strip())


def _remove_compose_volumes(instance_dir: Path) -> None:
    """Remove runtime volumes owned by a deleted Compose instance."""

    try:
        _run_command(
            ["docker", "compose", "down", "--volumes", "--remove-orphans"],
            cwd=instance_dir,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timed out while removing Compose volumes.")
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500, (exc.stderr or exc.stdout).strip())


# ── General routes ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def home() -> dict[str, object]:
    """Expose the manager contract independently from its OpenAPI document."""

    return {
        "status": "online",
        "service": "bridge.harness",
        "version": _MANAGER_VERSION,
        "capabilities": list(_MANAGER_CAPABILITIES),
    }


@app.get("/system/info", summary="Harness manager system information")
def system_info() -> dict[str, int]:
    """Return manager UID and GID values used to configure containers."""
    return {"uid": os.getuid(), "gid": os.getgid()}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


# ── Instance inventory ───────────────────────────────────────────────────────

@app.get("/instances", summary="List harness instances")
def list_instances() -> dict[str, list[str]]:
    """Return all managed instances except ignored directories."""
    base = _require_base_dir()
    instances = [
        d.name for d in sorted(base.iterdir())
        if d.is_dir() and d.name not in IGNORE_DIRS and not d.name.startswith(".")
    ]
    return {"instances": instances}


# ── Instance creation ────────────────────────────────────────────────────────

class CreateInstanceRequest(BaseModel):
    name: str
    template: str | None = None  # Optional BASE_DIR child directory to copy.


@app.post("/instances", status_code=201, summary="Create a harness instance")
def create_instance(body: CreateInstanceRequest) -> dict[str, str]:
    with _instance_lock(body.name, exclusive=True):
        return _create_instance(body)


def _create_instance(body: CreateInstanceRequest) -> dict[str, str]:
    """Create an instance directory, optionally from a template."""
    base = _require_base_dir()
    instance_dir = _check_dir_name(body.name, base)
    if instance_dir.exists():
        raise HTTPException(409, f"Instance '{body.name}' already exists.")
    if body.template:
        template_dir = _check_safe_path(body.template, base)
        if not template_dir.is_dir():
            raise HTTPException(404, f"Template '{body.template}' was not found.")
        shutil.copytree(template_dir, instance_dir)
    else:
        instance_dir.mkdir(parents=True)
    logger.info("Harness instance created — name={}, template={}", body.name, body.template)
    return {"instance": body.name, "status": "created"}


# ── Instance deletion ────────────────────────────────────────────────────────

_COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)


def _has_lifecycle_configuration(instance_dir: Path) -> bool:
    """Return whether an instance is complete enough to run its stop target."""

    return (instance_dir / "Makefile").is_file() and any(
        (instance_dir / filename).is_file() for filename in _COMPOSE_FILENAMES
    )


def _repair_delete_permissions(
    function: object,
    path: str,
    error: BaseException,
) -> None:
    """Retry deletion after restoring owner access on read-only runtime data."""

    if not isinstance(error, PermissionError) or not callable(function):
        raise error
    target = Path(path)
    for candidate in (target.parent, target):
        try:
            current_mode = os.stat(candidate, follow_symlinks=False).st_mode
            os.chmod(
                candidate,
                current_mode | stat.S_IRWXU,
                follow_symlinks=False,
            )
        except OSError:
            # Container-owned paths may not be repairable by the host user.
            # The outer quarantine handler keeps that case non-blocking.
            pass
    function(path)


def _delete_quarantined_tree(instance_id: str, directory: Path) -> None:
    try:
        shutil.rmtree(directory, onexc=_repair_delete_permissions)
    except OSError as exc:
        # The canonical instance name is already free. A container may have
        # created root-owned files that the unprivileged manager cannot unlink;
        # keep those inaccessible leftovers quarantined instead of failing the
        # lifecycle operation or reusing them in the replacement runtime.
        logger.warning(
            "Harness instance data cleanup deferred because of host permissions — "
            "name={}, quarantine={}, error={}",
            instance_id,
            directory,
            exc,
        )

@app.delete("/instances/{instance_id}", summary="Delete a harness instance")
def delete_instance(instance_id: str) -> dict[str, str]:
    with _instance_lock(instance_id, exclusive=True):
        return _delete_instance(instance_id)


def _delete_instance(instance_id: str) -> dict[str, str]:
    """Stop an instance and delete its directory."""
    instance_dir = _get_instance_dir(instance_id)
    if _has_lifecycle_configuration(instance_dir):
        try:
            _run_make(instance_dir, "stop")
        except HTTPException as e:
            logger.warning("make stop failed for '{}'; attempting Compose cleanup — {}", instance_id, e.detail)
        try:
            _remove_compose_volumes(instance_dir)
        except HTTPException as e:
            logger.warning(
                "Compose cleanup failed for '{}'; preserving instance for repair — {}",
                instance_id,
                e.detail,
            )
            raise
    else:
        logger.info(
            "Harness instance has no complete lifecycle configuration; deleting directory — name={}",
            instance_id,
        )
    quarantine = instance_dir.parent / f".deleting-{instance_id}-{uuid4().hex}"
    instance_dir.rename(quarantine)
    _delete_quarantined_tree(instance_id, quarantine)
    logger.info("Harness instance deleted — name={}", instance_id)
    return {"instance": instance_id, "status": "deleted"}


# ── Container status ─────────────────────────────────────────────────────────

def _get_compose_status(instance_dir: Path) -> str:
    """Return the Compose runtime status without changing the instance."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=instance_dir,
            env=_subprocess_env(instance_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        if not lines:
            return "absent"
        for line in lines:
            try:
                container = json.loads(line)
                if container.get("State", "").lower() == "running":
                    return "running"
            except json.JSONDecodeError:
                pass
        return "stopped"
    except subprocess.TimeoutExpired:
        return "unknown"
    except Exception:
        return "unknown"


@app.get("/instances/{instance_id}/status", summary="Docker container status")
def get_instance_status(instance_id: str) -> dict[str, str]:
    """Return the instance status: running, stopped, absent, or unknown."""
    instance_dir = _get_instance_dir(instance_id)
    return {"instance": instance_id, "status": _get_compose_status(instance_dir)}


# ── Container logs ───────────────────────────────────────────────────────────

@app.get("/instances/{instance_id}/logs", summary="Harness container logs")
def get_instance_logs(instance_id: str, lines: int = 300) -> dict[str, list[str]]:
    """Return the last N lines from the instance's Docker Compose logs."""
    instance_dir = _get_instance_dir(instance_id)
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "--tail", str(lines), "--no-color"],
            cwd=instance_dir,
            env=_subprocess_env(instance_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
        return {"lines": output.splitlines()}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timed out while retrieving logs.")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Lifecycle actions ────────────────────────────────────────────────────────

@app.post("/instances/{instance_id}/actions/{action}", summary="Run a lifecycle action")
def run_action(instance_id: str, action: str) -> dict[str, str]:
    with _instance_lock(instance_id, exclusive=True):
        return _run_action(instance_id, action)


def _run_action(instance_id: str, action: str) -> dict[str, str]:
    """Run an allowed lifecycle action in the instance directory."""
    if action not in ALLOWED_ACTIONS:
        allowed = ", ".join(sorted(ALLOWED_ACTIONS))
        raise HTTPException(400, f"Action is not allowed. Valid actions: {allowed}")
    instance_dir = _get_instance_dir(instance_id)
    logger.info("Running lifecycle action — instance={}, action={}", instance_id, action)
    command = action
    if action == "restart" and _get_compose_status(instance_dir) == "absent":
        command = "start"
        logger.info(
            "Cold restart creates the missing container — instance={}",
            instance_id,
        )
    output = _run_make(instance_dir, command)
    return {"instance": instance_id, "action": action, "output": output}


# ── Files ─────────────────────────────────────────────────────────────────────

@app.get("/instances/{instance_id}/files/{filepath:path}", summary="Read a text file")
def read_file(instance_id: str, filepath: str) -> PlainTextResponse:
    """Return Fernet-encrypted file content for the client to decrypt."""
    logger.info("Reading file — instance={}, file={}", instance_id, filepath)
    with _open_regular_file(instance_id, filepath) as source:
        content = source.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, "Text file exceeds the configured size limit.")
    return PlainTextResponse(_encrypt(content.decode("utf-8")))


@app.put("/instances/{instance_id}/files/{filepath:path}", summary="Write a text file")
def write_file(
    instance_id: str,
    filepath: str,
    content: Annotated[str, Body(media_type="text/plain")],
    mode: Annotated[int, Query()] = 0o644,
) -> dict[str, str]:
    """Decrypt Fernet-encrypted content from the client and write it to disk."""
    if mode not in {0o600, 0o644, 0o755}:
        raise HTTPException(400, "File mode must be 0600, 0644, or 0755.")
    if len(content.encode()) > MAX_FILE_SIZE:
        maximum_mb = MAX_FILE_SIZE / 1_000_000
        raise HTTPException(413, f"Content is too large (maximum {maximum_mb:g} MB).")
    with _atomic_file(instance_id, filepath, mode) as output:
        output.write(_decrypt(content).encode("utf-8"))
    logger.info("Writing file — instance={}, file={}", instance_id, filepath)
    return {"instance": instance_id, "file": filepath, "status": "written"}


@app.get("/instances/{instance_id}/raw/{filepath:path}", summary="Download a raw binary file")
def download_raw(instance_id: str, filepath: str) -> StreamingResponse:
    """Stream raw file content without encryption or full in-memory buffering.

    This channel streams videos, audio files and PDFs from their opened inode.
    Middleware authentication through X-Harness-Token still applies.
    """
    source = _open_regular_file(instance_id, filepath)
    return _OpenedFileResponse(source, Path(filepath).name)


@app.put("/instances/{instance_id}/raw/{filepath:path}", summary="Write a raw binary file")
async def upload_raw(
    instance_id: str,
    filepath: str,
    request: Request,
) -> dict[str, str | int]:
    """Write a raw request body under a configured size and time limit.

    This unencrypted channel receives large conversation attachments such as
    images, videos, and PDFs. X-Harness-Token middleware authentication still applies.
    """
    size = 0
    async with asyncio.timeout(1200):
        with _atomic_file(instance_id, filepath) as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_RAW_FILE_SIZE:
                    raise HTTPException(413, "Binary file exceeds the configured size limit.")
                await run_in_threadpool(out.write, chunk)
            await run_in_threadpool(out.flush)
            await run_in_threadpool(os.fsync, out.fileno())
    logger.info("Writing binary file — instance={}, file={}, size={}", instance_id, filepath, size)
    return {"instance": instance_id, "file": filepath, "size": size, "status": "written"}


@app.delete("/instances/{instance_id}/files/{filepath:path}", summary="Delete a file")
def delete_file(instance_id: str, filepath: str) -> dict[str, str]:
    """Delete one file from the managed instance directory."""
    with _file_parent(instance_id, filepath) as (parent, name):
        # unlink never dereferences the final component, including a concurrently
        # substituted symlink; traversal to its parent is descriptor anchored.
        os.unlink(name, dir_fd=parent)
    logger.info("Deleting file — instance={}, file={}", instance_id, filepath)
    return {"instance": instance_id, "file": filepath, "status": "deleted"}


@app.delete("/instances/{instance_id}/trees/{dirpath:path}", summary="Delete a directory tree")
def delete_tree(instance_id: str, dirpath: str) -> dict[str, str]:
    """Recursively delete one directory below the instance root.

    The operation is idempotent so callers can reliably purge a managed
    namespace before rebuilding it.
    """
    try:
        with _file_parent(instance_id, dirpath) as (parent, name):
            if not shutil.rmtree.avoids_symlink_attacks:
                raise HTTPException(503, "This platform cannot safely delete directory trees.")
            try:
                shutil.rmtree(name, dir_fd=parent)
            except FileNotFoundError:
                return {"instance": instance_id, "directory": dirpath, "status": "absent"}
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"instance": instance_id, "directory": dirpath, "status": "absent"}
        raise
    logger.info("Deleting directory tree — instance={}, directory={}", instance_id, dirpath)
    return {"instance": instance_id, "directory": dirpath, "status": "deleted"}
