"""Provision an isolated Claude Agent SDK runtime through the Harness manager."""

from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
from typing import Any

import yaml

from app.agent import Agent, DriverPipelinePolicy
from app.harnesses import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
    get_private_execution_credentials,
    resolve_agent_harness,
)
from app.skill import build_skill_projection
from bridge.harness import configured_compose, manager
from core.params import Params
from core.params import runtime_settings as settings


_DEFAULT_AGENT_DIR = Path(__file__).parent / "default-agent"
_RUNTIME_PORT = 8642
_MODEL_ID = "claude-agent"
_CLAUDE_AGENT_SDK_CHANNEL = "latest"
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _runtime_base_url(agent_code: str) -> str:
    return f"http://{agent_code}-agent:{_RUNTIME_PORT}/v1"


def _serialize_env(values: dict[str, str]) -> str:
    lines: list[str] = []
    for key, value in sorted(values.items()):
        if not _ENV_KEY_RE.fullmatch(key):
            raise ValueError(f"Invalid Claude Agent environment key: {key!r}.")
        lines.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _compose(agent_code: str, *, uid: int, gid: int) -> str:
    payload: dict[str, Any] = {
        "services": {
            "agent": {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile",
                    "no_cache": True,
                    "pull": True,
                    "args": {
                        "RUNTIME_UID": uid,
                        "RUNTIME_GID": gid,
                    },
                },
                "image": f"galaris/claude-agent-harness:{_CLAUDE_AGENT_SDK_CHANNEL}",
                "container_name": f"{agent_code}-agent",
                "restart": "unless-stopped",
                "init": True,
                "read_only": True,
                "env_file": [".env"],
                "volumes": ["./data:/data"],
                "tmpfs": ["/tmp:size=256m,mode=1777"],
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "pids_limit": 512,
                "mem_limit": "4g",
                "cpus": 4.0,
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        (
                            "import urllib.request; "
                            "urllib.request.urlopen('http://127.0.0.1:8642/health', timeout=3)"
                        ),
                    ],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 12,
                    "start_period": "20s",
                },
            }
        },
    }
    return str(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))


async def _sync_template(instance_id: str) -> None:
    if not _DEFAULT_AGENT_DIR.is_dir():
        raise RuntimeError(f"Claude Agent template is missing: {_DEFAULT_AGENT_DIR}.")
    for source in sorted(_DEFAULT_AGENT_DIR.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(_DEFAULT_AGENT_DIR).as_posix()
        await manager.upload_file_from(instance_id, relative, source)
    await manager.upload_file_from(
        instance_id,
        "stream_trace.py",
        Path(__file__).with_name("stream_trace.py"),
    )


async def _sync_skills(agent: Agent) -> str:
    snapshot = await build_skill_projection(agent.id)
    await manager.delete_tree(agent.code, "data/skills")
    for item in snapshot.files:
        destination = (
            "data/skills/.claude/skills/"
            f"{item.skill_code}/{item.relative_path}"
        )
        await manager.upload_file_from(agent.code, destination, item.source)
    manifest = {
        "version": 1,
        "revision": snapshot.revision,
        "skills": list(snapshot.skill_codes),
        "files": [
            {
                "skill": item.skill_code,
                "path": item.relative_path,
                "sha256": item.sha256,
                "size": item.size,
            }
            for item in snapshot.files
        ],
    }
    await manager.write_text_file(
        agent.code,
        "data/skills/.galaris-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return snapshot.revision


async def _sync_runtime(agent: Agent, *, api_token: str) -> str:
    api_url = settings.HARNESS_API_URL
    if not api_url:
        raise RuntimeError("The Claude Agent Harness requires APP_HOST.")
    from app.mcp import mcp_token_service

    system_token = await mcp_token_service.rotate_system_token(agent.id)
    system_info = await manager.get_system_info()
    await _sync_template(agent.code)
    skill_revision = await _sync_skills(agent)
    await manager.write_text_file(
        agent.code,
        ".env",
        _serialize_env(
            {
                "ANTHROPIC_AUTH_TOKEN": system_token,
                "ANTHROPIC_BASE_URL": f"{api_url}/llm/anthropic",
                "CLAUDE_AGENT_API_TOKEN": api_token,
                "CLAUDE_AGENT_WORKSPACE": "/data/workspace",
                "CLAUDE_CONFIG_DIR": "/data/claude",
                "HOME": "/data/home",
                "GALARIS_MCP_TOKEN": system_token,
                "GALARIS_MCP_URL": f"{api_url}/mcp/{agent.code}",
            }
        ),
    )
    await manager.write_text_file(
        agent.code,
        "compose.yaml",
        await configured_compose(
            _compose(
                agent.code,
                uid=int(system_info["uid"]),
                gid=int(system_info["gid"]),
            ),
            service_name="agent",
        ),
    )
    return skill_revision


async def _selected_token(agent: Agent) -> str:
    target = await resolve_agent_harness(agent)
    if target is None:
        raise RuntimeError("The agent has no selected Claude Agent Harness.")
    credentials = await get_private_execution_credentials(target.id)
    if not credentials.token:
        raise RuntimeError("The Claude Agent Harness has no runtime token.")
    return credentials.token


class ClaudeAgentHarnessProvider:
    pipeline_policy = DriverPipelinePolicy(
        use_planner=False, use_briefing=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
    )
    code = "claude_agent"
    driver_code = "openai_messages"
    label = "Claude Agent"
    containerized = True
    enabled_param: str | None = Params.HARNESS_CLAUDE_AGENT_ENABLED
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
        del request
        if not manager.configured:
            raise RuntimeError("The generic Harness manager is not configured.")
        api_token = token or secrets.token_urlsafe(32)
        existing = await manager.list_instances()
        if agent.code not in existing:
            await manager.create_instance(agent.code)
        try:
            skill_revision = await _sync_runtime(agent, api_token=api_token)
            await manager.run_action(agent.code, "start")
            from app.harnesses import OpenAIHarnessClient

            client = OpenAIHarnessClient(
                base_url=_runtime_base_url(agent.code),
                token=api_token,
            )
            models = await client.list_models()
            if _MODEL_ID not in models:
                raise RuntimeError("The Claude Agent runtime did not expose its model.")
        except Exception:
            try:
                await manager.delete_instance(agent.code)
            except Exception:
                pass
            try:
                from app.mcp import mcp_token_service

                await mcp_token_service.revoke_system_tokens(agent.id)
            except Exception:
                pass
            raise
        return HarnessProvisioningResult(
            base_url=_runtime_base_url(agent.code),
            model=_MODEL_ID,
            token=api_token,
            capabilities=self.capabilities(),
            metadata={
                "model_passthrough": True,
                "galaris_extensions": True,
                "model_gateway": "galaris-anthropic",
                "runtime": "claude-agent-sdk",
                "sdk_version_policy": "pinned",
                "skill_revision": skill_revision,
            },
        )

    async def deprovision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
    ) -> None:
        del request
        await manager.delete_instance(agent.code)
        from app.mcp import mcp_token_service

        await mcp_token_service.revoke_system_tokens(agent.id)

    async def status(self, agent: Agent) -> str:
        return await manager.get_instance_status(agent.code)

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        if action == "stop":
            return await manager.run_action(agent.code, action)
        token = await _selected_token(agent)
        await _sync_runtime(agent, api_token=token)
        effective_action = "restart" if action == "refresh" else action
        return await manager.run_action(agent.code, effective_action)

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        return await manager.get_logs(agent.code, lines)


provider = ClaudeAgentHarnessProvider()

__all__ = ["ClaudeAgentHarnessProvider", "provider"]
