"""Private broker transport for embedded and explicitly prepared external Consoles."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
from asyncssh import Error as SshError
from core.database import get_db
from app.agent import Agent

from app.code import CodeConnection, CodeRuntimeNotConfiguredError, WorkspaceTarget, Mode, RuntimeEndpoint
from app.code.contracts import CodeSessionUnavailableError
from app.console import SshConnectionConfig, code_runtime_tunnel, connection_generation, discover_repository, resolve_active_connection, resolve_ssh_connection


class CodeServerRuntime:
    def __init__(self, connection_resolver: Callable[[int], Awaitable[SshConnectionConfig]] = resolve_active_connection) -> None:
        self.connection_resolver = connection_resolver

    async def connection(self, connection_id: int) -> CodeConnection:
        config = await self.connection_resolver(connection_id)
        return CodeConnection(connection_id=config.connection_id, fingerprint=connection_generation(config))

    async def connection_for_agent(self, agent_id: int) -> CodeConnection:
        config = await resolve_ssh_connection(agent_id)
        agent = await get_db().get(Agent, agent_id)
        if config is None or agent is None:
            raise PermissionError("An owned active Console is required")
        return CodeConnection(connection_id=config.connection_id, fingerprint=connection_generation(config), owner_user_id=agent.user_id)

    async def _config(self, reference: CodeConnection) -> SshConnectionConfig:
        config = await self.connection_resolver(reference.connection_id)
        if connection_generation(config) != reference.fingerprint:
            raise PermissionError("Console target changed")
        return config

    async def discover(self, connection: CodeConnection, path: str) -> WorkspaceTarget:
        try:
            target = await discover_repository(await self._config(connection), path)
        except (SshError, OSError, TimeoutError):
            raise RuntimeError("Console repository discovery unavailable") from None
        return WorkspaceTarget.model_validate(target.model_dump())

    @asynccontextmanager
    async def endpoint(self, reference: CodeConnection) -> AsyncGenerator[RuntimeEndpoint]:
        config = await self._config(reference)
        try:
            if config.host == "ssh-executor":
                credential = Path("/run/galaris-code/token").read_text().strip()
                if len(credential) < 32:
                    raise RuntimeError("Missing code runtime credential")
                yield RuntimeEndpoint(url="http://code-executor:8766", credential=credential)
            else:
                if config.code_runtime_port is None or config.code_runtime_token is None:
                    raise CodeRuntimeNotConfiguredError("The external Console has no prepared code runtime")
                async with code_runtime_tunnel(config) as url:
                    yield RuntimeEndpoint(url=url, credential=config.code_runtime_token.get_secret_value())
        except (SshError, OSError, httpx.HTTPError):
            raise RuntimeError("The prepared code runtime or its transport is unavailable") from None

    async def _request(self, config: CodeConnection, method: str, path: str, data: dict[str, object] | None = None) -> None:
        async with self.endpoint(config) as endpoint:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                response = await client.request(method, endpoint.url + path,
                    headers={"Authorization": f"Bearer {endpoint.credential}"}, json=data)
                if response.status_code == 410:
                    raise CodeSessionUnavailableError("The editor session has stopped")
                response.raise_for_status()

    async def open(self, config: CodeConnection, target: WorkspaceTarget, session: UUID, mode: Mode) -> None:
        await self._request(config, "POST", "/sessions", {
            "session": str(session), "home": target.home, "root": target.root,
            "git_paths": list(target.git_paths), "mode": mode,
            "root_identity": target.root_identity, "git_identities": list(target.git_identities),
        })

    async def close(self, config: CodeConnection, session: UUID, *, discard: bool = False) -> None:
        await self._request(config, "DELETE", f"/sessions/{session}" + ("?discard=true" if discard else ""))

    async def touch(self, config: CodeConnection, session: UUID) -> None:
        await self._request(config, "POST", f"/sessions/{session}/touch")

    async def navigate(self, config: CodeConnection, session: UUID, file: str | None, view: str) -> None:
        await self._request(config, "POST", f"/sessions/{session}/navigate", {"file": file, "view": view})
