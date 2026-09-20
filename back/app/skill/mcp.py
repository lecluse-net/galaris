"""Restricted MCP tools for inspecting centrally managed skills."""

from __future__ import annotations

from typing import Any

from app.tools.mcp_loader import McpToolContext, mcp_tool

from . import skill_service, storage


@mcp_tool(
    "skill_management",
    name="skills_list",
    description=(
        "List the Galaris skills available to a given agent. By default only effectively enabled, "
        "valid, and present skills are returned. Set include_unavailable to inspect disabled, "
        "invalid, or missing catalog entries and their authorization states."
    ),
)
async def mcp_skills_list(
    ctx: McpToolContext,  # noqa: ARG001
    agent_id: int,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    """Return effective skill availability for one internal or Hermes agent."""


    authorizations = await skill_service.list_authorizations(agent_id=agent_id)
    if not include_unavailable:
        authorizations = [item for item in authorizations if item.effective]
    return [dict(item.model_dump(mode="json")) for item in authorizations]


@mcp_tool(
    "skill_management",
    name="skill_read",
    description=(
        "Read the complete SKILL.md file of one skill from the central Galaris skill library. "
        "Only SKILL.md is exposed; referenced files and other package contents are not returned."
    ),
)
async def mcp_skill_read(
    ctx: McpToolContext,  # noqa: ARG001
    skill_code: str,
) -> str:
    """Return exactly one centrally indexed skill's full SKILL.md text."""


    code = storage.validate_code(skill_code)
    record = await skill_service.get_by_code(code)
    if record is None:
        raise ValueError(f"Skill not found: {code}")
    inspection = storage.inspect(code)
    if not inspection.available:
        raise ValueError(f"Skill files are unavailable: {code}")
    return storage.read_text(code, "SKILL.md")
