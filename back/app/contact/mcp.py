"""Self-service MCP access to the calling agent's private contact directory."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.memory import ContactCoordinates
from app.tools import McpToolContext, mcp_tool

from . import service
from .directory import lock_contact_directory
from .schemas import ContactCreate, ContactUpdate


@mcp_tool("galaris", name="contact_list", approval="enabled",
    approval_reason="Bounded read of the calling agent's private contacts",
    description=("List or search your private Contacts by name or coordinates. Returns canonical contact UUIDs, "
                 "identities, phone numbers and postal addresses. Use contact_get before editing a contact."),
    conversation_policy="short", effect_policy="read", concurrency_policy="safe")
async def mcp_contact_list(
    ctx: McpToolContext,
    query: Annotated[str, Field(max_length=500)] = "",
    limit: Annotated[int, Field(ge=1, le=500)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, object]:
    if len(query) > 500 or not 1 <= limit <= 500 or offset < 0:
        raise ValueError("query must have at most 500 characters, limit must be 1–500 and offset nonnegative.")
    return (await service.list_contacts(agent_id=ctx.agent_id, query=query, limit=limit, offset=offset)).model_dump(mode="json")


@mcp_tool("galaris", name="contact_get", approval="enabled",
    approval_reason="Read one contact owned by the calling agent",
    description="Read one of your private Contacts by exact canonical UUID, including its name, identities and coordinates.",
    conversation_policy="short", effect_policy="read", concurrency_policy="safe")
async def mcp_contact_get(ctx: McpToolContext, contact_id: UUID) -> dict[str, object]:
    return (await service.get_contact(agent_id=ctx.agent_id, contact_item_id=contact_id)).model_dump(mode="json")


@mcp_tool("galaris", name="contact_create", approval="ask",
    approval_reason="Create a private address-book entry; a known email also affects inbound Mail admission",
    description=("Create a Contact in your private address book. Supply a display_name and at least one email, phone "
                 "or postal address. Search contact_list first to avoid duplicates. Creates no user and sends no message. "
                 "A saved email becomes a known contact for the default inbound Mail policy."),
    conversation_policy="short")
async def mcp_contact_create(
    ctx: McpToolContext,
    display_name: Annotated[str, Field(min_length=1, max_length=500)],
    email: Annotated[str, Field(max_length=320)] | None = None,
    coordinates: ContactCoordinates | None = None,
) -> dict[str, object]:
    data = ContactCreate.model_validate({"agent_id": ctx.agent_id, "display_name": display_name,
                                        "email": email, "coordinates": coordinates})
    await lock_contact_directory(ctx.agent_id)
    return (await service.create_contact(data)).model_dump(mode="json")


@mcp_tool("galaris", name="contact_update", approval="ask",
    approval_reason="Modify a contact owned by the calling agent",
    description=("Update your Contact's display_name and optionally replace its phone numbers and postal addresses. "
                 "Read contact_get first. Omit coordinates to preserve them; supply the complete desired lists to replace "
                 "them, or empty lists to clear them. Email and messaging identities are preserved and cannot be edited here."),
    conversation_policy="short")
async def mcp_contact_update(
    ctx: McpToolContext,
    contact_id: UUID,
    display_name: Annotated[str, Field(min_length=1, max_length=500)],
    coordinates: ContactCoordinates | None = None,
) -> dict[str, object]:
    data = ContactUpdate(display_name=display_name, coordinates=coordinates)
    await lock_contact_directory(ctx.agent_id)
    await service.get_contact(agent_id=ctx.agent_id, contact_item_id=contact_id)
    return (await service.update_contact(contact_item_id=contact_id, data=data)).model_dump(mode="json")
