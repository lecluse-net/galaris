"""Provision DeepSeek Harness behind the common OpenAI Messages contract."""

from __future__ import annotations

from pathlib import Path
import secrets

from loguru import logger

from app.agent import Agent, DriverPipelinePolicy
from app.harnesses import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
    OpenAIHarnessClient,
    get_private_execution_credentials,
    resolve_agent_harness,
)
from app.llm import get_llm_for_agent
from app.mcp import mcp_token_service
from app.skill import build_skill_projection
from bridge.harness import configured_compose, manager as harness_manager
from core.params import Params
from core.params import runtime_settings as settings


_DEFAULT_AGENT_DIR = Path(__file__).parent / "default-agent"
_MANAGED_SKILLS_ROOT = "data/skills"
_DSH_VERSION = "0.1.6-alpha.1"
_DSH_REF = "0a15e36e7f82b6ed45af6fa9759f29b40dcd965d"


def _runtime_name(agent_code: str, harness_id: object) -> str:
    """Return the stable, unique container name owned by one agent."""

    del harness_id
    return f"{agent_code}-agent"


def _serialize_env(values: dict[str, str]) -> str:
    """Serialize controlled values for Compose without exposing them to logs."""

    if any("\n" in key or "=" in key for key in values):
        raise ValueError("DeepSeek Harness environment keys are invalid.")
    lines: list[str] = []
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"DeepSeek Harness environment value {key!r} is invalid.")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


async def _push_static_files(instance_id: str) -> None:
    if not _DEFAULT_AGENT_DIR.is_dir():
        raise RuntimeError("The DeepSeek Harness runtime template is missing.")
    for source in sorted(_DEFAULT_AGENT_DIR.iterdir()):
        if source.is_file():
            content = source.read_text(encoding="utf-8")
            if source.name == "compose.yaml":
                content = await configured_compose(content, service_name="harness")
            await harness_manager.write_text_file(
                instance_id,
                source.name,
                content,
            )
    adapter = Path(__file__).with_name("runtime_adapter.py")
    await harness_manager.write_text_file(
        instance_id,
        "runtime_adapter.py",
        adapter.read_text(encoding="utf-8"),
    )
    for placeholder in (
        "data/workspace/.galaris-keep",
        "data/sessions/.galaris-keep",
    ):
        await harness_manager.write_text_file(instance_id, placeholder, "")


async def _sync_skills(agent: Agent) -> str:
    """Replace the isolated DSH skill root with the authorized Galaris snapshot."""

    snapshot = await build_skill_projection(agent.id)
    await harness_manager.delete_tree(agent.code, _MANAGED_SKILLS_ROOT)
    for item in snapshot.files:
        await harness_manager.upload_file_from(
            agent.code,
            f"{_MANAGED_SKILLS_ROOT}/{item.skill_code}/{item.relative_path}",
            item.source,
        )
    logger.info(
        "DeepSeek Harness skills synchronized: agent={} skills={} files={} revision={}",
        agent.code,
        len(snapshot.skill_codes),
        len(snapshot.files),
        snapshot.revision[:12],
    )
    return snapshot.revision


async def _runtime_env(
    agent: Agent,
    request: HarnessProvisioningRequest,
    *,
    api_token: str,
) -> tuple[dict[str, str], str, str]:
    api_url = settings.HARNESS_API_URL
    if not api_url:
        raise RuntimeError("APP_HOST is required for DeepSeek Harness.")
    llm = await get_llm_for_agent(agent)
    if llm is None:
        raise RuntimeError("DeepSeek Harness requires an executor model for the agent.")
    model = str(request.model or llm.code).strip()
    if not model:
        raise RuntimeError("DeepSeek Harness resolved an empty executor model.")
    mcp_token = await mcp_token_service.rotate_system_token(agent.id)
    system_info = await harness_manager.get_system_info()
    runtime_name = _runtime_name(agent.code, request.harness_id)
    return (
        {
            "AGENT_CODE": agent.code,
            "COMPOSE_PROJECT_NAME": runtime_name,
            "CONTAINER_NAME": runtime_name,
            "GALARIS_MCP_URL": f"{api_url}/mcp/{agent.code}",
            "GALARIS_MCP_TOKEN": mcp_token,
            "DEEPSEEK_BASE_URL": f"{api_url}/llm/openai",
            "DEEPSEEK_API_KEY": mcp_token,
            "HARNESS_API_TOKEN": api_token,
            "HARNESS_MODEL": model,
            "DSH_REF": _DSH_REF,
            "DSH_IMAGE": f"galaris/deepseek-harness:{_DSH_VERSION}",
            "RUNTIME_UID": str(int(system_info["uid"])),
            "RUNTIME_GID": str(int(system_info["gid"])),
        },
        f"http://{runtime_name}:8080/v1",
        model,
    )


async def _existing_api_token(agent: Agent) -> str:
    target = await resolve_agent_harness(agent)
    if target is None:
        raise RuntimeError("The agent has no selected DeepSeek Harness.")
    credentials = await get_private_execution_credentials(target.id)
    if not credentials.token:
        raise RuntimeError("The selected DeepSeek Harness has no API token.")
    return credentials.token


async def _synchronize(
    agent: Agent,
    request: HarnessProvisioningRequest,
    *,
    api_token: str,
) -> tuple[str, str, str]:
    await _push_static_files(agent.code)
    skill_revision = await _sync_skills(agent)
    environment, base_url, model = await _runtime_env(
        agent,
        request,
        api_token=api_token,
    )
    await harness_manager.write_text_file(
        agent.code,
        ".env",
        _serialize_env(environment),
    )
    return base_url, model, skill_revision


class DeepSeekHarnessProvider:
    pipeline_policy = DriverPipelinePolicy(
        use_planner=False, use_briefing=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
    )
    code = "deepseek_harness"
    driver_code = "openai_messages"
    label = "DeepSeek Harness"
    containerized = True
    enabled_param: str | None = Params.HARNESS_DEEPSEEK_ENABLED
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
        if not harness_manager.configured:
            raise RuntimeError("The generic Harness manager is not configured.")
        api_token = token or secrets.token_urlsafe(32)
        if agent.code not in await harness_manager.list_instances():
            await harness_manager.create_instance(agent.code)
        try:
            base_url, model, skill_revision = await _synchronize(
                agent,
                request,
                api_token=api_token,
            )
            await harness_manager.run_action(agent.code, "start")
            models = await OpenAIHarnessClient(
                base_url=base_url,
                token=api_token,
            ).list_models()
            if model not in models:
                raise RuntimeError("DeepSeek Harness did not expose its configured model.")
        except Exception:
            try:
                await harness_manager.delete_instance(agent.code)
            except Exception:
                logger.exception(
                    "DeepSeek Harness cleanup failed after provisioning error: agent={}",
                    agent.code,
                )
            await mcp_token_service.revoke_system_tokens(agent.id)
            raise
        return HarnessProvisioningResult(
            base_url=base_url,
            model=model,
            token=api_token,
            capabilities=self.capabilities(),
            metadata={
                "deepseek_harness_version": _DSH_VERSION,
                "deepseek_harness_ref": _DSH_REF,
                "skill_revision": skill_revision,
                "model_gateway": "galaris",
                "galaris_extensions": True,
                "model_passthrough": True,
            },
        )

    async def deprovision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
    ) -> None:
        del request
        try:
            await harness_manager.delete_instance(agent.code)
        finally:
            await mcp_token_service.revoke_system_tokens(agent.id)

    async def status(self, agent: Agent) -> str:
        return await harness_manager.get_instance_status(agent.code)

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        if action in {"restart", "update", "refresh", "start"}:
            target = await resolve_agent_harness(agent)
            if target is None:
                raise RuntimeError("The agent has no selected DeepSeek Harness.")
            api_token = await _existing_api_token(agent)
            request = HarnessProvisioningRequest(
                harness_id=target.id,
                catalogue_harness_id=target.harness_id,
                agent_id=agent.id,
                agent_code=agent.code,
                name=target.name,
                base_url=target.base_url,
                model=target.model,
                revision=target.revision,
            )
            await _synchronize(agent, request, api_token=api_token)
        if action == "refresh":
            return await harness_manager.run_action(agent.code, "restart")
        return await harness_manager.run_action(agent.code, action)

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        return await harness_manager.get_logs(agent.code, lines)


provider = DeepSeekHarnessProvider()

__all__ = ["DeepSeekHarnessProvider", "provider"]
