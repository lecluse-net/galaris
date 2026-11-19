"""Domain operations for shared Documents and their revisions."""

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.agent import EffectDescriptorV1
from app.services import McpToolContext, mcp_tool

from . import item_sharing, resource_service
from .formats import DocumentRevisionRegion

DocumentUri = Annotated[str, Field(pattern=r"^document://[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")]
RevisionNumber = Annotated[int, Field(ge=1)]


def _identity(value: str) -> UUID:
    return UUID(value.strip().removeprefix("document://"))


@mcp_tool("document", name="document_revision_list", approval="enabled", conversation_policy="short",
    approval_reason="Read saved content revision history for an accessible document",
    description="List saved document content versions, newest first. Use their exact revision numbers with file_read or document_revision_compare.",
    effect_descriptor=EffectDescriptorV1(capability="file.read", kind="read", target_arguments=("document_id",),
        idempotence="read_only", receipt="resource"), effect_policy="read", concurrency_policy="safe")
async def document_revision_list(ctx: McpToolContext, document_id: DocumentUri,
    offset: Annotated[int, Field(ge=0)] = 0, limit: Annotated[int, Field(ge=1, le=50)] = 20) -> str:
    identity = _identity(document_id)
    page = await resource_service.list_document_content_revisions(identity, actor_agent_id=ctx.agent_id,
        offset=offset, limit=limit)
    return json.dumps({"uri": f"document://{identity}", **page.model_dump(mode="json", exclude={
        "items": {"__all__": {"author_user_id", "author_agent_id", "task_id"}},
    })}, ensure_ascii=False)


@mcp_tool("document", name="document_revision_compare", approval="enabled", conversation_policy="short",
    approval_reason="Read and compare two saved content revisions of an accessible document",
    description="Compare two saved document revisions. Supported drawing formats report pixel changes, optionally restricted to a rectangle in source pixels. A content_hash comparison only reports that bytes differ.",
    effect_descriptor=EffectDescriptorV1(capability="file.read", kind="read", target_arguments=("document_id",),
        idempotence="read_only", receipt="resource"), effect_policy="read", concurrency_policy="safe")
async def document_revision_compare(ctx: McpToolContext, document_id: DocumentUri,
    before_revision: RevisionNumber, after_revision: RevisionNumber, region: DocumentRevisionRegion | None = None) -> str:
    result = await resource_service.compare_document_content_revisions(_identity(document_id), before_revision,
        after_revision, actor_agent_id=ctx.agent_id, region=region)
    return json.dumps(result, ensure_ascii=False)


@mcp_tool("document", name="document_sharing", approval="enabled",
    approval_reason="Read the current permissions of an accessible document",
    description="Inspect an owned Document's grants, recipient options and lock_version. Pass its document:// URI or UUID. Use the returned recipient IDs and lock_version with document_share. Paginate options with offset/limit (50 by default, maximum 500).",
    effect_policy="read", concurrency_policy="safe")
async def document_sharing(ctx: McpToolContext, document_id: str, search: str = "",
    kind: Literal["agent", "user", "team"] | None = None, offset: int = 0, limit: int = 50) -> str:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("Invalid recipient pagination")
    state = await item_sharing.agent_sharing(_identity(document_id), agent_id=ctx.agent_id)
    options = [option for option in state.options if (kind is None or option.kind == kind)
        and search.strip().casefold() in option.label.casefold()]
    return json.dumps({**state.model_dump(mode="json", exclude={"options"}),
        "options": [option.model_dump(mode="json") for option in options[offset:offset+limit]],
        "total": len(options), "has_more": offset+limit < len(options)}, ensure_ascii=False)


@mcp_tool("document", name="document_share", approval="ask",
    approval_reason="Change access to a shared Document",
    description="Share an owned Document with exactly one agent_id, user_id or team_id. Access read/edit grants access; none revokes only that direct grant. First call document_sharing for recipient IDs and expected_lock_version. Linking a Document never grants access.")
async def document_share(ctx: McpToolContext, document_id: str, agent_id: int | None = None,
    access: Literal["read", "edit", "none"] = "edit", team_id: int | None = None,
    user_id: int | None = None, expected_lock_version: int | None = None) -> str:
    targets: list[tuple[Literal["agent", "user", "team"], int]] = []
    if agent_id is not None:
        targets.append(("agent", agent_id))
    if user_id is not None:
        targets.append(("user", user_id))
    if team_id is not None:
        targets.append(("team", team_id))
    if len(targets) != 1 or targets[0][1] <= 0:
        raise ValueError("Supply exactly one positive agent_id, user_id or team_id")
    kind, target = targets[0]
    identity = _identity(document_id)
    state = await item_sharing.update_agent_sharing(identity, agent_id=ctx.agent_id,
        kind=kind, target_id=target, access=access, expected_lock_version=expected_lock_version,
        document_only=True)
    return json.dumps({"document_id": str(identity), "uri": f"document://{identity}",
        **state.model_dump(mode="json", exclude={"options"})}, ensure_ascii=False)
