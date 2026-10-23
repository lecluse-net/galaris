"""Document sharing tools, independent of the personal-memory provider."""

import json
from typing import Literal
from uuid import UUID

from app.tools import McpToolContext, mcp_tool

from . import item_sharing


def _identity(value: str) -> UUID:
    return UUID(value.strip().removeprefix("document://"))


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
    description="Share an owned HTML Document with exactly one agent_id, user_id or team_id. Access read/edit grants access; none revokes only that direct grant. First call document_sharing for recipient IDs and expected_lock_version. Linking a Document never grants access.")
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
