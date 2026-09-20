"""AsyncSSH implementation of the console execution contract."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

import asyncssh
from loguru import logger
from app.tools.contracts import ToolCallRejectedError

from .contracts import ConsoleResult, ConsoleStatus, SshConnectionConfig

_OUTPUT_LIMIT = 512 * 1024
_READ_CHUNK = 64 * 1024
_IDLE_CLOSE_SECONDS = 60.0
_DETECTED_COMMANDS = ("git", "python3", "bash", "rsync", "curl", "jq")
_DEPLOYED_HELPER_RELATIVE = PurePosixPath(".galaris/bin/galaris-exec")
_HELPER_VERSION_PREFIX = "galaris-exec "


def _known_hosts_data(config: SshConnectionConfig) -> bytes:
    value = config.known_host_key.strip()
    first = value.split(maxsplit=1)[0] if value else ""
    if first.startswith(("ssh-", "ecdsa-", "sk-", "rsa-sha2-")):
        host = config.host if config.port == 22 else f"[{config.host}]:{config.port}"
        value = f"{host} {value}"
    return (value.rstrip() + "\n").encode("utf-8")


async def _read_bounded(stream: Any, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    stored = 0
    truncated = False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            break
        raw = chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
        remaining = limit - stored
        if remaining > 0:
            kept = raw[:remaining]
            chunks.append(kept)
            stored += len(kept)
        if len(raw) > max(remaining, 0):
            truncated = True
    return b"".join(chunks), truncated


class SshExecutionTransport:
    """Pooled SSH connection with bounded-output command execution."""

    def __init__(self, config: SshConnectionConfig) -> None:
        self.config = config
        self._connection: Any | None = None
        self._connect_lock = asyncio.Lock()
        self._idle_handle: asyncio.TimerHandle | None = None
        self._home: str | None = None
        self._helper_checked = False
        self._helper_path: str | None = None
        self._helper_version: str | None = None
        self._active_runs: set[UUID] = set()

    async def _new_connection(self) -> Any:
        passphrase = (
            self.config.private_key_passphrase.get_secret_value()
            if self.config.private_key_passphrase is not None
            else None
        )
        key = asyncssh.import_private_key(
            self.config.private_key.get_secret_value(),
            passphrase=passphrase,
        )
        return await asyncio.wait_for(
            asyncssh.connect(
                self.config.host,
                port=self.config.port,
                username=self.config.username,
                client_keys=[key],
                known_hosts=_known_hosts_data(self.config),
                agent_path=None,
            ),
            timeout=self.config.connect_timeout_s,
        )

    def _schedule_idle_close(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
        loop = asyncio.get_running_loop()
        self._idle_handle = loop.call_later(
            _IDLE_CLOSE_SECONDS,
            lambda: asyncio.create_task(self.close()),
        )

    async def connection(self) -> Any:
        async with self._connect_lock:
            if self._connection is None or self._connection.is_closed():
                self._connection = await self._new_connection()
            self._schedule_idle_close()
            return self._connection

    async def close(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
            await connection.wait_closed()

    async def _simple(self, command: str, timeout_s: float = 10.0) -> Any:
        connection = await self.connection()
        return await asyncio.wait_for(
            connection.run(command, check=False),
            timeout=timeout_s,
        )

    async def home(self) -> str:
        if self._home is None:
            result = await self._simple("printf '%s' \"$HOME\"")
            home = str(result.stdout or "").strip()
            if result.exit_status != 0 or not home.startswith("/"):
                raise RuntimeError("Unable to discover the remote Unix home")
            self._home = home.rstrip("/") or "/"
        return self._home

    async def resolve_path(self, value: str = ".", *, must_exist: bool = True) -> tuple[str, str]:
        home = await self.home()
        clean = (value or ".").strip().replace("\\", "/")
        if clean == "~":
            clean = "."
        elif clean.startswith("~/"):
            clean = clean[2:]
        candidate = PurePosixPath(clean)
        if candidate.is_absolute():
            absolute = candidate
        else:
            absolute = PurePosixPath(home) / candidate
        if ".." in absolute.parts:
            raise ValueError("Path traversal outside the SSH home is not allowed")

        connection = await self.connection()
        sftp = await connection.start_sftp_client()
        try:
            real_home = str(await sftp.realpath(home)).rstrip("/") or "/"
            if must_exist:
                real = str(await sftp.realpath(str(absolute)))
            else:
                parent = str(await sftp.realpath(str(absolute.parent)))
                real = str(PurePosixPath(parent) / absolute.name)
        finally:
            sftp.exit()
        if real != real_home and not real.startswith(real_home + "/"):
            raise ValueError("Path resolves outside the SSH home")
        relative = PurePosixPath(real).relative_to(PurePosixPath(real_home)).as_posix()
        return real, relative or "."

    @staticmethod
    def _inside_home(home: str, path: str) -> bool:
        root = home.rstrip("/") or "/"
        return path == root or path.startswith(root + "/")

    async def _working_helper(self) -> str | None:
        if self._helper_checked:
            return self._helper_path

        home = await self.home()
        deployed = str(PurePosixPath(home) / _DEPLOYED_HELPER_RELATIVE)
        candidates: list[str] = []
        deployed_probe = await self._simple(
            f"test -x {shlex.quote(deployed)}",
        )
        if deployed_probe.exit_status == 0:
            candidates.append(deployed)

        discovered = await self._simple("command -v galaris-exec 2>/dev/null")
        discovered_path = str(discovered.stdout or "").strip()
        if (
            discovered.exit_status == 0
            and PurePosixPath(discovered_path).is_absolute()
            and discovered_path not in candidates
        ):
            candidates.append(discovered_path)

        self._helper_path = None
        self._helper_version = None
        for candidate in candidates:
            result = await self._simple(f"{shlex.quote(candidate)} --version")
            version = str(result.stdout or "").strip()
            if result.exit_status == 0 and version.startswith(_HELPER_VERSION_PREFIX):
                candidate_version = version.removeprefix(_HELPER_VERSION_PREFIX)
                # A legacy user installation must not mask the recoverable system helper.
                if self._helper_path is None or candidate_version == "2":
                    self._helper_path = candidate
                    self._helper_version = candidate_version
                if candidate_version == "2":
                    break
        self._helper_checked = True
        return self._helper_path

    async def _has_helper(self) -> bool:
        return await self._working_helper() is not None

    async def supports_recovery(self) -> bool:
        return await self._working_helper() is not None and self._helper_version == "2"

    async def install_helper(self, payload: bytes, *, expected_version: str) -> str:
        """Atomically install and verify the user-scoped enhanced-console helper."""
        if not payload:
            raise ValueError("The galaris-exec payload is empty")
        home = await self.home()
        connection = await self.connection()
        sftp = await connection.start_sftp_client()
        temporary = ""
        try:
            real_home = str(await sftp.realpath(home)).rstrip("/") or "/"
            current = real_home
            for part in (".galaris", "bin"):
                candidate = str(PurePosixPath(current) / part)
                try:
                    await sftp.lstat(candidate)
                except asyncssh.SFTPNoSuchFile:
                    await sftp.mkdir(candidate)
                resolved = str(await sftp.realpath(candidate))
                if not self._inside_home(real_home, resolved):
                    raise ValueError("The galaris-exec install path leaves the SSH home")
                await sftp.chmod(resolved, 0o700)
                current = resolved

            destination = str(PurePosixPath(current) / "galaris-exec")
            temporary = str(
                PurePosixPath(current) / f".galaris-exec.part-{uuid4().hex}"
            )
            async with sftp.open(temporary, "wb", encoding=None) as output:
                await output.write(payload)
            await sftp.chmod(temporary, 0o700)

            expected_output = f"{_HELPER_VERSION_PREFIX}{expected_version}"
            staged = await self._simple(f"{shlex.quote(temporary)} --version")
            if (
                staged.exit_status != 0
                or str(staged.stdout or "").strip() != expected_output
            ):
                detail = str(staged.stderr or staged.stdout or "").strip()
                raise RuntimeError(
                    "The uploaded galaris-exec helper cannot run"
                    + (f": {detail}" if detail else "")
                )

            try:
                await sftp.posix_rename(temporary, destination)
            except asyncssh.SFTPOpUnsupported:
                try:
                    await sftp.remove(destination)
                except asyncssh.SFTPNoSuchFile:
                    pass
                await sftp.rename(temporary, destination)
            temporary = ""
        except BaseException:
            if temporary:
                try:
                    await sftp.remove(temporary)
                except (asyncssh.SFTPError, OSError):
                    pass
            raise
        finally:
            sftp.exit()

        self._helper_checked = False
        self._helper_path = None
        self._helper_version = None
        installed = await self._working_helper()
        # Detection refreshes the cache across the await; discard the earlier None narrowing.
        installed_version = cast(str | None, self._helper_version)
        if installed != destination or installed_version != expected_version:
            raise RuntimeError("The installed galaris-exec helper was not detected")
        return destination

    async def status(self) -> ConsoleStatus:
        try:
            connection = await self.connection()
            home = await self.home()
            sftp = await connection.start_sftp_client()
            test_path = str(PurePosixPath(home) / f".galaris-write-test-{uuid4().hex}")
            writable = False
            try:
                async with sftp.open(test_path, "wb") as output:
                    await output.write(b"ok")
                await sftp.remove(test_path)
                writable = True
            finally:
                sftp.exit()
            probe = " ; ".join(
                f"command -v {shlex.quote(name)} >/dev/null 2>&1 && printf '{name}\\n'"
                for name in _DETECTED_COMMANDS
            )
            commands_result = await self._simple(probe)
            detected = [
                item for item in str(commands_result.stdout or "").splitlines() if item
            ]
            enhanced = await self._has_helper()
            mode = "enhanced" if enhanced else "standard"
            return ConsoleStatus(
                reachable=True,
                authenticated=True,
                host_key_verified=True,
                home=home,
                home_writable=writable,
                sftp_available=True,
                galaris_exec_available=enhanced,
                operation_recovery_available=self._helper_version == "2",
                mode=mode,
                detected_commands=detected,
            )
        except Exception as exc:
            logger.warning(
                "SSH console status failed for connection {}: {}",
                self.config.connection_id,
                exc,
            )
            return ConsoleStatus(
                reachable=False,
                authenticated=False,
                host_key_verified=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def exec(
        self,
        command: str,
        cwd: str = ".",
        timeout_s: float | None = None,
        *,
        stdin: bytes | None = None,
    ) -> ConsoleResult:
        if not command.strip():
            raise ToolCallRejectedError("Command must not be empty")
        absolute_cwd, relative_cwd = await self.resolve_path(cwd)
        shell_command = (
            f"cd -- {shlex.quote(absolute_cwd)} && "
            f"exec /bin/bash -c {shlex.quote(command)}"
        )
        connection = await self.connection()
        started = time.perf_counter()
        process = await connection.create_process(shell_command, encoding=None)
        if stdin is not None:
            process.stdin.write(stdin)
        process.stdin.write_eof()
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, _OUTPUT_LIMIT))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, _OUTPUT_LIMIT))
        timed_out = False
        limit = timeout_s if timeout_s is not None else self.config.command_timeout_s
        limit = max(1.0, min(float(limit), 86400.0))
        try:
            async with asyncio.timeout(limit):
                await process.wait_closed()
        except TimeoutError:
            timed_out = True
            process.close()
            await process.wait_closed()
        except BaseException:
            process.close()
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        stdout_data, stdout_truncated = await stdout_task
        stderr_data, stderr_truncated = await stderr_task
        exit_code = process.exit_status
        status = (
            "outcome_unknown"
            if timed_out or exit_code is None or exit_code < 0
            else "completed"
            if exit_code == 0
            else "failed"
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "SSH console command: connection={} host={} duration_ms={} status={} exit_code={}",
            self.config.connection_id,
            self.config.host,
            duration_ms,
            status,
            exit_code,
        )
        return ConsoleResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout_data.decode("utf-8", errors="replace"),
            stderr=stderr_data.decode("utf-8", errors="replace"),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=duration_ms,
            cwd=relative_cwd,
        )

    async def _require_helper(self) -> str:
        helper = await self._working_helper()
        if helper is None:
            raise ToolCallRejectedError("This SSH target does not provide galaris-exec")
        return helper

    @staticmethod
    def _session_result(result: ConsoleResult, expected_run_id: UUID | None = None) -> ConsoleResult:
        if result.exit_code != 0:
            raise RuntimeError("The console helper returned no acknowledged operation receipt")
        try:
            payload = cast(dict[str, Any], json.loads(result.stdout))
            receipt = ConsoleResult.model_validate(payload)
            if receipt.run_id is None or (expected_run_id is not None and receipt.run_id != expected_run_id):
                raise ValueError("The console receipt does not match the requested operation")
            return receipt
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("Invalid response from galaris-exec") from exc

    async def start(
        self,
        command: str,
        cwd: str = ".",
        *,
        task_id: UUID | None = None,
        operation_id: UUID | None = None,
    ) -> ConsoleResult:
        helper_path = await self._require_helper()
        if operation_id is not None and not await self.supports_recovery():
            raise ToolCallRejectedError("Install galaris-exec version 2 to use recoverable console operations")
        absolute_cwd, _relative = await self.resolve_path(cwd)
        helper = (
            f"{shlex.quote(helper_path)} start --cwd "
            f"{shlex.quote(absolute_cwd)} "
            f"{'--task-id ' + str(task_id) + ' ' if task_id is not None else ''}"
            f"{'--run-id ' + str(operation_id) + ' ' if operation_id is not None else ''}"
            f"-- {shlex.quote(command)}"
        )
        result = self._session_result(await self.exec(helper, "."), operation_id)
        if result.run_id is not None and result.status == "running":
            self._active_runs.add(result.run_id)
        return result

    async def exec_operation(
        self, command: str, *, operation_id: UUID, task_id: UUID | None,
        cwd: str = ".", timeout_s: float | None = None,
    ) -> ConsoleResult:
        if not await self.supports_recovery():
            # Standard SSH remains available, with conservative unknown-outcome handling.
            return await self.exec(command, cwd, timeout_s)
        result = await self.start(command, cwd, task_id=task_id, operation_id=operation_id)
        deadline = time.monotonic() + max(1.0, min(timeout_s if timeout_s is not None else self.config.command_timeout_s, 86400.0))
        while result.status == "running" and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            result = await self.poll(operation_id)
        if result.status == "running":
            result = await self.stop(operation_id)
            if result.status != "outcome_unknown":
                result = result.model_copy(update={"status": "timed_out"})
        return result

    async def recover_operation(
        self,
        operation_id: UUID,
        *,
        allow_running: bool = False,
    ) -> ConsoleResult | None:
        if not await self.supports_recovery():
            return None
        result = await self.poll(operation_id)
        if result.run_id != operation_id or result.status == "outcome_unknown":
            return None
        if result.status == "running" and not allow_running:
            return None
        return result

    async def poll(self, run_id: UUID, cursor: int = 0) -> ConsoleResult:
        helper_path = await self._require_helper()
        helper = (
            f"{shlex.quote(helper_path)} poll --run-id {run_id} "
            f"--cursor {max(0, cursor)}"
        )
        result = self._session_result(await self.exec(helper, "."), run_id)
        if result.status != "running":
            self._active_runs.discard(run_id)
        return result

    async def write(self, run_id: UUID, data: str) -> ConsoleResult:
        helper_path = await self._require_helper()
        helper = f"{shlex.quote(helper_path)} write --run-id {run_id}"
        return self._session_result(
            await self.exec(helper, ".", stdin=data.encode("utf-8")), run_id
        )

    async def stop(self, run_id: UUID) -> ConsoleResult:
        helper_path = await self._require_helper()
        helper = f"{shlex.quote(helper_path)} stop --run-id {run_id}"
        try:
            return self._session_result(await self.exec(helper, "."), run_id)
        finally:
            self._active_runs.discard(run_id)

    async def cancel_active(self) -> None:
        """Best-effort cancellation of enhanced runs started by this task action."""
        run_ids = tuple(self._active_runs)
        if not run_ids:
            return
        await asyncio.gather(
            *(self.stop(run_id) for run_id in run_ids),
            return_exceptions=True,
        )
