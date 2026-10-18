"""Per-account deployment and automatic maintenance of the packaged editor.

Only the approved account home is mounted. The receipt never contains a credential.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import tempfile
import traceback
import urllib.request


VERSION = "4.141.0"

# Only these fixed diagnostics may cross the SSH boundary. Never return the
# exception text, Docker stderr, paths or credentials to the application.
FAILURE_REASONS = {
    "Docker executable is unavailable": "docker_missing",
    "The Docker command timed out": "docker_timeout",
    "Docker daemon access failed": "docker_access",
    "Docker Compose is unavailable": "compose_unavailable",
    "Docker access, Compose or the code-server build failed": "docker_command_failed",
    "Deploy the editor through a non-system SSH account owning its home": "account_home",
    "The editor deployment directory must stay inside the account home": "deployment_path",
    "Automatic updates require an existing managed editor credential": "credential_missing",
    "Automatic updates require an existing managed editor": "editor_missing",
    "The retained editor credential is invalid": "credential_invalid",
    "The existing editor belongs to a different home": "home_mismatch",
    "An older editor is already deployed; preserve its sessions before replacing it": "upgrade_required",
    "End existing editor sessions before updating the editor": "sessions_active",
    "The editor control port must be loopback-only": "port_binding",
    "The editor user namespace check failed": "user_namespaces",
    "The deployed editor did not pass verification": "health_verification",
    "The deployed editor did not become ready": "health_timeout",
}

_credential_values: set[str] = set()


def diagnostic_text(value: str) -> str:
    for secret in _credential_values:
        value = value.replace(secret, "[redacted]")
    value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
                   "[redacted private key]", value, flags=re.S)
    value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+", "[redacted URL]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [redacted]", value)
    value = re.sub(r'''(?i)(["']?(?:password|passwd|token|secret|credential|api[_-]?key|authorization)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
                   r"\1[redacted]", value)
    value = re.sub(r"[A-Za-z0-9_+/=-]{32,}", "[redacted opaque value]", value)
    return value[-8000:]


class DockerCommandError(RuntimeError):
    def __init__(self, message: str, arguments: tuple[str, ...], exit_code: int | None,
                 stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.details = {"command": diagnostic_text("docker " + " ".join(arguments)), "exit_code": exit_code,
                        "stdout": diagnostic_text(stdout), "stderr": diagnostic_text(stderr)}


def docker(*arguments: str, timeout: int = 30, quiet: bool = False) -> str:
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(["docker", *arguments], check=False, timeout=timeout,
                stdout=output if quiet else subprocess.PIPE, stderr=errors, text=True)
        except FileNotFoundError:
            raise DockerCommandError("Docker executable is unavailable", arguments, None) from None
        except subprocess.TimeoutExpired as error:
            errors.seek(max(0, errors.tell() - 8000))
            output.seek(max(0, output.tell() - 8000))
            raise DockerCommandError("The Docker command timed out", arguments, None,
                                     stdout=output.read().decode("utf-8", errors="replace"),
                                     stderr=errors.read().decode("utf-8", errors="replace")) from error
        errors.seek(max(0, errors.tell() - 16000))
        stderr = errors.read().decode("utf-8", errors="replace")
        output.seek(max(0, output.tell() - 16000))
        stdout = result.stdout or output.read().decode("utf-8", errors="replace")
    if result.returncode:
        message = "Docker access, Compose or the code-server build failed"
        if arguments[0] == "info":
            message = "Docker daemon access failed"
        elif arguments[:2] == ("compose", "version"):
            message = "Docker Compose is unavailable"
        elif arguments[0] == "exec" and "bwrap" in arguments:
            message = "The editor user namespace check failed"
        raise DockerCommandError(message, arguments, result.returncode, stdout, stderr)
    return "" if quiet else stdout.strip()


def credential(root: Path) -> str:
    path = root / "credential"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as source:
            value = source.read(129).strip()
        if not 32 <= len(value) <= 128:
            raise RuntimeError("The retained editor credential is invalid")
        _credential_values.add(value)
        return value
    value = secrets.token_urlsafe(48)
    _credential_values.add(value)
    with os.fdopen(descriptor, "w") as target:
        target.write(value)
    return value


def probe(port: int, token: str) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=5) as response:
        value = json.loads(response.read(4096))
    if not isinstance(value, dict) or value.get("protocol") != 1 or value.get("version") != VERSION:
        raise RuntimeError("The deployed editor did not pass verification")
    return value


def verify_service(container: str, uid: int, gid: int, token: str) -> int:
    inspection = json.loads(docker("inspect", container))[0]
    binding = inspection["NetworkSettings"]["Ports"]["8766/tcp"]
    if len(binding) != 1 or binding[0]["HostIp"] != "127.0.0.1":
        raise RuntimeError("The editor control port must be loopback-only")
    port = int(binding[0]["HostPort"])
    docker("exec", "--user", f"{uid}:{gid}", container, "bwrap", "--unshare-user", "--unshare-pid", "--unshare-net",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc", "--", "/usr/bin/true")
    for attempt in range(30):
        try:
            probe(port, token)
            return port
        except (OSError, ValueError):
            if attempt == 29:
                raise RuntimeError("The deployed editor did not become ready") from None
            time.sleep(1)
    raise RuntimeError("The deployed editor did not become ready")


def deploy(bundle: Path, home: Path, *, upgrade: bool = False, check_only: bool = False, require_existing: bool = False) -> dict:
    require_existing = require_existing or check_only
    uid, gid = os.getuid(), os.getgid()
    if uid < 1000 or not home.is_dir() or home.stat().st_uid != uid:
        raise RuntimeError("Deploy the editor through a non-system SSH account owning its home")
    root = home / ".galaris" / "code-editor"
    marker = root / "upgrade-in-progress"
    if root.resolve() != root or bundle.resolve() != bundle or not bundle.is_relative_to(root):
        raise RuntimeError("The editor deployment directory must stay inside the account home")
    project = f"galaris-code-u{uid}"
    container = f"{project}-runtime"
    revision = hashlib.sha256()
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.name != "compose.json" and not path.name.startswith("."):
            revision.update(path.relative_to(bundle).as_posix().encode())
            revision.update(path.read_bytes())
    digest = revision.hexdigest()
    docker("info", "--format", "{{.OSType}}")
    docker("compose", "version")
    identifiers = docker("ps", "-a", "--filter", f"name=^/{container}$", "--format", "{{.ID}}")
    if check_only and require_existing and not identifiers and not (root / "credential").exists():
        # A manually administered broker is outside this controller's ownership.
        return {"managed": False, "update_required": False, "port": None}
    if require_existing and not (root / "credential").is_file():
        raise RuntimeError("Automatic updates require an existing managed editor credential")
    if require_existing and not identifiers:
        raise RuntimeError("Automatic updates require an existing managed editor")
    token = credential(root)
    already_installed = False
    previous = None
    published_port = None
    if identifiers:
        inspection = json.loads(docker("inspect", container))[0]
        labels = inspection["Config"].get("Labels") or {}
        if labels.get("galaris.code.home") != hashlib.sha256(str(home).encode()).hexdigest():
            raise RuntimeError("The existing editor belongs to a different home")
        if check_only:
            return {"managed": True, "update_required": labels.get("galaris.code.bundle") != digest
                    or not inspection["State"]["Running"] or bool(inspection["State"].get("Paused")),
                    "port": int(inspection["NetworkSettings"]["Ports"]["8766/tcp"][0]["HostPort"])}
        if labels.get("galaris.code.bundle") != digest:
            if not upgrade:
                raise RuntimeError("An older editor is already deployed; preserve its sessions before replacing it")
            previous = inspection
            published_port = int(inspection["NetworkSettings"]["Ports"]["8766/tcp"][0]["HostPort"])
        else:
            already_installed = True
            if not inspection["State"]["Running"]:
                docker("start", container)
            elif upgrade and inspection["State"].get("Paused"):
                docker("unpause", container)
    if not already_installed:
        specification = {"services": {"runtime": {
            "build": {"context": str(bundle), "target": "runtime"},
            "container_name": container,
            "labels": {"galaris.code.bundle": digest, "galaris.code.home": hashlib.sha256(str(home).encode()).hexdigest()},
            "environment": {"CODE_HOME_ROOT": str(home.parent), "CODE_UPGRADE_LOCK_FILE": str(root / "upgrade-in-progress")},
            "volumes": [f"{home}:{home}", f"{root / 'credential'}:/run/galaris-code/token:ro", "profiles:/var/lib/galaris-code"],
            "ports": [{"target": 8766, "host_ip": "127.0.0.1"}],
            "read_only": True, "tmpfs": ["/tmp:size=256m,mode=1777"],
            "cap_drop": ["ALL"],
            "cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETUID", "SETGID", "SETPCAP", "SYS_ADMIN", "NET_ADMIN"],
            "security_opt": ["seccomp=unconfined", "apparmor=unconfined", "systempaths=unconfined", "no-new-privileges:true"],
            "pids_limit": 2048, "mem_limit": "8g", "cpus": 4, "restart": "unless-stopped",
        }}, "volumes": {"profiles": {}}}
        compose = bundle / "compose.json"
        if published_port is not None:
            specification["services"]["runtime"]["ports"][0]["published"] = published_port
        compose.write_text(json.dumps(specification))
        paused = False
        replacement_started = False
        try:
            if previous is not None:
                os.close(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600))
                if previous["State"]["Running"]:
                    # Freeze launches before inspecting processes: another connection
                    # to this Unix account must not race the image replacement.
                    if not previous["State"].get("Paused"):
                        docker("pause", container)
                    paused = True
                    # Docker uses PID to select this container's rows from host ps.
                    processes = docker("top", container, "-eo", "pid,comm").splitlines()[1:]
                    if sorted(value.split(maxsplit=1)[1].strip() for value in processes) != ["python3", "tini"]:
                        raise RuntimeError("End existing editor sessions before updating the editor")
            replacement_started = True
            docker("compose", "-p", project, "-f", str(compose), "up", "-d", "--build", timeout=900, quiet=True)
            port = verify_service(container, uid, gid, token)
        except (RuntimeError, OSError, ValueError):
            if previous is not None and replacement_started:
                specification["services"]["runtime"].pop("build")
                specification["services"]["runtime"]["image"] = previous["Image"]
                specification["services"]["runtime"]["labels"] = previous["Config"]["Labels"]
                compose.write_text(json.dumps(specification))
                docker("compose", "-p", project, "-f", str(compose), "up", "-d", "--no-build", quiet=True)
            raise
        finally:
            if paused and json.loads(docker("inspect", container))[0]["State"].get("Paused"):
                docker("unpause", container)
            if previous is not None:
                marker.unlink(missing_ok=True)
    else:
        port = verify_service(container, uid, gid, token)
        if upgrade:
            marker.unlink(missing_ok=True)
    return {"port": port, "version": VERSION, "already_installed": already_installed}


def main() -> None:
    bundle = Path(__file__).resolve().parent
    home = Path.home().resolve()
    root = home / ".galaris" / "code-editor"
    descriptor = os.open(root / "deploy.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        print(json.dumps(deploy(bundle, home, upgrade="--upgrade" in sys.argv[1:],
            check_only="--check" in sys.argv[1:], require_existing="--require-existing" in sys.argv[1:])))


def run() -> int:
    try:
        main()
    except Exception as error:
        reason = FAILURE_REASONS.get(str(error), "unknown") if isinstance(error, RuntimeError) else "unknown"
        causes = []
        current = error
        seen = set()
        while current is not None and id(current) not in seen and len(causes) < 8:
            seen.add(id(current))
            causes.append({"type": type(current).__name__, "message": diagnostic_text(str(current)),
                "locations": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                              for frame in traceback.extract_tb(current.__traceback__)[-16:]],
                "command": current.details if isinstance(current, DockerCommandError) else None})
            current = current.__cause__ or current.__context__
        print(json.dumps({"error": reason, "diagnostic": causes}))
        # No arbitrary Docker or HTTP response is exposed to application logs.
        print("Editor deployment failed: verify Docker/Compose access, Linux user namespaces and the account home", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
