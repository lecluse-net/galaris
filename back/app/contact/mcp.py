"""MCP access to Contact directories within the caller's live delegation."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.agent import get_agent_record
from app.memory import ContactCoordinates, MemoryNotFoundError
from app.services import McpToolContext, mcp_tool
from app.services.facade import AdministrationScope, administration_scope

from . import service
from .directory import lock_contact_directory
from .schemas import ContactCreate, ContactUpdate


async def _scope(ctx: McpToolContext) -> AdministrationScope:
    scope = await administration_scope(ctx.agent_id, "contact")
    scope.require_administration()
    return scope


@mcp_tool("contact", name="contact_list", approval="enabled",
    approval_reason="Bounded read of contact directories within the delegated scope",
    description=("List or search Contacts by name or coordinates within your delegated Contact scope. "
                 "Optionally filter by owner_agent_id. Returns the owning agent, canonical contact UUIDs, "
                 "identities, phone numbers and postal addresses. Use contact_get before editing a contact."),
    conversation_policy="short", effect_policy="read", concurrency_policy="safe")
async def mcp_contact_list(
    ctx: McpToolContext,
    query: Annotated[str, Field(max_length=500)] = "",
    limit: Annotated[int, Field(ge=1, le=500)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
    owner_agent_id: Annotated[int, Field(gt=0)] | None = None,
) -> dict[str, object]:
    if len(query) > 500 or not 1 <= limit <= 500 or offset < 0:
        raise ValueError("query must have at most 500 characters, limit must be 1–500 and offset nonnegative.")
    scope = await _scope(ctx)
    if owner_agent_id is not None:
        scope.require(owner_agent_id)
        page = await service.list_contacts(agent_id=owner_agent_id, query=query, limit=limit, offset=offset)
    else:
        page = await service.list_contacts_for_owners(owner_agent_ids=scope.agent_ids, query=query, limit=limit, offset=offset)
    return page.model_dump(mode="json")


@mcp_tool("contact", name="contact_get", approval="enabled",
    approval_reason="Read one contact within the delegated scope",
    description="Read one Contact in your delegated scope by exact canonical UUID, including its owner, name, identities and coordinates.",
    conversation_policy="short", effect_policy="read", concurrency_policy="safe")
async def mcp_contact_get(ctx: McpToolContext, contact_id: UUID) -> dict[str, object]:
    scope = await _scope(ctx)
    return (await service.get_contact_for_owners(
        contact_item_id=contact_id, owner_agent_ids=scope.agent_ids,
    )).model_dump(mode="json")


@mcp_tool("contact", name="contact_create", approval="ask",
    approval_reason="Create an address-book entry within the delegated scope; this can affect the owner's inbound Mail admission",
    description=("Create a Contact in your address book by default, or specify owner_agent_id within your Contact scope. "
                 "Supply a display_name and at least one email, phone or postal address. Search the target address book "
                 "with contact_list first. Creates no user and sends no message. A saved email becomes a known contact "
                 "for the address-book owner's default inbound Mail policy."),
    conversation_policy="short")
async def mcp_contact_create(
    ctx: McpToolContext,
    display_name: Annotated[str, Field(min_length=1, max_length=500)],
    email: Annotated[str, Field(max_length=320)] | None = None,
    coordinates: ContactCoordinates | None = None,
    owner_agent_id: Annotated[int, Field(gt=0)] | None = None,
) -> dict[str, object]:
    owner_id = ctx.agent_id if owner_agent_id is None else owner_agent_id
    data = ContactCreate.model_validate({"agent_id": owner_id, "display_name": display_name,
                                        "email": email, "coordinates": coordinates})
    (await _scope(ctx)).require(owner_id)
    if owner_id != ctx.agent_id and await get_agent_record(owner_id) is None:
        raise MemoryNotFoundError("Contact directory not found.")
    await lock_contact_directory(owner_id)
    (await _scope(ctx)).require(owner_id)
    return (await service.create_contact(data)).model_dump(mode="json")


@mcp_tool("contact", name="contact_update", approval="ask",
    approval_reason="Modify a contact within the delegated scope",
    description=("Update a Contact's display_name within your delegated Contact scope and optionally replace its phone numbers and postal addresses. "
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
    scope = await _scope(ctx)
    contact = await service.get_contact_for_owners(contact_item_id=contact_id, owner_agent_ids=scope.agent_ids)
    await lock_contact_directory(contact.owner_agent_id)
    if not (await _scope(ctx)).allows(contact.owner_agent_id):
        raise MemoryNotFoundError("Contact not found.")
    return (await service.update_contact(contact_item_id=contact_id, data=data)).model_dump(mode="json")
