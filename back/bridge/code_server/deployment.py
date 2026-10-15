"""Upload the packaged editor and verify it over the pinned Console transport."""

import hashlib
from pathlib import Path, PurePosixPath
import shlex
from uuid import uuid4

import httpx
import asyncssh
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.code import CodeConnection, WorkspaceTarget, RUNTIME_CONFIGURATION_LOCK_OFFSET, prepare_runtime_configuration, finish_runtime_configuration, lock_runtime_upgrade
from app.console import (ConsoleEditorInstallResult, SshExecutionTransport, code_runtime_tunnel,
    configure_editor_runtime, connection_generation, discover_repository, resolve_connection)
from core.database import get_db
from sqlalchemy import text


class DeploymentReceipt(BaseModel):
    port: int = Field(ge=1, le=65535)
    version: str
    already_installed: bool


def deployment_files() -> dict[str, bytes]:
    source = Path("/opt/galaris-code-deployment")
    if not source.is_dir():
        source = Path(__file__).resolve().parents[3] / "code-executor"
    paths = ["Dockerfile", "runtime.py", "profiles.py", "provision-credential.py", "deploy.py", "extension/package.json", "extension/extension.js", "extension/LICENSE.md"]
    return {name: (source / name).read_bytes() for name in paths}


async def deploy_connection_code_editor(connection_id: int, upgrade: bool = False) -> ConsoleEditorInstallResult:
    config = await resolve_connection(connection_id)
    if config.host == "ssh-executor":
        raise ValueError("The embedded Console editor is deployed with Galaris")
    previous = CodeConnection(connection_id=connection_id, fingerprint=connection_generation(config))
    async def original_target(path: str) -> WorkspaceTarget:
        return WorkspaceTarget.model_validate((await discover_repository(config, path)).model_dump())
    verified = await prepare_runtime_configuration(previous, original_target)
    await get_db().commit()
    if upgrade:
        await lock_runtime_upgrade(previous)
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
            result = await transport.exec("python3 " + shlex.quote(bundle + "/deploy.py") + (" --upgrade" if upgrade else ""), timeout_s=960)
            if result.exit_code != 0 or result.stdout_truncated:
                raise ValueError("Editor deployment failed: verify Docker/Compose access, Linux user namespaces and the account home")
            try:
                receipt = DeploymentReceipt.model_validate_json(result.stdout)
            except ValidationError:
                raise RuntimeError("Invalid editor deployment receipt") from None
            credential_path = home + "/.galaris/code-editor/credential"
            if str(await sftp.realpath(credential_path)) != credential_path:
                raise ValueError("The editor credential must stay in the deployment directory")
            async with sftp.open(credential_path, "rb", encoding=None) as secret:
                try:
                    token = (await secret.read(129)).decode("ascii").strip()
                except UnicodeError:
                    raise RuntimeError("Invalid editor deployment credential") from None
            if not 32 <= len(token) <= 128 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in token):
                raise RuntimeError("Invalid editor deployment credential")
        finally:
            sftp.exit()
        candidate = config.model_copy(update={"code_runtime_port": receipt.port, "code_runtime_token": SecretStr(token)})
        async with code_runtime_tunnel(candidate) as endpoint:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.get(endpoint + "/health", headers={"Authorization": "Bearer " + token})
                if response.status_code != 200 or response.json() != {"ready": True, "protocol": 1, "version": receipt.version}:
                    raise ValueError("The editor was installed but SSH forwarding verification failed")
        # Coordinate with session creation before publishing a new runtime.
        await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {
            "key": RUNTIME_CONFIGURATION_LOCK_OFFSET + connection_id,
        })
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
