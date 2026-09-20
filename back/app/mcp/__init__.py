"""Public unified MCP server for each agent.

Each agent exposes one Streamable HTTP server at ``/api/mcp/{agent_code}``,
combining native Galaris tools and external MCP servers. Access uses dedicated
per-agent MCP tokens managed from the agent's MCP settings.

The transport-agnostic aggregated server is built centrally by
``app.tools.mcp_loader.build_agent_mcp`` and imported lazily by the router to
avoid coupling module loading to the Hermes bridge.
"""

from . import service as mcp_token_service
from .models import AgentMcpToken

__all__ = ["mcp_token_service", "AgentMcpToken"]
