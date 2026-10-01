"""MCP owns the reusable principal; Tools owns the per-run authority."""
from sqlalchemy import select

from app.tools.facade import RuntimePrincipal, register_runtime_principal_port
from core.database import get_db

from .models import AgentMcpToken
from .service import get_enabled_system_token_by_value


class McpRuntimePrincipalPort:
    @staticmethod
    def _projection(token: AgentMcpToken | None) -> RuntimePrincipal | None:
        return RuntimePrincipal(token.id, token.agent_id, token.enabled) if token is not None else None

    async def for_agent(self, agent_id: int) -> RuntimePrincipal | None:
        return self._projection(await get_db().scalar(select(AgentMcpToken).where(
            AgentMcpToken.agent_id == agent_id, AgentMcpToken.hidden.is_(True), AgentMcpToken.enabled.is_(True))))

    async def by_key(self, token_key: int) -> RuntimePrincipal | None:
        return self._projection(await get_db().get(AgentMcpToken, token_key, populate_existing=True))

    async def authenticate(self, bearer: str) -> RuntimePrincipal | None:
        return self._projection(await get_enabled_system_token_by_value(bearer))


register_runtime_principal_port(McpRuntimePrincipalPort())
