from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncssh
import pytest
from pydantic import SecretStr

from app.console import connection_service as console_connection_service
from app.console import router as console_router
from app.console.contracts import ConsoleResult, ConsoleStatus, SshConnectionConfig
from app.console.helper_service import HELPER_VERSION, helper_payload
from app.console.keys import generate_ed25519_keypair
from app.console.schemas import ConsoleHelperInstallResult
from app.console.ssh_client import SshExecutionTransport


def _config(private_key: str) -> SshConnectionConfig:
    return SshConnectionConfig(
        connection_id=1,
        host="executor.example.test",
        username="agent_code",
        private_key=SecretStr(private_key),
        known_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnly",
    )


def test_generated_keypair_is_accepted_by_asyncssh() -> None:
    private_key, public_key = generate_ed25519_keypair()

    parsed = asyncssh.import_private_key(private_key)

    assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert parsed.export_public_key().decode("ascii").strip() == public_key


def test_packaged_helper_exposes_the_expected_version() -> None:
    asset = Path(__file__).parents[1] / "assets" / "galaris-exec"
    # External SSH targets and the Debian executor do not use the backend's Python 3.14.
    ast.parse(asset.read_text(), filename=str(asset), feature_version=(3, 11))

    result = subprocess.run(
        [sys.executable, str(asset), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert helper_payload() == asset.read_bytes()
    assert result.stdout.strip() == f"galaris-exec {HELPER_VERSION}"


@pytest.mark.asyncio
async def test_helper_detection_prefers_the_user_scoped_working_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, _public_key = generate_ed25519_keypair()
    transport = SshExecutionTransport(_config(private_key))
    deployed = "/home/agent_code/.galaris/bin/galaris-exec"

    async def home() -> str:
        return "/home/agent_code"

    async def simple(command: str, timeout_s: float = 10.0) -> SimpleNamespace:
        del timeout_s
        if command == f"test -x {deployed}":
            return SimpleNamespace(exit_status=0, stdout="", stderr="")
        if command == "command -v galaris-exec 2>/dev/null":
            return SimpleNamespace(exit_status=1, stdout="", stderr="")
        if command == f"{deployed} --version":
            return SimpleNamespace(
                exit_status=0,
                stdout=f"galaris-exec {HELPER_VERSION}\n",
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(transport, "home", home)
    monkeypatch.setattr(transport, "_simple", simple)

    assert await transport._working_helper() == deployed  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
@pytest.mark.parametrize("deployed_version,path_version,expected", [("1", "2", "system"), ("2", "1", "user"), ("1", "1", "user")])
async def test_recovery_capable_helper_is_not_shadowed_by_legacy_installation(
    monkeypatch: pytest.MonkeyPatch, deployed_version: str, path_version: str, expected: str,
) -> None:
    private_key, _ = generate_ed25519_keypair()
    transport = SshExecutionTransport(_config(private_key))
    deployed = "/home/agent_code/.galaris/bin/galaris-exec"
    system = "/usr/local/bin/galaris-exec"
    monkeypatch.setattr(transport, "home", AsyncMock(return_value="/home/agent_code"))

    async def simple(command: str, timeout_s: float = 10.0) -> SimpleNamespace:
        if command == f"test -x {deployed}":
            return SimpleNamespace(exit_status=0, stdout="")
        if command == "command -v galaris-exec 2>/dev/null":
            return SimpleNamespace(exit_status=0, stdout=system)
        version = deployed_version if command == f"{deployed} --version" else path_version
        return SimpleNamespace(exit_status=0, stdout=f"galaris-exec {version}\n")

    monkeypatch.setattr(transport, "_simple", simple)
    assert await transport.supports_recovery() is ("2" in {deployed_version, path_version})
    assert await transport._working_helper() == (system if expected == "system" else deployed)


@pytest.mark.asyncio
async def test_helper_install_is_atomic_and_user_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, _public_key = generate_ed25519_keypair()
    transport = SshExecutionTransport(_config(private_key))
    home_path = "/home/agent_code"
    install_path = f"{home_path}/.galaris/bin/galaris-exec"

    class Writer:
        def __init__(self, files: dict[str, bytes], path: str) -> None:
            self.files = files
            self.path = path

        async def __aenter__(self) -> Writer:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def write(self, payload: bytes) -> None:
            self.files[self.path] = payload

    class Sftp:
        def __init__(self) -> None:
            self.files: dict[str, bytes] = {}
            self.directories = {home_path}
            self.permissions: dict[str, int] = {}
            self.exited = False

        async def realpath(self, path: str) -> str:
            # OpenSSH can normalize a missing path without reporting that it
            # does not exist, which is why install_helper probes with lstat.
            return path

        async def lstat(self, path: str) -> SimpleNamespace:
            if path not in self.directories:
                raise asyncssh.SFTPNoSuchFile("No such file")
            return SimpleNamespace()

        async def mkdir(self, path: str) -> None:
            self.directories.add(path)

        async def chmod(self, path: str, mode: int) -> None:
            self.permissions[path] = mode

        def open(self, path: str, _mode: str, *, encoding: object) -> Writer:
            assert encoding is None
            return Writer(self.files, path)

        async def posix_rename(self, source: str, destination: str) -> None:
            self.files[destination] = self.files.pop(source)
            self.permissions[destination] = self.permissions.pop(source)

        async def remove(self, path: str) -> None:
            self.files.pop(path, None)

        def exit(self) -> None:
            self.exited = True

    sftp = Sftp()

    class Connection:
        async def start_sftp_client(self) -> Sftp:
            return sftp

    async def home() -> str:
        return home_path

    async def connection() -> Connection:
        return Connection()

    async def simple(command: str, timeout_s: float = 10.0) -> SimpleNamespace:
        del timeout_s
        if command.startswith("test -x "):
            path = command.removeprefix("test -x ")
            return SimpleNamespace(
                exit_status=0 if path in sftp.files else 1,
                stdout="",
                stderr="",
            )
        if command == "command -v galaris-exec 2>/dev/null":
            return SimpleNamespace(exit_status=1, stdout="", stderr="")
        if command.endswith(" --version"):
            return SimpleNamespace(
                exit_status=0,
                stdout=f"galaris-exec {HELPER_VERSION}\n",
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(transport, "home", home)
    monkeypatch.setattr(transport, "connection", connection)
    monkeypatch.setattr(transport, "_simple", simple)
    payload = helper_payload()

    installed = await transport.install_helper(
        payload,
        expected_version=HELPER_VERSION,
    )

    assert installed == install_path
    assert sftp.files == {install_path: payload}
    assert sftp.permissions[install_path] == 0o700
    assert sftp.permissions[f"{home_path}/.galaris"] == 0o700
    assert sftp.permissions[f"{home_path}/.galaris/bin"] == 0o700
    assert sftp.exited is True


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_available", [False, True])
async def test_installation_requires_verified_operation_recovery(
    monkeypatch: pytest.MonkeyPatch, recovery_available: bool,
) -> None:
    from app.console import helper_service

    transport = SimpleNamespace(
        config=SimpleNamespace(host="console.example.test"),
        status=AsyncMock(return_value=ConsoleStatus(
            reachable=True, authenticated=True, host_key_verified=True,
            home_writable=True, sftp_available=True, galaris_exec_available=True,
            operation_recovery_available=recovery_available, mode="enhanced",
        )),
        install_helper=AsyncMock(return_value="/home/agent/.galaris/bin/galaris-exec"),
        close=AsyncMock(),
    )
    monkeypatch.setattr(helper_service, "resolve_connection", AsyncMock(return_value=object()))
    monkeypatch.setattr(helper_service, "SshExecutionTransport", lambda config: transport)
    if recovery_available:
        result = await helper_service.install_connection_helper(42)
        assert result.status.operation_recovery_available
    else:
        with pytest.raises(RuntimeError, match="verification failed"):
            await helper_service.install_connection_helper(42)
    transport.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_running", [False, True])
async def test_recovery_distinguishes_launch_acknowledgement_from_completion(
    monkeypatch: pytest.MonkeyPatch, allow_running: bool,
) -> None:
    private_key, _ = generate_ed25519_keypair()
    transport = SshExecutionTransport(_config(private_key))
    operation_id = uuid4()
    monkeypatch.setattr(transport, "supports_recovery", AsyncMock(return_value=True))
    poll = AsyncMock(side_effect=[
        ConsoleResult(run_id=operation_id, status="running"),
        ConsoleResult(run_id=operation_id, status="completed", exit_code=0, stdout="receipt"),
    ])
    monkeypatch.setattr(transport, "poll", poll)
    first = await transport.recover_operation(operation_id, allow_running=allow_running)
    assert (first is not None) is allow_running
    terminal = await transport.recover_operation(operation_id, allow_running=allow_running)
    assert terminal is not None and terminal.status == "completed" and terminal.stdout == "receipt"


@pytest.mark.asyncio
async def test_install_helper_route_returns_the_verified_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ConsoleHelperInstallResult(
        connection_id=42,
        path="/home/agent_code/.galaris/bin/galaris-exec",
        version=HELPER_VERSION,
        status=ConsoleStatus(
            reachable=True,
            authenticated=True,
            host_key_verified=True,
            home="/home/agent_code",
            home_writable=True,
            sftp_available=True,
            galaris_exec_available=True,
            mode="enhanced",
        ),
    )
    install = AsyncMock(return_value=expected)
    monkeypatch.setattr(console_router, "install_connection_helper", install)
    managed = AsyncMock()
    monkeypatch.setattr(console_router, "_managed_connection", managed)

    result = await console_router.install_connection_galaris_exec(42)

    assert result == expected
    install.assert_awaited_once_with(42)
    managed.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_embedded_executor_is_in_use_for_active_internal_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        console_connection_service.tool_service,
        "get_tool_record",
        AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        console_connection_service.connection_service,
        "get_connections_by_param",
        AsyncMock(return_value=[SimpleNamespace(agent_id=12, active=True)]),
    )
    monkeypatch.setattr(
        console_connection_service.agent_service,
        "get",
        AsyncMock(return_value=SimpleNamespace(agent_driver="internal")),
    )

    assert await console_connection_service.is_embedded_executor_in_use() is True


@pytest.mark.asyncio
async def test_embedded_executor_ignores_inactive_and_non_internal_harnesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        console_connection_service.tool_service,
        "get_tool_record",
        AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        console_connection_service.connection_service,
        "get_connections_by_param",
        AsyncMock(
            return_value=[
                SimpleNamespace(agent_id=10, active=False),
                SimpleNamespace(agent_id=11, active=True),
            ]
        ),
    )
    get_agent = AsyncMock(return_value=SimpleNamespace(agent_driver="hermes"))
    monkeypatch.setattr(console_connection_service.agent_service, "get", get_agent)

    assert await console_connection_service.is_embedded_executor_in_use() is False
    get_agent.assert_awaited_once_with(11)


@pytest.mark.asyncio
async def test_executor_availability_returns_usage_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    availability = AsyncMock(return_value=True)
    monkeypatch.setattr(console_router, "is_embedded_executor_in_use", availability)

    result = await console_router.executor_availability()

    assert result.in_use is True
    availability.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_task_cancellation_stops_tracked_enhanced_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, _public_key = generate_ed25519_keypair()
    transport = SshExecutionTransport(_config(private_key))
    run_id = uuid4()

    async def require_helper() -> str:
        return "/usr/local/bin/galaris-exec"

    async def resolve_path(
        _value: str = ".",
        *,
        must_exist: bool = True,
    ) -> tuple[str, str]:
        assert must_exist is True
        return "/home/agent_code", "."

    async def execute(
        _command: str,
        _cwd: str = ".",
        _timeout_s: float | None = None,
        *,
        stdin: bytes | None = None,
    ) -> ConsoleResult:
        assert stdin is None
        return ConsoleResult(
            run_id=run_id,
            status="completed",
            exit_code=0,
            stdout='{"run_id":"%s","status":"running"}' % run_id,
        )

    stopped: list[object] = []

    async def stop(target: object) -> ConsoleResult:
        stopped.append(target)
        return ConsoleResult(run_id=run_id, status="cancelled")

    monkeypatch.setattr(transport, "_require_helper", require_helper)
    monkeypatch.setattr(transport, "resolve_path", resolve_path)
    monkeypatch.setattr(transport, "exec", execute)
    started = await transport.start("sleep 60", task_id=uuid4())
    assert started.run_id == run_id

    monkeypatch.setattr(transport, "stop", stop)
    await transport.cancel_active()

    assert stopped == [run_id]
