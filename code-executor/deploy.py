"""Explicit per-account deployment, uploaded by the Console administration action.

Only the approved account home is mounted. The receipt never contains a credential.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request


VERSION = "4.141.0"


def docker(*arguments: str, timeout: int = 30, quiet: bool = False) -> str:
    try:
        result = subprocess.run(["docker", *arguments], check=False, timeout=timeout,
            stdout=subprocess.DEVNULL if quiet else subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise RuntimeError("Docker is unavailable or the deployment command timed out") from None
    if result.returncode:
        raise RuntimeError("Docker access, Compose or the code-server build failed")
    return (result.stdout or "").strip()


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
        return value
    value = secrets.token_urlsafe(48)
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


def deploy(bundle: Path, home: Path, *, upgrade: bool = False) -> dict:
    uid, gid = os.getuid(), os.getgid()
    if uid < 1000 or not home.is_dir() or home.stat().st_uid != uid:
        raise RuntimeError("Deploy the editor through a non-system SSH account owning its home")
    root = home / ".galaris" / "code-editor"
    marker = root / "upgrade-in-progress"
    if root.resolve() != root or bundle.resolve() != bundle or not bundle.is_relative_to(root):
        raise RuntimeError("The editor deployment directory must stay inside the account home")
    token = credential(root)
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
    already_installed = False
    previous = None
    published_port = None
    if identifiers:
        inspection = json.loads(docker("inspect", container))[0]
        labels = inspection["Config"].get("Labels") or {}
        if labels.get("galaris.code.home") != hashlib.sha256(str(home).encode()).hexdigest():
            raise RuntimeError("The existing editor belongs to a different home")
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
                    processes = docker("top", container, "-eo", "comm").splitlines()[1:]
                    if sorted(value.strip() for value in processes) != ["python3", "tini"]:
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
        print(json.dumps(deploy(bundle, home, upgrade="--upgrade" in sys.argv[1:])))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, IndexError):
        # No arbitrary Docker or HTTP response is exposed to application logs.
        print("Editor deployment failed: verify Docker/Compose access, Linux user namespaces and the account home", file=sys.stderr)
        sys.exit(1)
