"""MCP tools for the agent module."""

from __future__ import annotations

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool


@mcp_tool(
    "galaris",
    name="agent_list",
    description=(
        "List Galaris agents with profile text truncated to 100 characters. "
        "Use agent_get for a complete profile."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def list_agents(ctx: McpToolContext, limit: int = 50) -> str:
    """List every available Galaris agent with truncated profile text."""
    from app.agent import tools as agent_tools

    language = await context_language(ctx)
    return await agent_tools.list_agents(limit=limit, language=language)


@mcp_tool(
    "galaris",
    name="agent_get",
    description=(
        "Return a complete agent profile, including full job and personality text, "
        "using an ID obtained from agent_list."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def get_agent(ctx: McpToolContext, agent_id: int) -> str:
    """Return one complete detailed agent profile."""
    from app.agent import tools as agent_tools

    language = await context_language(ctx)
    return await agent_tools.get_agent_details(agent_id, language=language)
