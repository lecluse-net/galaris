"""The single Skills Tool; authenticated identity and live policy govern every call."""

from typing import Any
from uuid import UUID

from app.tools.mcp_loader import McpToolContext, mcp_tool
from . import interface, skill_service
from .schemas import SkillAuthorizationState, SkillCategoryAuthorizationState


@mcp_tool("skills", approval="enabled", approval_reason="Governed bounded read or polling",
          name="skills_list", description="Discover your usable generic and private personal skills. Management views require the matching live scope; administration=True requires team within the live union of your teams, or all. A foreign target requires that scope and an explicit administrative view. Returns canonical package URIs and stable IDs.")
async def mcp_skills_list(ctx: McpToolContext, agent_id: int | None = None,
                          include_unavailable: bool = False, administration: bool = False,
                          offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("Skills list limit must be between 1 and 500")
    if agent_id is not None and agent_id != ctx.agent_id:
        await interface.require_agent_administration(ctx.agent_id, agent_id)
        if not administration:
            raise PermissionError("A foreign target requires an explicit administrative view")
    return await interface.list_package_summaries(actor_agent_id=ctx.agent_id,
        administration=administration, include_unavailable=include_unavailable, offset=offset, limit=limit,
        target_agent_id=agent_id if administration else None)


@mcp_tool("skills", approval="enabled", approval_reason="Governed bounded read or polling",
          name="skill_read", description="Read exactly the SKILL.md of an authorized package by stable skill_id, or a generic skill_code. For a personal code specify owner_agent_id. References and auxiliary files use File Sharing with the canonical URI. Administrative reads require team within your teams or all, and administration=True; they never make a foreign personal skill usable.")
async def mcp_skill_read(ctx: McpToolContext, skill_id: int | None = None,
                         skill_code: str | None = None, owner_agent_id: int | None = None,
                         administration: bool = False) -> str:
    if (skill_id is None) == (skill_code is None):
        raise ValueError("Specify exactly one of skill_id or skill_code")
    if skill_id is None:
        assert skill_code is not None
        reference = await interface.resolve_package(skill_code, actor_agent_id=ctx.agent_id,
            owner_agent_id=owner_agent_id, administration=administration)
        skill_id = reference.id
    data = await interface.read_package_file(skill_id, "SKILL.md", actor_agent_id=ctx.agent_id,
                                              administration=administration)
    return data.content.decode("utf-8")


@mcp_tool("skills", approval="ask", approval_reason="Modify skill metadata",
          name="skill_update", description="Update a package label using expected_revision. Personal scope manages only your private packages; team can administer packages owned by agents sharing an active team, and all can administer every user package, with administration=True. File contents are edited through File Sharing.")
async def mcp_skill_update(ctx: McpToolContext, skill_id: int, label: str, expected_revision: int,
                           administration: bool = False) -> dict[str, Any]:
    return (await interface.update_package(skill_id, label, actor_agent_id=ctx.agent_id,
        expected_revision=expected_revision, administration=administration)).model_dump(mode="json")


@mcp_tool("skills", approval="ask", approval_reason="Change personal skill activation",
          name="skill_set_enabled", description="Enable or disable a personal package for its owner only. Requires personal scope for your own package, or team within your teams, or all, with administration=True for another owner's package. Generic authorization uses skill_set_authorization.")
async def mcp_skill_set_enabled(ctx: McpToolContext, skill_id: int, enabled: bool, expected_revision: int,
                                administration: bool = False) -> dict[str, Any]:
    return (await interface.set_package_enabled(skill_id, enabled, actor_agent_id=ctx.agent_id,
        expected_revision=expected_revision, administration=administration)).model_dump(mode="json")


@mcp_tool("skills", approval="ask", approval_reason="Delete a skill package",
          name="skill_delete", description="Delete an entire user skill package, including files. Requires its current expected_revision and the matching live management scope. System packages are protected.")
async def mcp_skill_delete(ctx: McpToolContext, skill_id: int, expected_revision: int,
                           administration: bool = False) -> dict[str, Any]:
    return (await interface.delete_package(skill_id, actor_agent_id=ctx.agent_id,
        expected_revision=expected_revision, administration=administration)).model_dump(mode="json")


@mcp_tool("skills", approval="ask", approval_reason="Distribute a generic skill",
          name="skill_set_authorization", description="Set an agent's generic skill authorization to default, enabled or disabled. Requires team for agents sharing an active team, or all. Personal skills can never be assigned to another agent, including by administrators.")
async def mcp_skill_set_authorization(ctx: McpToolContext, skill_id: int, agent_id: int,
                                      state: SkillAuthorizationState) -> dict[str, Any]:
    await interface.require_agent_administration(ctx.agent_id, agent_id)
    result = await skill_service.set_agent_authorization(skill_id, agent_id, state)
    return result.model_dump(mode="json")


@mcp_tool("skills", approval="ask", approval_reason="Distribute a generic skill category",
          name="skill_set_category_authorization", description="Set an agent's generic category authorization. Requires team for agents sharing an active team, or all. Personal packages have no shared category and cannot be distributed this way.")
async def mcp_skill_set_category_authorization(ctx: McpToolContext, category_id: int, agent_id: int,
                                               state: SkillCategoryAuthorizationState) -> dict[str, Any]:
    await interface.require_agent_administration(ctx.agent_id, agent_id)
    applied, affected = await skill_service.set_category_authorization(category_id, agent_id, state)
    return {"state": applied, "affected_agent_ids": affected}


@mcp_tool("skills", approval="ask", approval_reason="Convert a private skill into a generic package",
          name="skill_release_ownership", description="Explicitly remove personal ownership and convert the package to generic, initially disabled for everyone. Requires all, expected_revision and a stable operation_id UUID for retries. On code collision choose new_code. This is the only conversion mechanism; copying or moving private files outside their package is forbidden.")
async def mcp_skill_release_ownership(ctx: McpToolContext, skill_id: int, expected_revision: int,
                                     operation_id: UUID, new_code: str | None = None) -> dict[str, Any]:
    return await interface.release_ownership(skill_id, actor_agent_id=ctx.agent_id,
        expected_revision=expected_revision, operation_id=operation_id, new_code=new_code)
