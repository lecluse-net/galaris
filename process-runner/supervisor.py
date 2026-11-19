"""Dedicated host control plane for disposable Process Python sandboxes."""

from contextlib import suppress
from dataclasses import dataclass, field
import fcntl
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
from threading import BoundedSemaphore, Condition, Lock, Thread, Timer
import time
from typing import Any
from uuid import UUID

MAX_MESSAGE = 2_000_000
MAX_CALLS = 16
RETENTION = 86_400
LABEL = "io.galaris.process-python=true"
DOCKER = ("docker", "--host", "unix:///var/run/docker.sock")
LOGGER = logging.getLogger("process-runner")
JSON = dict[str, Any]


def encode(value: JSON) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode() + b"\n"


def invalid_number(_value: str) -> None:
    raise ValueError("Non-finite numbers are forbidden")


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*DOCKER, *args], stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=10, check=True)


@dataclass
class Job:
    identity: str
    invocation: JSON
    condition: Condition = field(default_factory=Condition)
    cancelled: bool = False
    call: JSON | None = None
    reply: bytes | None = None
    delivered: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return "galaris-python-" + self.identity

    def observation(self) -> JSON:
        with self.condition:
            return {"status": "running", "stopped": False, "capability_call": self.call}


class Supervisor:
    def __init__(self, image: str, storage: Path) -> None:
        if not re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("Provide an immutable sandbox image reference")
        if "runsc" not in json.loads(docker("info", "--format", "{{json .Runtimes}}").stdout):
            raise RuntimeError("Docker must provide the runsc runtime")
        docker("image", "inspect", "--format", "{{.Id}}", image)
        self.image = image
        storage.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.owner = (storage / "owner.lock").open("a")
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db = sqlite3.connect(storage / "invocations.sqlite3", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, signature TEXT, receipt BLOB, updated REAL)")
        self.lock = Lock()
        self.active: dict[str, Job] = {}
        # A restarted supervisor must prove the old sandbox is gone before offering a terminal receipt.
        for name in docker("container", "ls", "--all", "--filter", f"label={LABEL}", "--format", "{{.Names}}").stdout.splitlines():
            if not re.fullmatch(r"galaris-python-[0-9a-f-]{36}", name):
                raise RuntimeError("Unexpected Process sandbox name")
            docker("container", "rm", "--force", name)
        with self.db:
            self.db.execute("UPDATE jobs SET receipt = ?, updated = ? WHERE receipt IS NULL",
                            (encode({"status": "error", "stopped": True}), time.time()))

    def _read(self, identity: str) -> tuple[str | None, bytes | None] | None:
        return self.db.execute("SELECT signature, receipt FROM jobs WHERE id = ?", (identity,)).fetchone()

    def submit(self, identity: str, payload: JSON) -> JSON:
        if (set(payload) != {"phase", "source", "values", "handles"} or payload["phase"] != "activity"
                or not isinstance(payload["source"], str) or len(payload["source"]) > 200_000
                or not isinstance(payload["values"], dict) or not isinstance(payload["handles"], dict)
                or len(payload["handles"]) > 16):
            raise ValueError("Invalid invocation")
        signature = sha256(encode(payload)).hexdigest()
        with self.lock:
            saved = self._read(identity)
            if saved is not None:
                digest, receipt = saved
                if digest is not None and digest != signature:
                    raise ValueError("Invocation inputs changed")
                return json.loads(receipt) if receipt else self.active[identity].observation()
            with self.db:
                self.db.execute("DELETE FROM jobs WHERE receipt IS NOT NULL AND updated < ?", (time.time() - RETENTION,))
                if len(self.active) >= 4 or self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 1024:
                    raise OverflowError("Runner capacity exhausted")
                self.db.execute("INSERT INTO jobs VALUES (?, ?, NULL, ?)", (identity, signature, time.time()))
            job = Job(identity, payload)
            self.active[identity] = job
            Thread(target=self._execute, args=(job,), daemon=True).start()
            return job.observation()

    def observe(self, identity: str) -> JSON:
        with self.lock:
            job = self.active.get(identity)
            if job is not None:
                return job.observation()
            saved = self._read(identity)
            return json.loads(saved[1]) if saved and saved[1] else {"status": "unknown", "stopped": False}

    def cancel(self, identity: str) -> JSON:
        with self.lock:
            job = self.active.get(identity)
            if job is None:
                saved = self._read(identity)
                if saved and saved[1]:
                    return json.loads(saved[1])
                result = {"status": "cancelled", "stopped": True}
                with self.db:
                    self.db.execute("INSERT INTO jobs VALUES (?, NULL, ?, ?)", (identity, encode(result), time.time()))
                return result
            with job.condition:
                job.cancelled = True
                job.condition.notify_all()
        return job.observation()

    def reply(self, identity: str, call_id: str, payload: JSON) -> JSON:
        if payload.get("status") not in ("completed", "rejected") or set(payload) - {"status", "output", "error"}:
            raise ValueError("Invalid capability reply")
        content = encode(payload)
        digest = sha256(content).hexdigest()
        with self.lock:
            job = self.active.get(identity)
            if job is not None:
                with job.condition:
                    if job.delivered.get(call_id) == digest:
                        pass
                    elif job.cancelled or job.call is None or job.call["id"] != call_id or call_id in job.delivered:
                        raise ValueError("The capability call is no longer waiting for this reply")
                    else:
                        job.delivered[call_id] = digest
                        job.reply = content
                        job.condition.notify_all()
        return self.observe(identity)

    def _execute(self, job: Job) -> None:
        process: subprocess.Popen[bytes] | None = None
        created = False
        creation_uncertain = False
        timed_out = False
        result = {"status": "error", "stopped": True}

        def deadline() -> None:
            nonlocal timed_out
            with job.condition:
                timed_out = True
                job.condition.notify_all()

        def interrupt(attached: subprocess.Popen[bytes]) -> None:
            with job.condition:
                job.condition.wait_for(lambda: job.cancelled or timed_out or attached.poll() is not None)
                if not job.cancelled and not timed_out:
                    return
            # Even if Docker cannot respond, close the attach channel. Final
            # reconciliation still requires verified container removal below.
            attached.kill()

        timer = Timer(900, deadline)
        try:
            # The Docker cgroup also counts gVisor and OCI hook threads. RLIMIT_NPROC
            # separately caps the unprivileged script and its descendants inside gVisor.
            docker("container", "create", "--name", job.name, "--label", LABEL, "--runtime=runsc", "--pull=never",
                "--network=none", "--read-only", "--user=65532:65532", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--memory=128m", "--memory-swap=128m",
                "--cpus=0.5", "--pids-limit=128", "--ulimit=nproc=16:16", "--log-driver=none",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777", "-i", self.image)
            created = True
            with job.condition:
                if job.cancelled:
                    return
                process = subprocess.Popen([*DOCKER, "container", "start", "--attach", "--interactive", job.name],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                Thread(target=interrupt, args=(process,), daemon=True).start()
                timer.start()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(encode(job.invocation))
            process.stdin.flush()
            handles = set(job.invocation["handles"].values())
            while True:
                raw = process.stdout.readline(MAX_MESSAGE + 1)
                if not raw or len(raw) > MAX_MESSAGE:
                    break
                frame = json.loads(raw, parse_constant=invalid_number)
                if set(frame) == {"result"} and isinstance(frame["result"], dict):
                    process.stdin.close()
                    if not process.stdout.read(1) and process.wait(timeout=5) == 0:
                        candidate = {"status": "success", "stopped": True, "result": frame["result"]}
                        if len(encode({"invocation_id": job.identity, **candidate})) <= MAX_MESSAGE:
                            result = candidate
                    break
                if set(frame) != {"call"}:
                    break
                call = frame["call"]
                if (not isinstance(call, dict) or set(call) != {"id", "handle", "arguments"}
                        or not isinstance(call["arguments"], dict) or call["handle"] not in handles
                        or str(UUID(call["id"])) != call["id"]):
                    break
                with job.condition:
                    if len(job.delivered) >= MAX_CALLS or call["id"] in job.delivered:
                        break
                    job.call = call
                    job.condition.wait_for(lambda: job.reply is not None or job.cancelled or timed_out)
                    reply = job.reply
                    job.call = job.reply = None
                if reply is None:
                    break
                process.stdin.write(reply)
                process.stdin.flush()
        except subprocess.TimeoutExpired:
            creation_uncertain = not created
            LOGGER.warning("Docker command timed out for invocation %s (created=%s)", job.identity, created)
        except (OSError, ValueError, TypeError, RecursionError, subprocess.SubprocessError) as error:
            # Never publish raw Python output or Docker command details.
            LOGGER.warning("Invocation %s failed (%s)", job.identity, type(error).__name__)
        finally:
            timer.cancel()
            if process is not None:
                process.kill()
                process.wait()
                with job.condition:
                    job.condition.notify_all()
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        with suppress(OSError):
                            pipe.close()
            self._remove(job, creation_uncertain)
            with self.lock:
                if job.cancelled:
                    result = {"status": "cancelled", "stopped": True}
                with self.db:
                    self.db.execute("UPDATE jobs SET receipt = ?, updated = ? WHERE id = ?",
                                    (encode(result), time.time(), job.identity))
                self.active.pop(job.identity)

    @staticmethod
    def _remove(job: Job, creation_uncertain: bool) -> None:
        """Keep the slot occupied until the daemon confirms removal or absence."""
        delay = 1
        while True:
            try:
                names = docker("container", "ls", "--all", "--filter", f"label={LABEL}",
                               "--format", "{{.Names}}").stdout.splitlines()
                if job.name in names:
                    # After observing it, an absent sandbox also confirms a lost removal reply.
                    creation_uncertain = False
                    docker("container", "rm", "--force", job.name)
                    return
                if not creation_uncertain:
                    return
            except (OSError, subprocess.SubprocessError) as error:
                reason = type(error).__name__
            else:
                reason = "container creation unconfirmed"
            if delay == 1:
                LOGGER.warning("Sandbox stop unconfirmed for invocation %s (%s); retrying", job.identity, reason)
            time.sleep(delay)
            delay = min(2 * delay, 30)


class RunnerServer(ThreadingHTTPServer):
    slots = BoundedSemaphore(12)
    daemon_threads = True

    def __init__(self, supervisor: Supervisor, token: str, tls: ssl.SSLContext) -> None:
        self.supervisor = supervisor
        self.token = token.encode("ascii")
        self.tls = tls
        super().__init__(("0.0.0.0", 8443), RunnerHandler)

    def process_request(self, request, address) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address) -> None:
        try:
            with self.tls.wrap_socket(request, server_side=True) as secured:
                super().process_request_thread(secured, address)
        except (OSError, ssl.SSLError):
            self.shutdown_request(request)
        finally:
            self.slots.release()

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(4)
        return request, address


class RunnerHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def _respond(self, status: int, data: JSON) -> None:
        content = encode(data)
        if len(content) > MAX_MESSAGE:
            status, content = 422, b"{}\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle(self) -> None:
        auth = self.headers.get("Authorization", "").encode("ascii", errors="replace")
        if not hmac.compare_digest(auth, b"Bearer " + self.server.token):
            self._respond(401, {})
            return
        match = re.fullmatch(r"/v1/invocations/([0-9a-f-]{36})(?:/calls/([0-9a-f-]{36}))?", self.path)
        if match is None:
            self._respond(404, {})
            return
        identity, call_id = match.groups()
        runner = self.server.supervisor
        try:
            if str(UUID(identity)) != identity or (call_id is not None and str(UUID(call_id)) != call_id):
                raise ValueError("Invalid request identity")
            if self.command == "PUT":
                size = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < size <= MAX_MESSAGE:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(size), parse_constant=invalid_number)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid request payload")
                result = runner.reply(identity, call_id, payload) if call_id else runner.submit(identity, payload)
            elif call_id is not None:
                self._respond(404, {})
                return
            else:
                result = runner.cancel(identity) if self.command == "DELETE" else runner.observe(identity)
        except (TypeError, ValueError, RecursionError):
            self._respond(409, {})
            return
        except OverflowError:
            self._respond(429, {})
            return
        self._respond(200, {"invocation_id": identity, **result})

    do_GET = do_PUT = do_DELETE = _handle


def main() -> None:
    token = Path("/run/runner/token").read_text().strip()
    if len(token) < 32 or not token.isascii() or not token.isprintable() or any(char.isspace() for char in token):
        raise ValueError("A dedicated service credential is required")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain("/run/runner/tls.crt", "/run/runner/tls.key")
    supervisor = Supervisor(os.environ["PROCESS_PYTHON_IMAGE"], Path("/var/lib/process-runner"))
    with RunnerServer(supervisor, token, tls) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
