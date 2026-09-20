"""Manually list the MCP tools exposed to a Hermes agent.

Usage:
    HERMES_MCP_AGENT_ID=1 docker compose exec backend \
        python scripts/manual_test.py tests/manual/hermes_mcp_tools.py
"""

import os

from loguru import logger

from app.tools.mcp_loader import build_agent_mcp


async def main() -> None:
    agent_id = int(os.getenv("HERMES_MCP_AGENT_ID", "1"))
    mcp = await build_agent_mcp(agent_id, runtime="hermes")
    tools = await mcp.list_tools()
    logger.info("Tools MCP agent_id={} count={}", agent_id, len(tools))
    for tool in sorted(tools, key=lambda item: item.name):
        logger.info("- {}", tool.name)
