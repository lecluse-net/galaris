"""Private code-server supervisor; editor children see only approved mounts.

The supervisor is a trusted launcher. Its control credential and state directory
are never mounted in an editor. It does not have a Docker socket or host devices.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import time
from typing import BinaryIO
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout, UnixConnector, WSMsgType, web
from profiles import state_lock

HOME_ROOT = Path(os.environ.get("CODE_HOME_ROOT", "/data/ssh-executor/home")).resolve()
STATE_ROOT = Path(os.environ.get("CODE_STATE_ROOT", "/var/lib/galaris-code"))
TOKEN_PATH = Path(os.environ.get("CODE_TOKEN_FILE", "/run/galaris-code/token"))
UPGRADE_LOCK_PATH = os.environ.get("CODE_UPGRADE_LOCK_FILE")
# The default 8 GiB broker cannot accommodate 64 full IDE processes. Retained
# profiles have a separate bound and never consume an active slot while stopped.
MAX_SESSIONS = 8
MAX_RETAINED_PROFILES = 64
MAX_USER_SESSIONS = 8
LEASE_SECONDS = 600
MAX_LIFETIME_SECONDS = 86400
HOP_HEADERS = frozenset({"connection", "upgrade", "keep-alive", "transfer-encoding",
                         "proxy-authorization", "proxy-authenticate", "te", "trailer",
                         "authorization", "cookie", "set-cookie", "host", "content-length"})


@dataclass
class Editor:
    identifier: str
    fingerprint: str
    uid: int
    process: asyncio.subprocess.Process
    profile: Path
    log_file: BinaryIO
    log_task: asyncio.Task[None]
    started: float
    touched: float


editors: dict[str, Editor] = {}
launch_lock = asyncio.Lock()


def confined_path(raw: object, home: Path, *, directory: bool = True) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("Invalid path")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("An absolute canonical path is required")
    resolved = path.resolve(strict=True)
    if path != resolved or not resolved.is_relative_to(home):
        raise ValueError("Path is outside the approved home or is not canonical")
    if directory and not resolved.is_dir():
        raise ValueError("Expected a directory")
    return resolved


def sandbox_command(
    home: Path, repository: Path, git_paths: list[Path], profile: Path,
    uid: int, gid: int, editable: bool,
    identities: dict[Path, str] | None = None,
) -> tuple[list[str], list[int]]:
    """Hold source directory descriptors until bwrap has created the mounts."""
    descriptors: list[int] = []
    arguments = [
        "bwrap", "--die-with-parent", "--new-session", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts", "--unshare-user",
        "--uid", str(uid), "--gid", str(gid), "--cap-drop", "ALL",
        "--clearenv", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--setenv", "HOME", str(home), "--setenv", "SHELL", "/bin/bash",
        "--setenv", "LANG", "C.UTF-8", "--setenv", "USER", home.name,
        "--setenv", "LOGNAME", home.name,
        "--setenv", "XDG_CONFIG_HOME", "/profile/config",
        "--setenv", "XDG_DATA_HOME", "/profile/data",
        "--setenv", "XDG_CACHE_HOME", "/profile/cache",
        "--setenv", "GIT_OPTIONAL_LOCKS", "1" if editable else "0",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin", "--symlink", "usr/lib", "/lib",
        "--dir", "/etc", "--tmpfs", "/tmp", "--dev", "/dev",
    ]
    if Path("/usr/lib64").exists():
        arguments += ["--symlink", "usr/lib64", "/lib64"]
    for name in ("ssl/certs", "resolv.conf", "hosts", "nsswitch.conf", "localtime"):
        source = Path("/etc") / name
        if source.exists():
            arguments += ["--ro-bind", str(source), str(source)]
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile.parent.chmod(0o711)
    os.chown(profile, uid, gid)
    passwd = profile.parent / "passwd"
    passwd.write_text(f"{home.name}:x:{uid}:{gid}:Editor:{home}:/bin/bash\n")

    def mount(source: Path, destination: Path, writable: bool) -> None:
        descriptor = os.open(source, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(descriptor)
        expected = (identities or {}).get(source)
        info = os.fstat(descriptor)
        if expected is not None and expected != f"{info.st_dev}:{info.st_ino}":
            raise ValueError("Repository mount target changed")
        arguments.extend(["--bind-fd" if writable else "--ro-bind-fd",
                          str(descriptor), str(destination)])

    try:
        mount(passwd, Path("/etc/passwd"), False)
        mount(profile, Path("/profile"), True)
        # Create the home as an empty skeleton: other repositories are not exposed.
        arguments += ["--dir", str(home)]
        for source in sorted({repository, *git_paths}, key=lambda value: len(value.parts)):
            # Already covered by an earlier approved mount.
            if source != repository and source.is_relative_to(repository):
                continue
            mount(source, source, editable)
        if editable:
            for name in (".gitconfig", ".ssh", ".config/git"):
                source = home / name
                if source.exists():
                    canonical = confined_path(str(source), home, directory=False)
                    mount(canonical, canonical, False)
        else:
            arguments += ["--unshare-net"]
        arguments += ["--proc", "/proc", "--chdir", str(repository),
                      "--", "/usr/bin/code-server", "--auth", "none",
                      "--socket", "/profile/editor.sock", "--socket-mode", "0600",
                      "--user-data-dir", "/profile/user-data",
                      "--extensions-dir", "/profile/extensions", "--disable-telemetry",
                      "--disable-update-check", "--disable-proxy", str(repository)]
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise
    return ["/usr/bin/setpriv", "--reuid", str(uid), "--regid", str(gid),
            "--clear-groups", "--bounding-set=-all", "--no-new-privs", *arguments], descriptors


async def stop_editor(editor: Editor) -> None:
    if editor.process.returncode is None:
        try:
            os.killpg(editor.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(editor.process.wait(), 5)
        except TimeoutError:
            try:
                os.killpg(editor.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await editor.process.wait()
    # Profiles are retained for recovery; repository contents are never deleted.
    await asyncio.gather(editor.log_task, return_exceptions=True)
    editor.log_file.close()


async def bounded_log(stream: asyncio.StreamReader, output: BinaryIO) -> None:
    while chunk := await stream.read(65536):
        if output.tell() + len(chunk) > 1024 * 1024:
            output.seek(0)
            output.truncate()
        output.write(chunk)
        output.flush()


async def open_editor(request: web.Request) -> web.Response:
    if UPGRADE_LOCK_PATH and Path(UPGRADE_LOCK_PATH).exists():
        raise web.HTTPServiceUnavailable(text="Editor update in progress")
    data = await request.json()
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Invalid session request")
    identifier = str(UUID(str(data.get("session"))))
    home = Path(str(data.get("home"))).resolve(strict=True)
    if not home.is_relative_to(HOME_ROOT) or home == HOME_ROOT:
        raise web.HTTPForbidden(text="Home outside the configured root")
    info = home.stat()
    uid, gid = info.st_uid, info.st_gid
    if uid < 1000:
        raise web.HTTPForbidden(text="A non-system account is required")
    repository = confined_path(data.get("root"), home)
    if repository == home:
        raise web.HTTPForbidden(text="The complete account home is not a workspace")
    git_raw = data.get("git_paths", [])
    if not isinstance(git_raw, list) or len(git_raw) > 4:
        raise web.HTTPBadRequest(text="Invalid Git metadata")
    git_paths = [confined_path(value, home) for value in git_raw]
    identity = data.get("root_identity")
    git_identities = data.get("git_identities")
    if not isinstance(identity, str) or not isinstance(git_identities, list) or len(git_identities) != len(git_paths) or not all(isinstance(value, str) for value in git_identities):
        raise web.HTTPBadRequest(text="Verified mount identities are required")
    identities = dict(zip([repository, *git_paths], [identity, *git_identities]))
    mode = data.get("mode")
    if mode not in ("read", "edit"):
        raise web.HTTPBadRequest(text="Invalid editor mode")
    fingerprint = json.dumps({"home": str(home), "root": str(repository),
                              "git_paths": [str(value) for value in git_paths], "mode": mode,
                              "identities": [identity, *git_identities]},
                             sort_keys=True)
    async with launch_lock:
        existing = editors.get(identifier)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise web.HTTPConflict(text="Session target cannot change")
            if existing.process.returncode is None and time.monotonic() - existing.started < MAX_LIFETIME_SECONDS:
                existing.touched = time.monotonic()
                return web.json_response({"session": identifier, "state": "ready"})
            await stop_editor(existing)
            del editors[identifier]
        if len(editors) >= MAX_SESSIONS or sum(value.uid == uid for value in editors.values()) >= MAX_USER_SESSIONS:
            raise web.HTTPTooManyRequests(text="Editor session quota reached")
        session_directory = STATE_ROOT / "sessions" / identifier
        manifest_path = session_directory / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("fingerprint") != fingerprint or manifest.get("uid") != uid:
                raise web.HTTPConflict(text="Retained session target cannot change")
        else:
            manifests = list((STATE_ROOT / "sessions").glob("*/manifest.json"))
            if len(manifests) >= MAX_RETAINED_PROFILES:
                raise web.HTTPTooManyRequests(text="Retained profile quota reached; administrator cleanup is required")
        profile = session_directory / "profile"
        profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"session": identifier, "uid": uid,
            "mode": mode, "fingerprint": fingerprint, "started_at": time.time()}))
        arguments, descriptors = sandbox_command(home, repository, git_paths, profile, uid, gid, mode == "edit", identities)
        (profile / "navigation.json").unlink(missing_ok=True)
        # Reset the diagnostic file on launch; a single process cannot grow it indefinitely.
        log_file = (profile.parent / "runtime.log").open("wb")
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                pass_fds=descriptors, start_new_session=True,
            )
        except BaseException:
            log_file.close()
            raise
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
        now = time.monotonic()
        assert process.stdout is not None
        log_task = asyncio.create_task(bounded_log(process.stdout, log_file))
        editor = Editor(identifier, fingerprint, uid, process, profile, log_file, log_task, now, now)
        editors[identifier] = editor
        socket_path = profile / "editor.sock"
        try:
            async with asyncio.timeout(45):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError("Editor process exited")
                    try:
                        if stat.S_ISSOCK(socket_path.lstat().st_mode):
                            async with ClientSession(connector=UnixConnector(path=str(socket_path))) as client:
                                async with client.get("http://localhost/healthz") as response:
                                    if response.status == 200:
                                        break
                    except (OSError, ConnectionError):
                        pass
                    await asyncio.sleep(0.1)
        except BaseException:
            await stop_editor(editor)
            editors.pop(identifier, None)
            raise
        return web.json_response({"session": identifier, "state": "ready"})


async def close_editor(request: web.Request) -> web.Response:
    identifier = str(UUID(request.match_info["session"]))
    async with launch_lock:
        editor = editors.pop(identifier, None)
        if editor is not None:
            await stop_editor(editor)
        if request.query.get("discard") == "true":
            directory = STATE_ROOT / "sessions" / identifier
            if directory.exists():
                # Only this explicit human action discards the IDE profile, never the checkout.
                shutil.rmtree(directory)
    return web.json_response({"session": identifier, "state": "closed"})


async def touch_editor(request: web.Request) -> web.Response:
    identifier = str(UUID(request.match_info["session"]))
    editor = editors.get(identifier)
    if editor is None or editor.process.returncode is not None or time.monotonic() - editor.started >= MAX_LIFETIME_SECONDS:
        raise web.HTTPGone(text="Editor session is unavailable")
    editor.touched = time.monotonic()
    return web.json_response({"session": identifier, "state": "ready"})


async def proxy(request: web.Request) -> web.StreamResponse:
    identifier = str(UUID(request.match_info["session"]))
    editor = editors.get(identifier)
    if editor is None or editor.process.returncode is not None:
        raise web.HTTPGone(text="Editor session is unavailable")
    editor.touched = time.monotonic()
    path = "/" + request.match_info.get("path", "")
    if request.query_string:
        path += "?" + request.query_string
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_HEADERS}
    if request.match_info.get("path", "") == "":
        headers["Accept-Encoding"] = "identity"
    for name in list(headers):
        if name.lower().startswith("sec-websocket-"):
            headers.pop(name)
    connector = UnixConnector(path=str(editor.profile / "editor.sock"))
    async with ClientSession(connector=connector, auto_decompress=False, timeout=ClientTimeout(total=None, sock_connect=10)) as client:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            protocols = tuple(part.strip() for part in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if part.strip())
            async with client.ws_connect("http://localhost" + path, headers=headers, protocols=protocols, max_msg_size=16 * 1024 * 1024) as upstream:
                downstream = web.WebSocketResponse(protocols=protocols, max_msg_size=16 * 1024 * 1024)
                await downstream.prepare(request)

                async def pump(source, destination) -> None:
                    async for message in source:
                        editor.touched = time.monotonic()
                        if message.type == WSMsgType.BINARY:
                            await destination.send_bytes(message.data)
                        elif message.type == WSMsgType.TEXT:
                            await destination.send_str(message.data)
                        elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                            break
                    await destination.close()

                tasks = [asyncio.create_task(pump(downstream, upstream)), asyncio.create_task(pump(upstream, downstream))]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await downstream.close()
                return downstream
        async with client.request(request.method, "http://localhost" + path, headers=headers, data=request.content, allow_redirects=False) as upstream:
            response_headers = {key: value for key, value in upstream.headers.items() if key.lower() not in HOP_HEADERS}
            origin = request.headers.get("X-Galaris-Application-Origin")
            if origin and upstream.status == 200 and request.match_info.get("path", "") == "" and "text/html" in upstream.headers.get("Content-Type", ""):
                content = bytearray()
                async for chunk in upstream.content.iter_chunked(65536):
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise web.HTTPBadGateway(text="Editor bootstrap too large")
                payload = json.dumps({"type": "galaris.code.ready", "session": identifier}).replace("<", "\\u003c")
                target = json.dumps(origin).replace("<", "\\u003c")
                script = f"<script>(()=>{{const ready=()=>{{if(!document.querySelector('.monaco-workbench'))return false;parent.postMessage({payload},{target});return true}};if(!ready()){{const observer=new MutationObserver(()=>{{if(ready())observer.disconnect()}});observer.observe(document.documentElement,{{childList:true,subtree:true}})}}}})();</script>"
                content = content.replace(b"</body>", script.encode() + b"</body>")
                response_headers.pop("Content-Encoding", None)
                return web.Response(body=content, status=200, headers=response_headers)
            response = web.StreamResponse(status=upstream.status, headers=response_headers)
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(65536):
                await response.write(chunk)
            return response


@web.middleware
async def authenticate(request: web.Request, handler):
    token = TOKEN_PATH.read_text().strip()
    if not token or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
        raise web.HTTPForbidden(text="Runtime authentication required")
    try:
        return await handler(request)
    except (ValueError, FileNotFoundError, KeyError):
        raise web.HTTPBadRequest(text="Invalid runtime target") from None
    except (RuntimeError, TimeoutError):
        raise web.HTTPBadGateway(text="Editor runtime could not start") from None


def write_profile_request(profile: Path, uid: int, gid: int, name: str, data: dict[str, object]) -> None:
    # Never follow an editor-created symlink with the privileged broker.
    directory = os.open(profile, os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = "navigation-" + str(time.time_ns())
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            os.fchown(descriptor, uid, gid)
            os.write(descriptor, json.dumps({**data, "sequence": str(time.time_ns())}).encode())
        finally:
            os.close(descriptor)
        os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        os.close(directory)


def write_navigation(profile: Path, uid: int, gid: int, data: dict[str, object]) -> None:
    write_profile_request(profile, uid, gid, "navigation.json", data)


async def navigate(request: web.Request) -> web.Response:
    editor = editors.get(str(UUID(request.match_info["session"])))
    if editor is None:
        raise web.HTTPGone(text="Editor unavailable")
    data = await request.json()
    file = data.get("file")
    if (file is not None and (not isinstance(file, str) or Path(file).is_absolute()
        or ".." in Path(file).parts or "\\" in file or len(file) > 1024 or any(ord(char) < 32 for char in file))
        or data.get("view") not in ("files", "changes")):
        raise web.HTTPBadRequest(text="Invalid navigation")
    write_navigation(editor.profile, editor.uid, editor.profile.stat().st_gid, {"file": file, "view": data["view"]})
    return web.json_response({"state": "requested"})


async def lifetime(app: web.Application):
    with state_lock(STATE_ROOT):
        async for value in supervised_lifetime(app):
            yield value


async def supervised_lifetime(app: web.Application):
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_ROOT, 0o711)
    (STATE_ROOT / "sessions").mkdir(mode=0o711, exist_ok=True)

    async def reap() -> None:
        while True:
            await asyncio.sleep(10)
            now = time.monotonic()
            async with launch_lock:
                for identifier, editor in list(editors.items()):
                    if editor.process.returncode is not None or now - editor.touched > LEASE_SECONDS or now - editor.started > MAX_LIFETIME_SECONDS:
                        editors.pop(identifier, None)
                        await stop_editor(editor)

    worker = asyncio.create_task(reap())
    yield
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    for editor in list(editors.values()):
        await stop_editor(editor)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ready": True, "protocol": 1, "version": "4.141.0"})


def main() -> None:
    app = web.Application(middlewares=[authenticate], client_max_size=8 * 1024 * 1024)
    app.cleanup_ctx.append(lifetime)
    app.router.add_get("/health", health)
    app.router.add_post("/sessions", open_editor)
    app.router.add_delete("/sessions/{session}", close_editor)
    app.router.add_post("/sessions/{session}/touch", touch_editor)
    app.router.add_post("/sessions/{session}/navigate", navigate)
    app.router.add_route("*", "/sessions/{session}/editor/{path:.*}", proxy)
    web.run_app(app, host=os.environ.get("CODE_BIND_HOST", "0.0.0.0"),
                port=int(os.environ.get("CODE_BIND_PORT", "8766")), access_log=None)


if __name__ == "__main__":
    main()
