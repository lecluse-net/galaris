"""Manual Hermes-agent diagnostic for the voice proof of concept.

Usage:
    docker compose exec backend python scripts/manual_test.py tests/manual/hermes_voice_agents.py

Optional:
    Set HERMES_SYNC_AGENT_ID=1 to synchronize the configured model, tools, STT,
    and TTS resources, then restart that agent.
"""

import os

from loguru import logger

from app.agent import agent_service
from bridge.hermes.manager import manager as hermes_manager


async def main() -> None:
    agents = await agent_service.get_all(limit=200)
    sync_id = os.getenv("HERMES_SYNC_AGENT_ID", "").strip()
    for agent in agents:
        if agent.agent_driver != "hermes":
            continue
        logger.info(
            "Hermes agent id={} code={} name='{} {}' url={} model={}",
            agent.id,
            agent.code,
            agent.first_name,
            agent.last_name,
            agent.hermes_url,
            agent.hermes_model,
        )
        if sync_id and str(agent.id) == sync_id:
            logger.info("Syncing Hermes voice configuration for agent id={} code={}", agent.id, agent.code)
            await hermes_manager.get_agent(agent).sync()
            logger.success("Hermes voice configuration sync completed for {}", agent.code)
