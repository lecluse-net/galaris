"""Manual diagnostic for the internal harness's aggregated in-process MCP toolset.

Usage:
    AGENT_ID=1 docker compose exec backend \
        python scripts/manual_test.py tests/manual/agent_mcp_toolset.py
"""

import os
from loguru import logger
from app.harness.mcp_toolset import build_agent_mcp_toolset


async def main() -> None:
    agent_id = int(os.getenv("AGENT_ID", "1"))
    toolset = await build_agent_mcp_toolset(agent_id)
    tools = await toolset.list_tools()
    logger.info("Aggregated in-process MCP toolset agent_id={} count={}", agent_id, len(tools))
    for tool in sorted(tools, key=lambda item: item.name):
        logger.info("- {}", tool.name)
