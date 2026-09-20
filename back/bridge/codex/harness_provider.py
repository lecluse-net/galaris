"""Provision one isolated OpenAI Codex runtime per Galaris agent."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from app.agent import Agent, DriverPipelinePolicy
from app.harnesses import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
)
from app.mcp import mcp_token_service
from app.skill import build_skill_projection
from bridge.harness import configured_compose, manager
from core.params import Params
from core.params import runtime_settings as settings


_DEFAULT_AGENT_DIR = Path(__file__).parent / "default-agent"
_MODEL_PROXY = "galaris-profile"
_SERVICE_TOKEN_PREFIX = "galaris_codex_"
_SAFE_AGENT_CODE = re.compile(r"^[A-Za-z0-9_-]+$")


def _require_env_value(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required.")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError(f"{name} cannot contain a line break.")
    return normalized


def _instance_id(agent_code: str) -> str:
    code = _require_env_value("Agent code", agent_code)
    if not _SAFE_AGENT_CODE.fullmatch(code):
        raise ValueError("Agent code cannot be used as a Codex runtime name.")
    return code


def _runtime_url(agent_code: str) -> str:
    return f"http://{_instance_id(agent_code)}-agent:8787/v1"


def _compose_content(agent_code: str, *, uid: int, gid: int) -> str:
    container_name = f"{_instance_id(agent_code)}-agent"
    if uid < 0 or gid < 0:
        raise ValueError("Harness Manager UID and GID must be non-negative integers.")
    return f"""services:
  codex:
    build:
      context: .
      dockerfile: Dockerfile
      no_cache: true
      pull: true
      args:
        APP_UID: {uid}
        APP_GID: {gid}
    image: galaris/codex-harness:latest
    container_name: {container_name}
    restart: unless-stopped
    env_file:
      - .env
    environment:
      CODEX_HOME: /var/lib/codex
      CODEX_WORKSPACE: /workspace
    volumes:
      - ./workspace:/workspace
      - ./codex-home:/var/lib/codex
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 256
    mem_limit: 4g
    cpus: 2.0
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=512m
      - /run:rw,noexec,nosuid,size=16m
    healthcheck:
      test: [\"CMD\", \"curl\", \"--fail\", \"--silent\", \"http://127.0.0.1:8787/healthz\"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 20s

"""


def _env_content(
    *,
    llm_url: str,
    service_token: str,
    mcp_token: str,
) -> str:
    values = {
        "GALARIS_LLM_URL": _require_env_value("Galaris LLM URL", llm_url),
        "HARNESS_API_TOKEN": _require_env_value("Harness API token", service_token),
        "GALARIS_MCP_TOKEN": _require_env_value("Galaris MCP token", mcp_token),
    }
    return "".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}\n"
        for key, value in values.items()
    )


def _env_values(content: str) -> dict[str, str]:
    """Read the small JSON-quoted runtime env format without logging secrets."""

    values: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, raw_value = line.partition("=")
        if not separator or not key:
            continue
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            decoded = raw_value
        if isinstance(decoded, str):
            values[key] = decoded
    return values


def _codex_config(agent_code: str) -> str:
    api_url = _require_env_value("HARNESS_MANAGER_GALARIS_API_URL or APP_HOST", settings.HARNESS_API_URL)
    mcp_url = f"{api_url}/mcp/{agent_code}"
    llm_url = f"{api_url}/llm/openai"
    return f'''model_provider = "galaris"

[model_providers.galaris]
name = "Galaris"
base_url = {json.dumps(llm_url, ensure_ascii=False)}
env_key = "GALARIS_MCP_TOKEN"
wire_api = "responses"
requires_openai_auth = false

[sandbox_workspace_write]
network_access = true

[mcp_servers.galaris]
url = {json.dumps(mcp_url, ensure_ascii=False)}
bearer_token_env_var = "GALARIS_MCP_TOKEN"
required = true
'''


def _runtime_llm_url() -> str:
    api_url = _require_env_value("HARNESS_MANAGER_GALARIS_API_URL or APP_HOST", settings.HARNESS_API_URL)
    return f"{api_url}/llm/openai"


async def _write_static_files(instance_id: str) -> None:
    for filename in ("Dockerfile", "Makefile", "requirements.txt", "server.py"):
        await manager.write_text_file(
            instance_id,
            filename,
            (_DEFAULT_AGENT_DIR / filename).read_text(encoding="utf-8"),
        )
    await manager.write_text_file(
        instance_id,
        "stream_trace.py",
        (Path(__file__).with_name("stream_trace.py")).read_text(encoding="utf-8"),
    )


async def _sync_skills(instance_id: str, agent_id: int) -> str:
    snapshot = await build_skill_projection(agent_id)
    await manager.delete_tree(instance_id, "codex-home/skills")
    for item in snapshot.files:
        await manager.upload_file_from(
            instance_id,
            f"codex-home/skills/{item.skill_code}/{item.relative_path}",
            item.source,
        )
    await manager.write_text_file(
        instance_id,
        "codex-home/skills/.galaris-manifest.json",
        json.dumps(
            {
                "version": 1,
                "revision": snapshot.revision,
                "skills": list(snapshot.skill_codes),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return snapshot.revision


async def _write_runtime_files(
    instance_id: str,
    *,
    agent_code: str,
    service_token: str,
    mcp_token: str,
    uid: int,
    gid: int,
) -> None:
    await _write_static_files(instance_id)
    await manager.write_text_file(
        instance_id,
        "compose.yaml",
        await configured_compose(
            _compose_content(agent_code, uid=uid, gid=gid), service_name="codex",
        ),
    )
    await manager.write_text_file(
        instance_id,
        ".env",
        _env_content(
            llm_url=_runtime_llm_url(),
            service_token=service_token,
            mcp_token=mcp_token,
        ),
    )
    await manager.write_text_file(
        instance_id,
        "codex-home/config.toml",
        _codex_config(agent_code),
    )
    await manager.write_text_file(
        instance_id,
        "workspace/AGENTS.md",
        (
            "# Galaris managed Codex workspace\n\n"
            "Use the Galaris MCP server for platform tools and canonical memory. "
            "Keep file references on their exact Messenger or file-share provider URI. "
            "Local files are available to Galaris only through `console://` when that "
            "scheme is advertised; otherwise create deliverables directly on a writable "
            "provider returned by `file_schemes`.\n"
        ),
    )


async def _probe_runtime(base_url: str, token: str) -> None:
    from app.harnesses import OpenAIHarnessClient

    models = await OpenAIHarnessClient(base_url=base_url, token=token).list_models()
    if not models:
        raise RuntimeError("The Codex runtime did not expose any configured Galaris model.")


class CodexHarnessProvider:
    pipeline_policy = DriverPipelinePolicy(
        use_planner=False, use_briefing=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
    )
    code = "codex"
    driver_code = "openai_messages"
    label = "OpenAI Codex"
    containerized = True
    enabled_param: str | None = Params.HARNESS_CODEX_ENABLED
    max_parallel_tasks = 1

    def capabilities(self) -> frozenset[HarnessCapability]:
        return frozenset(
            {
                "execute",
                "streaming",
                "status",
                "start",
                "stop",
                "restart",
                "update",
                "logs",
                "refresh",
                "skills",
                "runtime_files",
                "mcp",
                "memory",
            }
        )

    async def provision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
        *,
        token: str | None,
    ) -> HarnessProvisioningResult:
        if not manager.configured:
            raise RuntimeError("The generic Harness manager is not configured.")
        del request, token
        instance_id = _instance_id(agent.code)
        service_token = _SERVICE_TOKEN_PREFIX + secrets.token_urlsafe(36)
        mcp_token = await mcp_token_service.rotate_system_token(agent.id)
        created = False
        try:
            system_info = await manager.get_system_info()
            await manager.create_instance(instance_id)
            created = True
            await _write_runtime_files(
                instance_id,
                agent_code=agent.code,
                service_token=service_token,
                mcp_token=mcp_token,
                uid=system_info["uid"],
                gid=system_info["gid"],
            )
            skill_revision = await _sync_skills(instance_id, agent.id)
            await manager.run_action(instance_id, "start")
            await _probe_runtime(_runtime_url(agent.code), service_token)
        except Exception:
            if created:
                try:
                    await manager.delete_instance(instance_id)
                except Exception:
                    pass
            await mcp_token_service.revoke_system_tokens(agent.id)
            raise

        return HarnessProvisioningResult(
            base_url=_runtime_url(agent.code),
            model=_MODEL_PROXY,
            token=service_token,
            capabilities=self.capabilities(),
            metadata={
                "runtime": "openai-codex-python",
                "sdk_version_policy": "pinned",
                "skill_revision": skill_revision,
                "model_passthrough": True,
                "galaris_extensions": True,
                "model_gateway": "galaris-responses",
            },
        )

    async def deprovision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
    ) -> None:
        del request
        instance_id = _instance_id(agent.code)
        await manager.delete_instance(instance_id)
        # Remove the short-lived pre-canonical Codex directory as well. Deletion
        # is idempotent, so this compatibility cleanup is safe on new installs.
        await manager.delete_instance(f"{instance_id}-codex")
        await mcp_token_service.revoke_system_tokens(agent.id)

    async def status(self, agent: Agent) -> str:
        return await manager.get_instance_status(_instance_id(agent.code))

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        if action == "refresh":
            await _sync_skills(_instance_id(agent.code), agent.id)
            return await manager.run_action(_instance_id(agent.code), "restart")
        if action == "update":
            instance_id = _instance_id(agent.code)
            previous_env = _env_values(
                await manager.read_text_file(instance_id, ".env")
            )
            system_info = await manager.get_system_info()
            await _write_runtime_files(
                instance_id,
                agent_code=agent.code,
                service_token=_require_env_value(
                    "Harness API token",
                    previous_env.get("HARNESS_API_TOKEN", ""),
                ),
                mcp_token=_require_env_value(
                    "Galaris MCP token",
                    previous_env.get("GALARIS_MCP_TOKEN", ""),
                ),
                uid=system_info["uid"],
                gid=system_info["gid"],
            )
        return await manager.run_action(_instance_id(agent.code), action)

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        return await manager.get_logs(_instance_id(agent.code), lines)


provider = CodexHarnessProvider()

__all__ = ["CodexHarnessProvider", "provider"]
