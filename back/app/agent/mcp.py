"""MCP tools for the agent module."""

from __future__ import annotations

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool


@mcp_tool(
    "galaris",
    name="agent_list",
    description=(
        "List Galaris agents with profile text truncated to 100 characters. "
        "Includes each profile's galaris://agent/<id> URI for file_read under existing access rights. "
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
        "using an ID obtained from agent_list. Includes its live galaris://agent/<id> URI "
        "for file_read under existing access rights; no document is created."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def get_agent(ctx: McpToolContext, agent_id: int) -> str:
    """Return one complete detailed agent profile."""
    from app.agent import tools as agent_tools

    language = await context_language(ctx)
    return await agent_tools.get_agent_details(agent_id, language=language)


from typing import Any, Literal

from core.team import notify_team_access_changed
from .admin_authorization import delegated_admin
from .admin_schemas import AdminAgentCreate, AdminAgentUpdate, PageLimit, PageOffset
from . import admin_service, agent_service, title_service, agent_group_service
from .schemas import Title as TitleRead, TitleCreate, TitleUpdate, AgentGroup as GroupRead, AgentGroupCreate, AgentGroupUpdate


@mcp_tool("agent_admin", name="agent_create", description="Create an internally harnessed agent with a human manager and HTML personality/job description.")
async def agent_create(ctx: McpToolContext, configuration: AdminAgentCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_create", "AGENT_EDIT") as grant:
        assert configuration.user_id is not None
        grant.manager_change(None, configuration.user_id)
        if configuration.agent_driver != "internal":
            raise ValueError("Create with the internal Harness before selecting another")
        created = await agent_service.create(configuration, actor_user_id=grant.manager.id)
        return await admin_service.projection(created.id)


@mcp_tool("agent_admin", name="agent_update", description="Update explicitly supplied agent fields; null clears nullable fields. Code and Harness are immutable here.", effect_policy="idempotent")
async def agent_update(ctx: McpToolContext, agent_id: int, changes: AdminAgentUpdate) -> dict[str, Any]:
    if {"code", "agent_driver"} & changes.model_fields_set:
        raise ValueError("Code and Harness cannot be updated here")
    async with delegated_admin(ctx.agent_id, "agent_update", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        if "user_id" in changes.model_fields_set:
            assert changes.user_id is not None
            if not grant.scope.is_global:
                raise PermissionError("Global management is required to change a manager")
            grant.manager_change(agent_id, changes.user_id)
        await agent_service.update(agent_id, changes, actor_user_id=grant.manager.id)
        return await admin_service.projection(agent_id)


@mcp_tool("agent_admin", name="agent_delete", description="Soft-delete an agent in the delegated management scope.", effect_policy="idempotent")
async def agent_delete(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_delete", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        if agent_id == ctx.agent_id:
            raise PermissionError("An administrator agent cannot delete itself")
        if not await agent_service.delete(agent_id):
            raise LookupError("Agent not found")
        return {"agent_id": agent_id, "resource_uri": f"galaris://agent/{agent_id}", "deleted": True}


@mcp_tool("agent_admin", name="agent_options", description="List selectable managers, LLM profiles, voices or existing Harnesses without credentials.", effect_policy="read", concurrency_policy="safe")
async def agent_options(ctx: McpToolContext, category: Literal["managers", "profiles", "voices", "harnesses"], skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_options", "AGENT_EDIT") as grant:
        return await admin_service.options(grant, category, skip, limit)


@mcp_tool("agent_admin", name="agent_avatar_delete", description="Remove an agent avatar.", effect_policy="idempotent")
async def agent_avatar_delete(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_avatar_delete", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        await agent_service.delete_avatar(agent_id)
        return await admin_service.projection(agent_id)


@mcp_tool("agent_admin", name="agent_team_list", description="List shared teams and the target's membership.", effect_policy="read", concurrency_policy="safe")
async def agent_team_list(ctx: McpToolContext, agent_id: int, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_team_list", "AGENT_EDIT", "TEAM_ACCESS") as grant:
        await grant.target(agent_id)
        return await admin_service.teams(agent_id, skip, limit)


@mcp_tool("agent_admin", name="agent_team_set", description="Idempotently add or remove a target's shared team membership.", effect_policy="idempotent")
async def agent_team_set(ctx: McpToolContext, agent_id: int, team_id: int, present: bool) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_team_set", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_MEMBERS_EDIT") as grant:
        await grant.target(agent_id)
        return await admin_service.team_set(agent_id, team_id, present)


@mcp_tool("agent_admin", name="agent_title_list", description="List existing titles and their gender values.", effect_policy="read", concurrency_policy="safe")
async def agent_title_list(ctx: McpToolContext, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_list", "AGENT_EDIT"):
        return {"items": [TitleRead.model_validate(t).model_dump() for t in await title_service.get_all(skip, limit)], "skip": skip, "limit": limit}


@mcp_tool("agent_admin", name="agent_title_create", description="Create a shared title with its existing M/F gender contract; requires global management.")
async def agent_title_create(ctx: McpToolContext, configuration: TitleCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_create", "AGENT_EDIT", global_scope=True):
        return TitleRead.model_validate(await title_service.create(configuration)).model_dump()


@mcp_tool("agent_admin", name="agent_title_update", description="Update a shared title; requires global management.", effect_policy="idempotent")
async def agent_title_update(ctx: McpToolContext, title_id: int, changes: TitleUpdate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_update", "AGENT_EDIT", global_scope=True):
        if any(v is None for v in changes.model_dump(exclude_unset=True).values()):
            raise ValueError("Title fields cannot be null")
        title = await title_service.update(title_id, changes)
        if title is None:
            raise LookupError("Title not found")
        return TitleRead.model_validate(title).model_dump()


@mcp_tool("agent_admin", name="agent_title_delete", description="Delete an unused shared title; referenced titles cannot be removed.", effect_policy="idempotent")
async def agent_title_delete(ctx: McpToolContext, title_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_delete", "AGENT_EDIT", global_scope=True):
        if not await title_service.delete(title_id):
            raise LookupError("Title not found")
        return {"title_id": title_id, "deleted": True}


@mcp_tool("agent_admin", name="agent_group_list", description="List shared agent groups/teams.", effect_policy="read", concurrency_policy="safe")
async def agent_group_list(ctx: McpToolContext, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_list", "AGENT_EDIT", "TEAM_ACCESS"):
        return {"items": [GroupRead.model_validate(t).model_dump() for t in await agent_group_service.get_all(skip, limit)], "skip": skip, "limit": limit}


@mcp_tool("agent_admin", name="agent_group_create", description="Create a shared group/team; requires global management and team edit rights.")
async def agent_group_create(ctx: McpToolContext, configuration: AgentGroupCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_create", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True):
        return GroupRead.model_validate(await agent_group_service.create(configuration)).model_dump()


@mcp_tool("agent_admin", name="agent_group_update", description="Rename or reorder a shared group/team.", effect_policy="idempotent")
async def agent_group_update(ctx: McpToolContext, group_id: int, changes: AgentGroupUpdate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_update", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True):
        if any(v is None for v in changes.model_dump(exclude_unset=True).values()):
            raise ValueError("Group fields cannot be null")
        group = await agent_group_service.update(group_id, changes)
        if group is None:
            raise LookupError("Group not found")
        return GroupRead.model_validate(group).model_dump()


@mcp_tool("agent_admin", name="agent_group_delete", description="Soft-delete a shared team, detach legacy group references and revoke its memberships.", effect_policy="idempotent")
async def agent_group_delete(ctx: McpToolContext, group_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_delete", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True):
        if not await agent_group_service.delete(group_id):
            raise LookupError("Group not found")
        await notify_team_access_changed()
        return {"group_id": group_id, "deleted": True}


@mcp_tool("agent_admin", name="agent_avatar_set", description="Replace an agent avatar from an authorized canonical resource URI; validates image bytes and dimensions.", effect_policy="idempotent")
async def agent_avatar_set(ctx: McpToolContext, agent_id: int, uri: str) -> dict[str, Any]:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from app.file_share import ResourceContext, materialize_resource
    from .avatars import MAX_AVATAR_BYTES
    async with delegated_admin(ctx.agent_id, "agent_avatar_set", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        with TemporaryDirectory(prefix="galaris-avatar-") as temporary:
            destination = Path(temporary) / "avatar"
            await materialize_resource(ResourceContext(ctx.agent_id, ctx.runtime, ctx.task_id), uri,
                                       destination, max_bytes=MAX_AVATAR_BYTES)
            content = destination.read_bytes()
        # The transfer may be long. Resolve the live delegation again before storage.
        async with delegated_admin(ctx.agent_id, "agent_avatar_set", "AGENT_EDIT") as current:
            await current.target(agent_id)
            await agent_service.update_avatar(agent_id, content)
        return await admin_service.projection(agent_id)


async def _avatar_available(ctx: McpToolContext) -> bool:
    from .avatar_engine import avatar_generation_available
    return await avatar_generation_available(ctx.agent_id)


@mcp_tool("agent_admin", name="agent_avatar_generate", description="Queue a photographic avatar using your effective image model and the target profile. Returns a durable Process URI; queued is not registered.", available_when=_avatar_available)
async def agent_avatar_generate(ctx: McpToolContext, agent_id: int, instructions: str = "") -> dict[str, Any]:
    from app.process import process_service
    from app.process.interface import ensure_integrated_definition
    async with delegated_admin(ctx.agent_id, "agent_avatar_generate", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        if not await _avatar_available(ctx):
            raise ValueError("A usable image generation model is required")
        if len(instructions) > 4000:
            raise ValueError("Avatar instructions exceed 4000 characters")
        workflow = await ensure_integrated_definition(ctx.agent_id, "agent_admin", "avatar")
        result = await process_service.start_process(agent_id=ctx.agent_id, workflow_id=workflow,
            input_data={"target_id": agent_id, "runtime": ctx.runtime, "instructions": instructions},
            task_id=ctx.task_id, runtime=ctx.runtime)
        return {"agent_id": agent_id, "resource_uri": f"galaris://agent/{agent_id}", "status": result.status,
                "registered": False, "process_uri": f"galaris://process/{workflow}", "run_id": str(result.run_id),
                "follow_up": {"tool": "process_get_run", "arguments": {"run_id": str(result.run_id)}}}
