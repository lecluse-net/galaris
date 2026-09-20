"""Verify without exposing secrets that every Hermes agent uses the Galaris gateway."""

import httpx
import yaml
from loguru import logger
from sqlalchemy import select

from app.agent import agent_service
from app.mcp.models import AgentMcpToken
from bridge.hermes.manager import _DIRECT_LLM_KEY_ENVS, manager as hermes_manager
from core.database import get_db
from core.settings import settings
from core.util.encryption import decrypt_value


async def main() -> None:
    agents = await agent_service.get_all(limit=200)
    proxy_checks: list[tuple[str, str, str, str]] = []
    for agent in agents:
        if agent.agent_driver != "hermes":
            continue
        runtime = hermes_manager.get_agent(agent)
        config = yaml.safe_load(await runtime.read_file("data/config.yaml")) or {}
        env_lines = await runtime.read_file("data/.env")
        compose = yaml.safe_load(await runtime.read_file("compose.yaml")) or {}
        env_keys = {
            line.split("=", 1)[0].strip()
            for line in env_lines.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }
        model = config.get("model") or {}
        direct_keys = sorted(env_keys.intersection(_DIRECT_LLM_KEY_ENVS))
        compose_env = compose.get("services", {}).get("agent", {}).get("environment", [])
        compose_keys = {
            str(entry).split("=", 1)[0].strip()
            for entry in compose_env
        } if isinstance(compose_env, list) else set(compose_env)
        direct_compose_keys = sorted(compose_keys.intersection(_DIRECT_LLM_KEY_ENVS))
        expected_url = f"{settings.APP_API_URL}/llm/openai"
        ok = (
            model.get("provider") == "custom"
            and model.get("base_url") == expected_url
            and bool(model.get("default"))
            and model.get("api_key") == "${GALARIS_LLM_API_KEY}"
            and "GALARIS_LLM_API_KEY" in env_keys
            and not direct_keys
            and not direct_compose_keys
        )
        logger.info(
            "Hermes LLM gateway agent={} status={} model={} provider={} url={} direct_keys={} compose_keys={} ok={}",
            agent.code,
            await runtime.get_status(),
            model.get("default"),
            model.get("provider"),
            model.get("base_url"),
            direct_keys,
            direct_compose_keys,
            ok,
        )
        if not ok:
            raise RuntimeError(f"Invalid Hermes LLM configuration for {agent.code}")

        token_record = (await get_db().execute(
            select(AgentMcpToken).where(
                AgentMcpToken.agent_id == agent.id,
                AgentMcpToken.hidden.is_(True),
                AgentMcpToken.enabled.is_(True),
            )
        )).scalar_one()
        token = decrypt_value(token_record.token_encrypted)
        proxy_checks.append((agent.code, expected_url, token, str(config["model"]["default"])))

    # The manual runner keeps a database session for the whole script. Release it before the
    # HTTP call back into Galaris so the endpoint can obtain its own connection.
    await get_db().commit()
    await get_db().close()
    for agent_code, expected_url, token, expected_model in proxy_checks:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{expected_url}/models",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            models = response.json().get("data", [])
        if not any(model.get("id") == expected_model for model in models):
            raise RuntimeError(f"Proxy model missing for {agent_code}")
        logger.info("Authenticated LLM proxy agent={} models={}", agent_code, len(models))
