"""
Onboarding services.

These helpers inspect the configuration state of individual modules.
"""
from collections.abc import Collection

from sqlalchemy import func, select

from core.database import get_db

from app.llm import LLM, LLMProvider
from app.agent.models import Agent
from app.connection.models import Connection
from app.messenger import enabled_specs, kind_for_tool
from app.process import has_process_definitions
from app.skill import has_configured_skills
from app.tools.models import Tool as ToolModel


async def check_llm_status() -> bool:
    """
    Check whether at least one configured LLM is available.

    Returns:
        Whether a non-deleted chat-capable LLM belongs to an active,
        non-deleted provider.
    """
    db = get_db()

    query = (
        select(func.count())
        .select_from(LLM)
        .join(LLMProvider, LLM.llm_provider_id == LLMProvider.id)
        .where(
            LLMProvider.is_active.is_(True),
            LLM.service_capabilities.contains(["chat"]),
        )
    )
    query = LLM.histo_filter(query)
    query = LLMProvider.histo_filter(query)
    result = await db.execute(query)
    count = result.scalar() or 0
    return count > 0


async def check_agent_status(
    *, agent_ids: Collection[int] | None = None
) -> bool:
    """
    Check whether at least one non-deleted agent exists.

    Returns:
        Whether an agent exists.
    """
    db = get_db()

    # Apply the standard history filter to exclude deleted agents.
    query = select(func.count()).select_from(Agent)
    query = Agent.histo_filter(query)
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    result = await db.execute(query)
    count = result.scalar() or 0
    return count > 0


async def check_messaging_status(
    *, agent_ids: Collection[int] | None = None
) -> bool:
    """
    Check whether at least one active messaging connection exists.

    Returns:
        Whether an active connection belongs to an enabled messaging bridge.
    """
    db = get_db()

    specs = enabled_specs()
    enabled_kinds = {spec.kind for spec in specs}
    if not enabled_kinds:
        return False

    query = (
        select(ToolModel)
            .join(Connection, ToolModel.id == Connection.tool_id)
            .where(Connection.active.is_(True))
            .distinct()
    )
    if agent_ids is not None:
        query = query.where(Connection.agent_id.in_(agent_ids))
    rows = (await db.execute(query)).scalars().all()
    return any(
        kind_for_tool(tool) in enabled_kinds
        for tool in rows
    )


async def check_tools_status() -> bool:
    """
    Check whether at least one tool is configured.

    Returns:
        Whether the database contains a configured tool.
    """
    from app.tools import tool_service

    tools = await tool_service.get_all_tools()
    return len(tools) > 0


async def check_skills_status() -> bool:
    """Return whether at least one skill is configured."""
    return await has_configured_skills()


async def check_processes_status(
    *, agent_ids: Collection[int] | None = None
) -> bool:
    """Return whether at least one process definition is in scope."""
    return await has_process_definitions(agent_ids=agent_ids)
