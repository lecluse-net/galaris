"""Upload the packaged editor and verify it over the pinned Console transport."""

import hashlib
from pathlib import Path, PurePosixPath
import shlex
from typing import Literal, cast
from uuid import uuid4

import httpx
import asyncssh
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.code import CodeConnection, WorkspaceTarget, RUNTIME_CONFIGURATION_LOCK_OFFSET, prepare_runtime_configuration, finish_runtime_configuration, lock_runtime_upgrade
from app.console import (ConsoleEditorInstallResult, ConsoleResult, SshExecutionTransport, code_runtime_tunnel,
    configure_editor_runtime, connection_generation, discover_repository, resolve_connection, resolve_active_connection)
from core.database import get_db
from sqlalchemy import text


class DeploymentReceipt(BaseModel):
    port: int = Field(ge=1, le=65535)
    version: str
    already_installed: bool


class DeploymentCheck(BaseModel):
    managed: bool = True
    update_required: bool
    port: int | None = Field(default=None, ge=1, le=65535)


class DeploymentFailure(BaseModel):
    error: str


_FAILURE_MESSAGES = {
    "docker_missing": "Docker is not installed or is absent from the SSH command PATH",
    "docker_timeout": "A Docker command timed out",
    "docker_access": "The SSH account cannot access the Docker daemon",
    "compose_unavailable": "Docker Compose is unavailable to the SSH account",
    "docker_command_failed": "A Docker inspection, build or container command failed",
    "account_home": "The SSH account must be non-system and own its home directory",
    "deployment_path": "The deployment directory leaves the SSH account home",
    "credential_missing": "The managed editor credential file is missing",
    "editor_missing": "The managed editor container is missing",
    "credential_invalid": "The retained editor credential is invalid",
    "home_mismatch": "The existing editor belongs to another home directory",
    "upgrade_required": "The existing editor requires an explicit upgrade",
    "sessions_active": "Editor processes are still active; save files and close editor sessions for this SSH account",
    "port_binding": "The editor control port must be bound only to loopback",
    "user_namespaces": "The editor Bubblewrap user namespace check failed",
    "health_verification": "The editor health response does not match the required protocol/version",
    "health_timeout": "The editor did not become ready",
}


class EditorDeploymentError(ValueError):
    """A fixed diagnostic safe to print without exposing remote output."""

    def __init__(self, stage: Literal["inspection", "upgrade", "installation"], reason: str = "unknown") -> None:
        if reason not in _FAILURE_MESSAGES:
            reason = "unknown"
        message = _FAILURE_MESSAGES.get(reason, "The remote controller failed without a recognized diagnostic")
        super().__init__(f"{stage} [{reason}]: {message}")


def _deployment_error(result: ConsoleResult, stage: Literal["inspection", "upgrade", "installation"]) -> EditorDeploymentError:
    reason = "unknown"
    if not result.stdout_truncated:
        try:
            reason = DeploymentFailure.model_validate_json(result.stdout).error
        except ValidationError:
            pass
    return EditorDeploymentError(stage, reason)


def deployment_files() -> dict[str, bytes]:
    source = Path("/opt/galaris-code-deployment")
    if not source.is_dir():
        source = Path(__file__).resolve().parents[3] / "code-executor"
    paths = ["Dockerfile", "runtime.py", "profiles.py", "provision-credential.py", "deploy.py", "extension/package.json", "extension/extension.js", "extension/LICENSE.md"]
    return {name: (source / name).read_bytes() for name in paths}


async def _deployment_credential(sftp: asyncssh.SFTPClient, home: str) -> str:
    path = home + "/.galaris/code-editor/credential"
    if str(await sftp.realpath(path)) != path:
        raise ValueError("The editor credential must stay in the deployment directory")
    async with sftp.open(path, "rb", encoding=None) as secret:
        payload = cast(object, await secret.read(129))
        if not isinstance(payload, bytes):
            raise RuntimeError("Invalid editor deployment credential encoding")
        try:
            token = payload.decode("ascii").strip()
        except UnicodeError:
            raise RuntimeError("Invalid editor deployment credential") from None
    if not 32 <= len(token) <= 128 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in token):
        raise RuntimeError("Invalid editor deployment credential")
    return token


async def update_connection_code_editor(connection_id: int) -> ConsoleEditorInstallResult | None:
    """Maintain an already configured managed service without changing its access."""
    return await _deploy(connection_id, upgrade=True, update_only=True)


async def deploy_connection_code_editor(connection_id: int, upgrade: bool = False) -> ConsoleEditorInstallResult:
    result = await _deploy(connection_id, upgrade=upgrade)
    assert result is not None
    return result


async def _deploy(connection_id: int, *, upgrade: bool, update_only: bool = False) -> ConsoleEditorInstallResult | None:
    config = await (resolve_active_connection(connection_id) if update_only else resolve_connection(connection_id))
    if config.host == "ssh-executor":
        raise ValueError("The embedded Console editor is deployed with Galaris")
    if update_only and (not config.code_runtime_port or not config.code_runtime_token):
        raise ValueError("Automatic updates require configured editor access")
    previous = CodeConnection(connection_id=connection_id, fingerprint=connection_generation(config))
    async def original_target(path: str) -> WorkspaceTarget:
        return WorkspaceTarget.model_validate((await discover_repository(config, path)).model_dump())
    verified = {} if update_only else await prepare_runtime_configuration(previous, original_target)
    await get_db().commit()
    transport = SshExecutionTransport(config)
    try:
        status = await transport.status()
        if not (status.reachable and status.authenticated and status.host_key_verified
                and status.home_writable and status.sftp_available):
            raise ValueError("Test the SSH Console successfully before deploying its editor")
        connection = await transport.connection()
        sftp = await connection.start_sftp_client()
        try:
            home = str(await sftp.realpath(await transport.home())).rstrip("/")
            files = deployment_files()
            digest = hashlib.sha256()
            for name, payload in sorted(files.items()):
                digest.update(name.encode())
                digest.update(payload)
            root = home
            for part in (".galaris", "code-editor", "bundle-" + digest.hexdigest(), "extension"):
                directory = str(PurePosixPath(root) / part)
                try:
                    await sftp.lstat(directory)
                except asyncssh.SFTPNoSuchFile:
                    try:
                        await sftp.mkdir(directory)
                    except asyncssh.SFTPFailure:
                        await sftp.lstat(directory)  # Concurrent deployment of the same bundle.
                canonical = str(await sftp.realpath(directory))
                if canonical != directory or not canonical.startswith(home + "/"):
                    raise ValueError("The editor deployment path leaves the account home")
                await sftp.chmod(directory, 0o700)
                root = directory
            bundle = str(PurePosixPath(root).parent)
            for name, payload in files.items():
                path = str(PurePosixPath(bundle) / name)
                temporary = str(PurePosixPath(path).with_name("." + PurePosixPath(path).name + ".part-" + uuid4().hex))
                try:
                    async with sftp.open(temporary, "wb", encoding=None) as output:
                        await output.write(payload)
                    await sftp.chmod(temporary, 0o600)
                    await sftp.posix_rename(temporary, path)
                finally:
                    try:
                        await sftp.remove(temporary)
                    except asyncssh.SFTPNoSuchFile:
                        pass
            command = "python3 " + shlex.quote(bundle + "/deploy.py")
            if upgrade:
                checked = await transport.exec(command + " --check --require-existing", timeout_s=30)
                if checked.exit_code != 0 or checked.stdout_truncated:
                    raise _deployment_error(checked, "inspection")
                check = DeploymentCheck.model_validate_json(checked.stdout)
                if not check.managed:
                    if update_only:
                        return None
                    raise ValueError("This editor is administered manually")
                if check.port is None:
                    raise ValueError("Invalid managed editor port")
                if update_only and check.port != config.code_runtime_port:
                    raise ValueError("The managed editor does not match its configured port")
                if update_only and SecretStr(await _deployment_credential(sftp, home)) != config.code_runtime_token:
                    raise ValueError("The managed editor does not match its configured credential")
                if check.update_required:
                    await lock_runtime_upgrade(previous)
            result = await transport.exec(command + (" --upgrade" if upgrade else "")
                + (" --require-existing" if update_only else ""), timeout_s=960)
            if result.exit_code != 0 or result.stdout_truncated:
                raise _deployment_error(result, "upgrade" if upgrade else "installation")
            try:
                receipt = DeploymentReceipt.model_validate_json(result.stdout)
            except ValidationError:
                raise RuntimeError("Invalid editor deployment receipt") from None
            token = await _deployment_credential(sftp, home)
        finally:
            sftp.exit()
        candidate = config.model_copy(update={"code_runtime_port": receipt.port, "code_runtime_token": SecretStr(token)})
        if update_only and candidate != config:
            raise ValueError("Automatic updates cannot change configured editor access")
        async with code_runtime_tunnel(candidate) as endpoint:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.get(endpoint + "/health", headers={"Authorization": "Bearer " + token})
                if response.status_code != 200 or response.json() != {"ready": True, "protocol": 1, "version": receipt.version}:
                    raise ValueError("The editor was installed but SSH forwarding verification failed")
        # Coordinate with session creation before publishing a new runtime.
        await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {
            "key": RUNTIME_CONFIGURATION_LOCK_OFFSET + connection_id,
        })
        if update_only:
            if await resolve_active_connection(connection_id) != config:
                raise ValueError("Console configuration changed during the editor update")
        else:
            await configure_editor_runtime(config, receipt.port, token)
        current = CodeConnection(connection_id=connection_id, fingerprint=connection_generation(candidate))
        if current.fingerprint != previous.fingerprint:
            async def configured_target(path: str) -> WorkspaceTarget:
                return WorkspaceTarget.model_validate((await discover_repository(candidate, path)).model_dump())
            await finish_runtime_configuration(current, verified, configured_target)
        await get_db().commit()
        return ConsoleEditorInstallResult(connection_id=connection_id, port=receipt.port, version=receipt.version,
            ready=True, already_installed=receipt.already_installed)
    except httpx.HTTPError:
        raise RuntimeError("Editor verification transport unavailable") from None
    finally:
        await transport.close()
