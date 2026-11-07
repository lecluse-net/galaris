"""MCP tools for the agent module."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from .admin_schemas import PageLimit, PageOffset


@mcp_tool("galaris", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect",

    name="agent_list",
    description=(
        "List Galaris agents in compact JSON pages with ID, profile URI, code, name and job title. "
        "Optionally filter by team_id or exact team_name (case-insensitive); both filters intersect. "
        "Follow next_offset until null; a page may contain fewer than limit entries to stay bounded. "
        "Keep the same team filters on subsequent pages. "
        "Use agent_get for full profiles and assigned models, or team_list and team_members for teams and their human/agent members."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def list_agents(
    ctx: McpToolContext, limit: PageLimit = 50, offset: PageOffset = 0,
    team_id: Annotated[int, Field(gt=0)] | None = None,
    team_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None,
) -> str:
    """List a bounded directory page with an explicit continuation offset."""
    from app.agent import tools as agent_tools

    language = await context_language(ctx)
    return await agent_tools.list_agents(
        limit=limit, offset=offset, language=language, team_id=team_id, team_name=team_name,
    )


@mcp_tool("galaris", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect",

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


@mcp_tool("galaris", name="team_list", approval="enabled",
    approval_reason="Read the shared team directory without granting access or changing memberships",
    description=(
        "Discover shared teams across this Galaris instance, including empty teams, with IDs, name/description previews "
        "and counts of active humans and non-deleted agents. Search is a literal case-insensitive name substring. "
        "Use team_members(team_id) for the roster. Follow next_offset until null, preserving search. "
        "Pages can be shorter than limit. No AgentAdmin delegation or document is required; no contact or management rights are granted."
    ), effect_policy="read", concurrency_policy="safe")
async def team_list(
    ctx: McpToolContext, search: Annotated[str, Field(max_length=200)] = "",
    offset: PageOffset = 0, limit: PageLimit = 50,
) -> str:
    from .team_directory import list_team_directory

    return (await list_team_directory(search=search, offset=offset, limit=limit)).model_dump_json()


@mcp_tool("galaris", name="team_members", approval="enabled",
    approval_reason="Read current team memberships without granting access or changing them",
    description=(
        "List one team's active human users and non-deleted agents using a team_id from team_list. "
        "Each identity is the pair (kind, id): user and agent IDs can overlap. "
        "Optionally filter kind=agent/user and a literal case-insensitive name substring search. "
        "Follow next_offset until null, preserving team_id, kind and search; pages can be shorter than limit. "
        "Unknown/deleted teams fail. Human emails and account details are excluded. Discovery grants no contact, sharing or management rights."
    ), effect_policy="read", concurrency_policy="safe")
async def team_members(
    ctx: McpToolContext, team_id: Annotated[int, Field(gt=0)],
    kind: Literal["agent", "user"] | None = None,
    search: Annotated[str, Field(max_length=200)] = "", offset: PageOffset = 0, limit: PageLimit = 50,
) -> str:
    from .team_directory import list_team_members

    try:
        return (await list_team_members(team_id, kind=kind, search=search, offset=offset, limit=limit)).model_dump_json()
    except LookupError as error:
        raise ValueError("Team not found; refresh team_list and select a current team ID") from error


from typing import Any
from sqlalchemy import select

from core.database import get_db
from core.team import notify_team_access_changed
from .admin_authorization import delegated_admin
from .admin_schemas import AdminAgentCreate, AdminAgentUpdate
from .registry import INTERNAL_HARNESS
from . import admin_service, agent_service, title_service, agent_group_service
from .schemas import Title as TitleRead, TitleCreate, TitleUpdate, AgentGroup as GroupRead, AgentGroupCreate, AgentGroupUpdate


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_create", description="Create an internally harnessed agent with a human manager and HTML personality/job description.")
async def agent_create(ctx: McpToolContext, configuration: AdminAgentCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_create", "AGENT_EDIT") as grant:
        assert configuration.user_id is not None
        grant.manager_change(None, configuration.user_id)
        if grant.delegation_level != "all" and not configuration.team_ids:
            raise PermissionError("A new agent must belong to a delegated team")
        for team_id in configuration.team_ids:
            await grant.team(team_id)
        if configuration.agent_driver != INTERNAL_HARNESS.code:
            raise ValueError("Create with the internal Harness before selecting another")
        created = await agent_service.create(configuration, actor_user_id=grant.manager.id)
        return await admin_service.projection(created.id)


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_update", description="Update explicitly supplied agent fields; null clears nullable fields. Code and Harness are immutable here.", effect_policy="idempotent")
async def agent_update(ctx: McpToolContext, agent_id: int, changes: AdminAgentUpdate) -> dict[str, Any]:
    if {"code", "agent_driver"} & changes.model_fields_set:
        raise ValueError("Code and Harness cannot be updated here")
    async with delegated_admin(ctx.agent_id, "agent_update", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        if "team_ids" in changes.model_fields_set:
            from .models import Agent, AgentTeam
            await get_db().scalar(select(Agent.id).where(Agent.id == agent_id).with_for_update())
            previous = set(await get_db().scalars(select(AgentTeam.team_id).where(AgentTeam.agent_id == agent_id)))
            for team_id in previous ^ set(changes.team_ids):
                await grant.team(team_id)
        if "user_id" in changes.model_fields_set:
            assert changes.user_id is not None
            if not grant.scope.is_global:
                raise PermissionError("Global management is required to change a manager")
            grant.manager_change(agent_id, changes.user_id)
        await agent_service.update(agent_id, changes, actor_user_id=grant.manager.id)
        return await admin_service.projection(agent_id)


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_delete", description="Soft-delete an agent in the delegated management scope.", effect_policy="idempotent")
async def agent_delete(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_delete", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        if agent_id == ctx.agent_id:
            raise PermissionError("An administrator agent cannot delete itself")
        if not await agent_service.delete(agent_id):
            raise LookupError("Agent not found")
        return {"agent_id": agent_id, "resource_uri": f"galaris://agent/{agent_id}", "deleted": True}


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", name="agent_options", description="List selectable managers, LLM profiles, voices or existing Harnesses without credentials.", effect_policy="read", concurrency_policy="safe")
async def agent_options(ctx: McpToolContext, category: Literal["managers", "profiles", "voices", "harnesses"], skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_options", "AGENT_EDIT") as grant:
        return await admin_service.options(grant, category, skip, limit)


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_avatar_delete", description="Remove an agent avatar.", effect_policy="idempotent")
async def agent_avatar_delete(ctx: McpToolContext, agent_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_avatar_delete", "AGENT_EDIT") as grant:
        await grant.target(agent_id)
        await agent_service.delete_avatar(agent_id)
        return await admin_service.projection(agent_id)


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", name="agent_team_list", description="List shared teams and the target's membership.", effect_policy="read", concurrency_policy="safe")
async def agent_team_list(ctx: McpToolContext, agent_id: int, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_team_list", "AGENT_EDIT", "TEAM_ACCESS") as grant:
        await grant.target(agent_id)
        return await admin_service.teams(agent_id, skip, limit)


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_team_set", description="Idempotently add or remove a target's shared team membership.", effect_policy="idempotent")
async def agent_team_set(ctx: McpToolContext, agent_id: int, team_id: int, present: bool) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_team_set", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_MEMBERS_EDIT") as grant:
        await grant.target(agent_id)
        await grant.team(team_id)
        return await admin_service.team_set(agent_id, team_id, present)


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", name="agent_title_list", description="List existing titles and their gender values.", effect_policy="read", concurrency_policy="safe")
async def agent_title_list(ctx: McpToolContext, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_list", "AGENT_EDIT"):
        return {"items": [TitleRead.model_validate(t).model_dump() for t in await title_service.get_all(skip, limit)], "skip": skip, "limit": limit}


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_title_create", description="Create a shared title with its existing M/F gender contract; requires global management.")
async def agent_title_create(ctx: McpToolContext, configuration: TitleCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_create", "AGENT_EDIT", global_scope=True):
        return TitleRead.model_validate(await title_service.create(configuration)).model_dump()


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_title_update", description="Update a shared title; requires global management.", effect_policy="idempotent")
async def agent_title_update(ctx: McpToolContext, title_id: int, changes: TitleUpdate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_update", "AGENT_EDIT", global_scope=True) as grant:
        await grant.reference(title_id, title=True)
        if any(v is None for v in changes.model_dump(exclude_unset=True).values()):
            raise ValueError("Title fields cannot be null")
        title = await title_service.update(title_id, changes)
        if title is None:
            raise LookupError("Title not found")
        return TitleRead.model_validate(title).model_dump()


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_title_delete", description="Delete an unused shared title; referenced titles cannot be removed.", effect_policy="idempotent")
async def agent_title_delete(ctx: McpToolContext, title_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_title_delete", "AGENT_EDIT", global_scope=True) as grant:
        await grant.reference(title_id, title=True)
        if not await title_service.delete(title_id):
            raise LookupError("Title not found")
        return {"title_id": title_id, "deleted": True}


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", name="agent_group_list", description="List shared agent groups/teams.", effect_policy="read", concurrency_policy="safe")
async def agent_group_list(ctx: McpToolContext, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_list", "AGENT_EDIT", "TEAM_ACCESS"):
        return {"items": [GroupRead.model_validate(t).model_dump() for t in await agent_group_service.get_all(skip, limit)], "skip": skip, "limit": limit}


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_group_create", description="Create a shared group/team; requires global management and team edit rights.")
async def agent_group_create(ctx: McpToolContext, configuration: AgentGroupCreate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_create", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True):
        return GroupRead.model_validate(await agent_group_service.create(configuration)).model_dump()


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_group_update", description="Rename or reorder a shared group/team.", effect_policy="idempotent")
async def agent_group_update(ctx: McpToolContext, group_id: int, changes: AgentGroupUpdate) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_update", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True) as grant:
        await grant.reference(group_id)
        if any(v is None for v in changes.model_dump(exclude_unset=True).values()):
            raise ValueError("Group fields cannot be null")
        group = await agent_group_service.update(group_id, changes)
        if group is None:
            raise LookupError("Group not found")
        return GroupRead.model_validate(group).model_dump()


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_group_delete", description="Soft-delete a shared team, detach legacy group references and revoke its memberships.", effect_policy="idempotent")
async def agent_group_delete(ctx: McpToolContext, group_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_group_delete", "AGENT_EDIT", "TEAM_ACCESS", "TEAM_EDIT", global_scope=True) as grant:
        await grant.reference(group_id)
        if not await agent_group_service.delete(group_id):
            raise LookupError("Group not found")
        await notify_team_access_changed()
        return {"group_id": group_id, "deleted": True}


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_avatar_set", description="Replace an agent avatar from an authorized canonical resource URI; validates image bytes and dimensions.", effect_policy="idempotent")
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
    from .avatar_generation import avatar_generation_available
    return await avatar_generation_available(ctx.agent_id)


@mcp_tool("agent_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="agent_avatar_generate", description="Generate or regenerate and replace another agent's avatar using your image model. Pass the user's appearance and style instructions, including realistic human portraits. Uses the target's saved identity, personality and job as context. Waits for registration and returns registered=true on success; no separate image Tool is required. Stores a JPEG within 500x500 pixels.", available_when=_avatar_available)
async def agent_avatar_generate(ctx: McpToolContext, agent_id: int, instructions: Annotated[str, Field(max_length=4000)] = "") -> dict[str, Any]:
    from .avatar_generation import generate_avatar
    return await generate_avatar(ctx.agent_id, agent_id, instructions, task_id=ctx.task_id)
